import redis, json
from ib_insync import *
import asyncio, time, random

# connect to Interactive Brokers 
ib = IB()
#ib.connect('127.0.0.1', 7497, clientId=1)
ib.connect('127.0.0.1', 4001, clientId=1) # live account on IB gateway
#ib.connect('127.0.0.1', 4002, clientId=1) # paper account on IB gateway


# connect to Redis and subscribe to tradingview messages
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('tradingview')

async def check_messages():
    print(f"{time.time()} - checking for tradingview webhook messages")
    message = p.get_message()
    if message is not None and message['type'] == 'message':
        print(message)

        message_data = json.loads(message['data'])

        # Normalization -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.
        if message_data['ticker'] == 'NQ1!':
            stock = Future('NQ', '20220617', 'GLOBEX')
        else:
            stock = Stock(message_data['ticker'], 'SMART', 'USD')
        order = MarketOrder(message_data['strategy']['order_action'], message_data['strategy']['order_contracts'])
        #ib.qualifyOrder(order)
        trade = ib.placeOrder(stock, order)

async def run_periodically(interval, periodic_function):
    while True:
        await asyncio.gather(asyncio.sleep(interval), periodic_function())

asyncio.run(run_periodically(1, check_messages))

ib.run()
