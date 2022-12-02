import redis, json
from ib_insync import *
import asyncio, time, random, datetime
import sys
import nest_asyncio
import configparser
import traceback
import math
import yfinance as yf
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

# function to round to the nearest decimal. y=10 for dimes, y=4 for quarters, y=100 for pennies
def x_round(x,y):
    return round(x*y)/y

# figure out what account list to use, if any is specified
accounts = ['DEFAULT']
accountlist = config['DEFAULT']['accounts-'+bot]
if accountlist and accountlist != "":
    accounts = accountlist.split(",")

def get_price(symbol, stock):
    #stockdata = yf.Ticker(symbol).info
    #print("stock ", symbol, " : ", stockdata)
    #return stockdata['regularMarketPrice']

    #ib.reqMarketDataType(4)
    #ticker = ib.reqMktData(contract)
    #while ticker.last != ticker.last: 
    #    ib.sleep(0.01) #Wait until data is in. 
    #ib.cancelMktData(contract)
    [ticker] = ib.reqTickers(stock)
    if math.isnan(ticker.last):
        if math.isnan(ticker.close):
            raise Exception("error trying to retrieve stock price for " + symbol)
        else:
            precio = ticker.close
            tipo = 'Close'
    else:
        precio = ticker.last
        tipo = 'Last'
    print("stock ", symbol, " : ", precio)
    return precio


