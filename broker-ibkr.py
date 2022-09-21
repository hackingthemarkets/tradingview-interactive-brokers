import redis, json
from ib_insync import *
import asyncio, time, random
import sys
import nest_asyncio

nest_asyncio.apply()

# connect to Interactive Brokers (try all 4 options)
ib = IB()
print("Trying to connect...")

# arguments: broker-ibkr.py [port] [account]
if len(sys.argv) != 3:
    print("Usage: " + sys.argv[0] + " [port] [account]")
    quit()

# note [mode] needs to be set in the TV alert json in the strategy section, ie mode='live'
# ports are typically: 
#  7496 = TW-live
#  4001 = Gateway-live
#  7497 = TW-paper
#  4002 = Gateway-paper
ib.connect('127.0.0.1', int(sys.argv[1]), clientId=1)

account = sys.argv[2]

# connect to Redis and subscribe to tradingview messages
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('tradingview')
run = 1

print("Waiting for webhook messages...")
async def check_messages():
    #print(f"{time.time()} - checking for tradingview webhook messages")
    message = p.get_message()
    if message is not None and message['type'] == 'message':
        print("***")
        print(message)

        data_dict = json.loads(message['data'])
        ## extract data from TV payload received via webhook
        order_symbol          = data_dict['ticker']                             # ticker for which TV order was sent
        order_price           = data_dict['strategy']['order_price']            # purchase price per TV
        market_position       = data_dict['strategy']['market_position']        # after order, long, short, or flat
        market_position_size  = data_dict['strategy']['market_position_size']   # desired position after order per TV

        round_precision = 2 # position variation minimum varies by security; start by assuming cents

        ## NORMALIZATION -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.
        if data_dict['ticker'] == 'NQ1!':
            order_symbol = 'NQ'
            stock = Future(order_symbol, '20221216', 'GLOBEX') # go with mini futures for Q's for now, keep risk managed
            round_precision = 1
        elif data_dict['ticker'] == 'ES1!':
            order_symbol = 'ES'
            stock = Future(order_symbol, '20221216', 'GLOBEX') # go with mini futures for now
            round_precision = 1
        elif data_dict['ticker'] == 'RTY1!':
            order_symbol = 'RTY'
            stock = Future(order_symbol, '20221216', 'GLOBEX') # go with mini futures for now
            round_precision = 1
        elif data_dict['ticker'] == 'CL1!':
            order_symbol = 'CL'
            stock = Future(order_symbol, '20220920', 'NYMEX')
            round_precision = 1
        elif data_dict['ticker'] == 'NG1!':
            order_symbol = 'NG'
            stock = Future(order_symbol, '20220920', 'NYMEX')
            round_precision = 1
        elif data_dict['ticker'] == 'HG1!':
            order_symbol = 'HG'
            stock = Future(order_symbol, '20220928', 'NYMEX')
            round_precision = 1
        elif data_dict['ticker'] == '6J1!':
            order_symbol = 'J7'
            stock = Future(order_symbol, '20220919', 'GLOBEX')
            round_precision = 1
        elif data_dict['ticker'] == 'HEN2022':
            order_symbol = 'HE'
            stock = Future(order_symbol, '20220715', 'NYMEX')
            round_precision = 1
        elif data_dict['exchange'] == 'TSX':
            stock = Stock(order_symbol, 'TSE', 'CAD')
        else:
            stock = Stock(order_symbol, 'SMART', 'USD')

        ## PLACING THE ORDER

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
        high_limit_price = round(max(order_price, bar_high) * 1.005, round_precision)
        low_limit_price  = round(min(order_price, bar_low) * 0.995, round_precision)

        #######################################################################
        #### check if there is already a position for the order_symbol
        #######################################################################

        position = 0
        current_qty = 0.0

        # TODO: limit only to the selected account
        print("getting positions")
        print(ib.positions())
        for i in ib.positions():
            if i.contract.symbol == order_symbol:
                position = i.position
                current_qty = i.position

        #######################################################################
        #### cancel if there are open orders for the order_symbol
        #######################################################################

        #orders = api.list_orders(status="open")
        #for order in orders:
        #    if (order.symbol == order_symbol):
        #        api.cancel_order(order.id)

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
                print('sending order to reduce short position to flat')
            else:
                closing_side = "sell"
                limit_price = low_limit_price
                print('sending order to reduce long position to flat')

            order = LimitOrder(closing_side, abs(current_qty), limit_price)
            order.outsideRth = True
            # order.Account = ?? #TODO
            trade = ib.placeOrder(stock, order)
            ib.waitOnUpdate()
            print('done order')


        ########################################################
        ## Now, place the order to build up the desired position
        ########################################################

        if desired_qty != current_qty:
            if opposite_sides:
                order_qty = desired_qty
            else:
                order_qty = abs(desired_qty - current_qty)

            if (desired_qty > current_qty):
                desired_action = "buy"
                limit_price = high_limit_price
            else:
                desired_action = "sell"
                limit_price = low_limit_price

            print('sending order to reach desired position, to price limit',limit_price,' low=',low_limit_price,' high=',high_limit_price)
            order = LimitOrder(desired_action, order_qty, limit_price)
            order.outsideRth = True
            # order.Account = ?? #TODO
            trade = ib.placeOrder(stock, order)
            ib.waitOnUpdate()
            print('done order')
        else:
            print('desired quantity is the same as the current quantity.  No order placed.')



async def run_periodically(interval, periodic_function):
    global run
    while run < 3600: # quit about once an hour (and let the looping wrapper script restart this)
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        run = run + 1

asyncio.run(run_periodically(1, check_messages))

ib.run()
