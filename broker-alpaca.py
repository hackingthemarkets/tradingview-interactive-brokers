import redis, json
import alpaca_trade_api as tradeapi
import asyncio, time, random
import sys

# Usage: broker-alpaca.py [apikey] [apisecret]

api = tradeapi.REST(sys.argv[1], sys.argv[2], base_url='https://paper-api.alpaca.markets')


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
        print(message)

        data_dict = json.loads(message['data'])

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

        bar_high     = data_dict['bar']['high']                        # previous bar high per TV payload
        bar_low      = data_dict['bar']['low']                         # previous bar low per TV payload

        ## calculate a conservative limit order
        high_limit_price = round(max(order_price, bar_high) * 1.01, 2)
        low_limit_price  = round(min(order_price, bar_low) * 0.99, 2)

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
        for order in orders:
            if (order.symbol == order_symbol):
                api.cancel_order(order.id)

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
            print('Waiting for 1 second ...')
            sleep(1)


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


async def run_periodically(interval, periodic_function):
    global run
    while run < 3600: # quit about once an hour (and let the looping wrapper script restart this)
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        run = run + 1

asyncio.run(run_periodically(1, check_messages))