print("Waiting for webhook messages...")
async def check_messages():
    try:

        #print(f"{time.time()} - checking for tradingview webhook messages")

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

            config.read('config.txt')

            ## extract data from TV payload received via webhook
            order_symbol_orig          = data_dict['ticker']                             # ticker for which TV order was sent
            order_price_orig           = data_dict['strategy']['order_price']            # purchase price per TV
            market_position_orig       = data_dict['strategy']['market_position']        # order direction: long, short, or flat
            market_position_size_orig  = data_dict['strategy']['market_position_size']   # desired position after order per TV

            round_precision = 100 # position variation minimum varies by security; start by assuming cents

            ## NORMALIZATION -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.
            is_futures = 1
            if order_symbol_orig == 'NQ1!':
                order_symbol_orig = 'NQ'
                stock_orig = Future(order_symbol_orig, '20221216', 'GLOBEX') # go with mini futures for Q's for now, keep risk managed
                round_precision = 4
            elif order_symbol_orig == 'ES1!':
                order_symbol_orig = 'ES'
                stock_orig = Future(order_symbol_orig, '20221216', 'GLOBEX') # go with mini futures for now
                round_precision = 4
            elif order_symbol_orig == 'RTY1!':
                order_symbol_orig = 'RTY'
                stock_orig = Future(order_symbol_orig, '20221216', 'GLOBEX') # go with mini futures for now
                round_precision = 10
            elif order_symbol_orig == 'CL1!':
                order_symbol_orig = 'CL'
                stock_orig = Future(order_symbol_orig, '20221220', 'NYMEX')
                round_precision = 10
            elif order_symbol_orig == 'NG1!':
                order_symbol_orig = 'NG'
                stock_orig = Future(order_symbol_orig, '20221220', 'NYMEX')
                round_precision = 10
            elif order_symbol_orig == 'HG1!':
                order_symbol_orig = 'HG'
                stock_orig = Future(order_symbol_orig, '20220928', 'NYMEX')
                round_precision = 10
            elif order_symbol_orig == '6J1!':
                order_symbol_orig = 'J7'
                stock_orig = Future(order_symbol_orig, '20220919', 'GLOBEX')
                round_precision = 10
            elif order_symbol_orig == 'HEN2022':
                order_symbol_orig = 'HE'
                stock_orig = Future(order_symbol_orig, '20220715', 'NYMEX')
                round_precision = 10
            elif data_dict['exchange'] == 'TSX':
                stock_orig = Stock(order_symbol_orig, 'SMART', 'CAD')
                is_futures = 0
            else:
                stock_orig = Stock(order_symbol_orig, 'SMART', 'USD')
                is_futures = 0

            order_price_orig           = get_price(order_symbol_orig, stock_orig)              # override price from IB

            for account in accounts:
                ## PLACING THE ORDER

                print("")

                order_symbol = order_symbol_orig
                order_price = order_price_orig
                market_position = market_position_orig
                market_position_size = market_position_size_orig
                stock = stock_orig

                # check for security conversion (generally futures to ETF); format is "mult x ETF"
                if order_symbol_orig in config[account]:
                    print("switching from ", order_symbol_orig, " to ", config[account][order_symbol_orig])
                    [switchmult, x, order_symbol] = config[account][order_symbol_orig].split()
                    switchmult = float(switchmult)
                    market_position_size = round(market_position_size * switchmult)
                    stock = Stock(order_symbol, 'SMART', 'USD') # TODO: have to make this assumption for now
                    order_price = get_price(order_symbol, stock)
                    is_futures = 0

                # check for global multipliers, vs whatever position sizes are coming in from TV
                if (config['DEFAULT']["multiplier"] != ""):
                    if not is_futures:
                        print("multiplying position by ",float(config['DEFAULT']["multiplier"]))
                        market_position_size = round(market_position_size * float(config['DEFAULT']["multiplier"]))

                # check for overall multipliers on the account, vs whatever position sizes are coming in from TV
                if account != "DEFAULT":
                    if (account in config 
                        and "multiplier" in config[account] 
                        and config[account]["multiplier"] != ""
                        ):
                        if not is_futures:
                            print("multiplying position by ",float(config[account]["multiplier"]))
                            market_position_size = round(market_position_size * float(config[account]["multiplier"]))
                    else:
                        throw("You need to specify the multiplier for account " + account + " in config.txt")

                print("** WORKING ON TRADE for account ", account, " symbol ", order_symbol, " to position ", market_position_size, " at price ", order_price)

                # check for futures permissions (default is allow)
                if is_futures and 'use-futures' in config[account] and config[account]['use-futures'] == 'no':
                    print("this account doesn't allow futures; skipping")
                    continue

                #######################################################################
                ## Fix from short to a short ETF, if this account needs it.
                #######################################################################
                if (market_position == 'short' 
                    and order_symbol in config['inverse-etfs']
                    and account != 'DEFAULT' 
                    and 'use-inverse-etf' in config[account] 
                    and config[account]['use-inverse-etf'] == 'yes'
                    ):

                    long_price = get_price(order_symbol, stock)
                    short_symbol = config['inverse-etfs'][order_symbol]
                    if data_dict['exchange'] == 'TSX':
                        stock = Stock(short_symbol, 'SMART', 'CAD')
                    else:
                        stock = Stock(short_symbol, 'SMART', 'USD')
                    order_symbol = short_symbol
                    short_price = get_price(order_symbol, stock)
                    order_price = short_price
                    market_position = "long"
                    market_position_size = round(market_position_size * long_price / short_price)
                    print("switching to short ETF ", order_symbol, " to position ", market_position_size, " at price ", order_price)

                    # TODO: handle long-short transitions
                    # TODO: handle go-flat orders (needs to sell both long and short ETF)


                # Place order

                ## set the order_qty sign based on whether the final position is long or short
                if (market_position == "long"):
                    desired_qty = +market_position_size
                elif (market_position == "short"):
                    desired_qty = -market_position_size
                else:
                    desired_qty = 0.0

                ## calculate a conservative limit order
                high_limit_price = x_round(order_price * 1.005, round_precision)
                low_limit_price  = x_round(order_price * 0.995, round_precision)

                #######################################################################
                ## Check if the time lapsed between previous order and current order
                ## is less than 2 minutes.  If so, check if the current order qty
                ## is zero. i.e., it is closing active position. If so, skip the order.
                #######################################################################

                current_time = datetime.datetime.now()
                last_time = datetime.datetime(1970,1,1)
                if order_symbol+bot in last_time_traded:
                    last_time = last_time_traded[order_symbol+bot+account] 
                delta = current_time - last_time
                last_time_traded[order_symbol+bot+account] = current_time

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
                #print(positions)
                for i in positions:
                    if i.contract.symbol == order_symbol and (account=='DEFAULT' or i.account==account):
                        position = i.position
                        current_qty = i.position

                #######################################################################
                #### cancel if there are open orders for the order_symbol
                #######################################################################

                #print("getting trades")
                #opentrades = ib.openTrades()
                #print(opentrades)
                #for t in opentrades:
                #    if t.contract.symbol == order_symbol and (account=='DEFAULT' or t.order.account==account):
                #        ib.cancelOrder(t.order)

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
                    if account != 'DEFAULT': order.account = account
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

runcount = 1
async def run_periodically(interval, periodic_function):
    global runcount
    while runcount < 3600:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        runcount = runcount + 1
    sys.exit()
asyncio.run(run_periodically(1, check_messages))

ib.run()
