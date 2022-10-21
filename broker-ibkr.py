import redis, json
from ib_insync import *
import asyncio, time, random, datetime
import sys
import nest_asyncio
import configparser
import traceback
from textmagic.rest import TextmagicRestClient

nest_asyncio.apply()


# arguments: broker-ibkr.py [port] [bot]
if len(sys.argv) != 3:
    print("Usage: " + sys.argv[0] + " [port] [bot]")
    quit()

bot = sys.argv[2]

last_time_traded = {}

config = configparser.ConfigParser()
config.read('config.txt')

def handle_ex(e):
    tmu = config['DEFAULT']['textmagic-username']
    tmk = config['DEFAULT']['textmagic-key']
    tmp = config['DEFAULT']['textmagic-phone']
    if tmu != '':
        tmu = config['DEFAULT']['textmagic-username']
        tmk = config['DEFAULT']['textmagic-key']
        tmp = config['DEFAULT']['textmagic-phone']

        tmc = TextmagicRestClient(tmu, tmk)
        message = tmc.messages.create(phones=tmp, text="broker-ibkr " + bot + " FAIL " + traceback.format_exc()[0:300])

# note [bot] needs to be set in the TV alert json in the strategy section, ie bot='live'
# ports are typically: 
#  7496 = TW-live
#  4001 = Gateway-live
#  7497 = TW-paper
#  4002 = Gateway-paper

# connect to Interactive Brokers
ib = IB()
print("Trying to connect...")

try:
    ib.connect('127.0.0.1', int(sys.argv[1]), clientId=1)
except Exception as e:
    handle_ex(e)
    raise

# connect to Redis and subscribe to tradingview messages
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('tradingview')
run = 1

# function to round to the nearest decimal. y=10 for dimes, y=4 for quarters, y=100 for pennies
def x_round(x,y):
    return round(x*y)/y

# figure out what account list to use, if any is specified
accounts = ['DEFAULT']
accountlist = config['DEFAULT']['accounts-'+bot]
if accountlist and accountlist != "":
    accounts = accountlist.split(",")

