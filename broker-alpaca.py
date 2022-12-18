import redis, json
import alpaca_trade_api as tradeapi
import asyncio, time, random, datetime
import sys
import configparser
import traceback
from textmagic.rest import TextmagicRestClient

# Usage: broker-alpaca.py [apikey] [apisecret] [bot]
if len(sys.argv) != 2:
    print("Usage: " + sys.argv[0] + " [bot]")
    quit()

config = configparser.ConfigParser()
config.read('config.txt')

alpkey = config['DEFAULT']['alpaca-key']
alpsec = config['DEFAULT']['alpaca-secret']
api = tradeapi.REST(alpkey, alpsec, base_url='https://paper-api.alpaca.markets')

bot = sys.argv[1]

last_time_traded = {}

# connect to Redis and subscribe to tradingview messages
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('tradingview')
run = 1

print("Waiting for webhook messages...")
async def check_messages():
    try:

        #print(f"{time.time()} - checking for tradingview webhook messages")
        message = p.get_message()
        if message is not None and message['type'] == 'message':

            if message['data'] == b'health check':
                print("health check received")
                time.sleep(1)
                r.publish('health', 'ok')
                return

            r.publish('health', 'ok')

            print("*** ",datetime.datetime.now())
            print(message)

            data_dict = json.loads(message['data'])

            if 'bot' not in data_dict['strategy']:
                raise Exception("You need to indicate the bot in the strategy portion of the json payload")
                return
            if bot != data_dict['strategy']['bot']:
                print("signal intended for different bot '",data_dict['strategy']['bot'],"', skipping")
                return

            # Normalization -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.
            #if message_data['ticker'] == 'QQQ': # hack for now -- the QQQ trade is a gap play in premarket where I use NQ, so skip on Alpaca
            #    return;

            # Place order
            ## extract data from TV payload received via webhook
            order_symbol          = data_dict['ticker']                             # ticker for which TV order was sent
            order_price           = data_dict['strategy']['order_price']            # purchase price per TV
            market_position       = data_dict['strategy']['market_position']        # after order, long, short, or flat
            market_position_size  = data_dict['strategy']['market_position_size']   # desired position after order per TV

            ## set the order_qty sign based on whether the final position is long or short
            if (market_position == "long"):
                desired_qty = +market_position_size
            elif (market_position == "short"):
                desired_qty = -market_position_size
            else:
                desired_qty = 0.0

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

            bar_high     = data_dict['bar']['high']                        # previous bar high per TV payload
            bar_low      = data_dict['bar']['low']                         # previous bar low per TV payload

            ## calculate a conservative limit order
            high_limit_price = round(max(order_price, bar_high) * 1.005, 2)
            low_limit_price  = round(min(order_price, bar_low) * 0.995, 2)

           #######################################################################
            #### check if there is already a position for the order_symbol
            #######################################################################

            try:
                position      = api.get_position(order_symbol)
                current_qty  = float(position.qty)

            except:
                current_qty = 0.0

            #######################################################################
            #### cancel if there are open positions for the order_symbol
            #######################################################################

            orders = api.list_orders(status="open")

            order_canceled = False

            for order in orders:
                if (order.symbol == order_symbol):
                    api.cancel_order(order.id)
                    order_canceled = True

            if order_canceled:
                # Wait for unexecuted order to be canceled ...
                print('Asked Alpaca to cancel open order.  Waiting for 5 seconds for it to be canceled...')
                time.sleep(5)

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


                order = api.submit_order(symbol = order_symbol,
                                         qty = abs(current_qty),
                                         side = closing_side,
                                         type = 'limit',
                                         time_in_force = 'day',
                                         limit_price = limit_price,
                                         extended_hours = True
                                         )

                print('Alpaca close order success: ', order_symbol, closing_side, abs(current_qty))

                print(order)

                # Wait a second for position close order to fill...
                print('Waiting for 10 seconds ...')
                time.sleep(10)


            ########################################################
            ## Now, place the order to build up the desired position
            ########################################################

            if desired_qty != current_qty:
                if opposite_sides:
                    order_qty = abs(desired_qty)
                else:
                    order_qty = abs(desired_qty - current_qty)

                if (desired_qty > current_qty):
                    desired_action = "buy"
                    limit_price = high_limit_price
                else:
                    desired_action = "sell"
                    limit_price = low_limit_price

                order = api.submit_order(symbol = order_symbol,
                                         qty = order_qty,
                                         side = desired_action,
                                         type = 'limit',
                                         time_in_force = 'day',
                                         limit_price = limit_price,
                                         extended_hours = True
                                         )

                print('order to build up the desired position')
                print(order)
            else:
                print('desired quantity is the same as the current quantity.  No order placed.')

    except Exception as e:
        handle_ex(e)
        raise


def handle_ex(e):
    tmu = config['DEFAULT']['textmagic-username']
    tmk = config['DEFAULT']['textmagic-key']
    tmp = config['DEFAULT']['textmagic-phone']
    if tmu != '':
        tmu = config['DEFAULT']['textmagic-username']
        tmk = config['DEFAULT']['textmagic-key']
        tmp = config['DEFAULT']['textmagic-phone']

        tmc = TextmagicRestClient(tmu, tmk)
        message = tmc.messages.create(phones=tmp, text="broker-ibkr " + bot + " FAIL " + traceback.format_exc())

async def run_periodically(interval, periodic_function):
    global run
    while run < 3600: # quit about once an hour (and let the looping wrapper script restart this)
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        run = run + 1

asyncio.run(run_periodically(1, check_messages))

