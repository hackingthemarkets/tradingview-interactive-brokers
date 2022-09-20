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
        order_price  = data_dict['strategy']['order_price']            # purchase price per TV
        order_action = data_dict['strategy']['order_action']           # buy or sell per TV
        order_qty    = data_dict['strategy']['market_position_size']   # desired position after order per TV
        order_symbol = data_dict['ticker']                             # ticker for which TV order was sent

        bar_high     = data_dict['bar']['high']                        # previous bar high per TV payload
        bar_low      = data_dict['bar']['low']                         # previous bar low per TV payload
        
        ## calculate a conservative limit order
        high_limit_price = round(max(order_price, bar_high) * 1.01, 2)
        low_limit_price  = round(min(order_price, bar_low) * 0.99, 2)
            
        #######################################################################
        #### check if there is already an open position for the order_symbol
        #######################################################################

        position = 0
        try:
            position      = api.get_position(order_symbol)
            position_qty  = float(position.qty)

        except:
            position_qty = 0.0

        ########################################################################
        ### if there is an existing position but in the opposite direction
        ### api doesn't allow directly going from long to short ot short to long
        ### so, close the opposite position first before opening the order
        ########################################################################
        
        opposite_sides = (position_qty < 0 and order_qty > 0) or (position_qty > 0 and order_qty < 0)

        if opposite_sides:  
        # existing position is in the opposite direction of order
        
            if (position_qty < 0):
                closing_side = "buy"
                limit_price = high_limit_price
                print('sending order to reduce short position to flat')
            else:
                closing_side = "sell"
                limit_price = low_limit_price
                print('sending order to reduce long position to flat')
     
            try:
                order = api.submit_order(symbol = order_symbol, 
                                         qty = abs(position_qty),
                                         side = closing_side, 
                                         type = 'limit',
                                         time_in_force = 'day',
                                         limit_price = limit_price,
                                         extended_hours = True
                                         )
            
                print('Alpaca close order success: ', order_symbol, closing_side, abs(position_qty))
                
                # Wait a second for position close order to fill...
                print('Waiting for 1 second ...')
                sleep(1)
                
            except:
                print('Alpaca close order failure: ', order_symbol, closing_side, abs(position_qty))      
            
      
        elif (position != 0):  
        # existing position is in the same direction as the order
        # no need to close existing position.  Just adjust its size to order_size
        
            if (position_qty > order_qty):
                try:
                    order = api.submit_order(symbol = order_symbol, 
                                             qty = position_qty - order_qty,
                                             side = 'sell', 
                                             type = 'limit',
                                             time_in_force = 'day',
                                             limit_price = low_limit_price,
                                             extended_hours = True
                                             )
                    print('reducing existing position to match order size')
                except:
                    print('failed to reduce existing position to match order size')
                    
            elif (position_qty < order_qty):
                try:
                    order = api.submit_order(symbol = order_symbol, 
                                             qty = order_qty - position_qty,
                                             side = 'buy', 
                                             type = 'limit',
                                             time_in_force = 'day',
                                             limit_price = high_limit_price,
                                             extended_hours = True
                                             )
                    print('increasing existing position to match order size')
                                       
                except:
                    print('failed to increase existing position to match order size')
            else:
                print('existing position matches order size.  Nothing to do.')
            

        else: 
        # no position exists for order_symbol, so open a new one

            try:
                if order_action == 'buy':
                    limit_price = high_limit_price
                else:
                    limit_price = low_limit_price
                    
                order = api.submit_order(symbol = order_symbol, 
                                         qty = order_qty,
                                         side = order_action, 
                                         type = 'limit',
                                         time_in_force = 'day',
                                         limit_price = limit_price,
                                         extended_hours = True
                                         )
                print('Alpaca order success: ', order_symbol, order_action, order_qty)
            except:
                print('Alpaca order failure: ', order_symbol, order_action, order_qty)
    

        print(order)


async def run_periodically(interval, periodic_function):
    global run
    while run < 3600: # quit about once an hour (and let the looping wrapper script restart this)
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        run = run + 1

asyncio.run(run_periodically(1, check_messages))

