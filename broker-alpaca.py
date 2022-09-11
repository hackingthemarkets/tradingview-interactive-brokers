import redis, json
import alpaca_trade_api as tradeapi
import asyncio, time, random
import sys

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

        message_data = json.loads(message['data'])

        # Normalization -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.


        # Place order
        price = message_data['strategy']['order_price']
        quantity = message_data['strategy']['order_contracts']
        symbol = message_data['ticker']
        side = message_data['strategy']['order_action']

        order = api.submit_order(symbol, quantity, side, 'limit', 'gtc', limit_price=price)
        print(order)

async def run_periodically(interval, periodic_function):
    global run
    while run < 3600: # quit about once an hour (and let the looping wrapper script restart this)
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        run = run + 1

asyncio.run(run_periodically(1, check_messages))