print("Waiting for webhook messages...")
async def check_messages():
    try:

        #print(f"{time.time()} - checking for tradingview webhook messages")
        global run
        if run > 3600: # quit about once an hour (and let the looping wrapper script restart this)
            quit
        run = run + 1

        message = p.get_message()
        if message is not None and message['type'] == 'message':
            print("*** ",datetime.datetime.now())
            print(message)

            data_dict = json.loads(message['data'])

            if 'bot' not in data_dict['strategy']:
                raise Exception("You need to indicate the bot in the strategy portion of the json payload")
                return
            if bot != data_dict['strategy']['bot']:
                print("signal intended for different bot '",data_dict['strategy']['bot'],"', skipping")
                return

            ## extract data from TV payload received via webhook
            order_symbol          = data_dict['ticker']                             # ticker for which TV order was sent
            order_price           = data_dict['strategy']['order_price']            # purchase price per TV
            market_position       = data_dict['strategy']['market_position']        # after order, long, short, or flat
            market_position_size_orig  = data_dict['strategy']['market_position_size']   # desired position after order per TV

            round_precision = 100 # position variation minimum varies by security; start by assuming cents

            ## NORMALIZATION -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.
            if data_dict['ticker'] == 'NQ1!':
                order_symbol = 'NQ'
                stock = Future(order_symbol, '20221216', 'GLOBEX') # go with mini futures for Q's for now, keep risk managed
                round_precision = 4
            elif data_dict['ticker'] == 'ES1!':
                order_symbol = 'ES'
                stock = Future(order_symbol, '20221216', 'GLOBEX') # go with mini futures for now
                round_precision = 4
            elif data_dict['ticker'] == 'RTY1!':
                order_symbol = 'RTY'
                stock = Future(order_symbol, '20221216', 'GLOBEX') # go with mini futures for now
                round_precision = 10
            elif data_dict['ticker'] == 'CL1!':
                order_symbol = 'CL'
                stock = Future(order_symbol, '20220920', 'NYMEX')
                round_precision = 10
            elif data_dict['ticker'] == 'NG1!':
                order_symbol = 'NG'
                stock = Future(order_symbol, '20220920', 'NYMEX')
                round_precision = 10
            elif data_dict['ticker'] == 'HG1!':
                order_symbol = 'HG'
                stock = Future(order_symbol, '20220928', 'NYMEX')
                round_precision = 10
            elif data_dict['ticker'] == '6J1!':
                order_symbol = 'J7'
                stock = Future(order_symbol, '20220919', 'GLOBEX')
                round_precision = 10
            elif data_dict['ticker'] == 'HEN2022':
                order_symbol = 'HE'
                stock = Future(order_symbol, '20220715', 'NYMEX')
                round_precision = 10
            elif data_dict['exchange'] == 'TSX':
                stock = Stock(order_symbol, 'SMART', 'CAD')
            else:
                stock = Stock(order_symbol, 'SMART', 'USD')

            for account in accounts:
                ## PLACING THE ORDER

                if account == "DEFAULT":
                    market_position_size = market_position_size_orig
                else:
                    multstr = config[account]["multiplier"]
                    if multstr and multstr != "":
                        market_position_size = round(market_position_size_orig * float(multstr))
                    else:
                        throw("You need to specify the multiplier for account " + account + " in config.txt")

                print("working on trade for account ", account, " symbol ", order_symbol, " to position ", market_position_size, " at price ", order_price)

                # Place order

                ## set the order_qty sign based on whether the final position is long or short
                if (market_position == "long"):
                    desired_qty = +market_position_size
                elif (market_position == "short"):
                    desired_qty = -market_position_size
                else:
                    desired_qty = 0.0

                bar_high     = data_dict['bar']['high']                        # previous bar high per TV payload
                bar_low      = data_dict['bar']['low']                         # previous bar low per TV payload

                ## calculate a conservative limit order
                high_limit_price = x_round(max(order_price, bar_high) * 1.005, round_precision)
                low_limit_price  = x_round(min(order_price, bar_low) * 0.995, round_precision)

                #######################################################################
                ## Check if the time lapsed between previous order and current order
                ## is less than 2 minutes.  If so, check if the current order qty
                ## is zero. i.e., it is closing active position. If so, skip the order.
                #######################################################################

                current_time = datetime.datetime.now()
                last_time = datetime.datetime(1970,1,1)
                if order_symbol+bot in last_time_traded:
                    last_time = last_time_traded[order_symbol+bot] 
                delta = current_time - last_time
                last_time_traded[order_symbol+bot] = current_time

                if (delta.total_seconds() < 120):
                    if desired_qty == 0:
                        print("skipping order, seems to be a direction changing exit")
                        return

                #######################################################################
                #### check if there is already a position for the order_symbol
                #######################################################################

                position = 0
                current_qty = 0.0

                print("getting positions")
                positions = ib.positions()
                print(positions)
                for i in positions:
                    if i.contract.symbol == order_symbol and (account=='DEFAULT' or i.account==account):
                        position = i.position
                        current_qty = i.position

                #######################################################################
                #### cancel if there are open orders for the order_symbol
                #######################################################################

                print("getting trades")
                opentrades = ib.openTrades()
                print(opentrades)
                for t in opentrades:
                    if t.contract.symbol == order_symbol and (account=='DEFAULT' or t.order.account==account):
                        ib.cancelOrder(t.order)

                ########################################################################
                ### if there is an existing position but in the opposite direction
                ### api doesn't allow directly going from long to short ot short to long
                ### so, close the opposite position first before opening the order
                ########################################################################

                opposite_sides = (current_qty < 0 and desired_qty > 0) or (current_qty > 0 and desired_qty < 0)

                if opposite_sides:
                # existing position is in the opposite direction of order

                    if (current_qty < 0):
                        closing_side = "buy"
                        limit_price = high_limit_price
                        print('sending order to reduce short position to flat, to price limit',limit_price,' low=',low_limit_price,' high=',high_limit_price)
                    else:
                        closing_side = "sell"
                        limit_price = low_limit_price
                        print('sending order to reduce long position to flat, to price limit',limit_price,' low=',low_limit_price,' high=',high_limit_price)

                    order = LimitOrder(closing_side, abs(current_qty), limit_price)
                    order.outsideRth = True
                    # order.Account = ?? #TODO
                    trade = ib.placeOrder(stock, order)
                    maxloop = 60   # 60s time limit for the flattening order
                    while not trade.isDone():
                        ib.sleep(1)
                        maxloop = maxloop - 1
                        if maxloop == 0:
                            raise Exception('** CASHING OUT ORDER TIMEOUT! Aborting to look for new orders')
                            return
                    current_qty = 0
                    print('done order')


                ########################################################
                ## Now, place the order to build up the desired position
                ########################################################

                if desired_qty != current_qty:
                    order_qty = abs(desired_qty - current_qty)

                    if (desired_qty > current_qty):
                        desired_action = "buy"
                        limit_price = high_limit_price
                    else:
                        desired_action = "sell"
                        limit_price = low_limit_price

                    print('sending order to reach desired position, to quantity',desired_qty,', price limit',limit_price)
                    order = LimitOrder(desired_action, order_qty, limit_price)
                    order.outsideRth = True
                    if account != 'DEFAULT': order.account = account
                    trade = ib.placeOrder(stock, order)
                    ib.sleep(1)
                    print('done placing order')
                else:
                    print('desired quantity is the same as the current quantity.  No order placed.')


    except Exception as e:
        handle_ex(e)
        raise

async def run_periodically(interval, periodic_function):
    while True:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())

asyncio.run(run_periodically(1, check_messages))

ib.run()
