import redis, json
from ib_insync import *
import asyncio, time, random
import sys

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
        print(message)

        message_data = json.loads(message['data'])

        # Normalization -- this is where you could check passwords, normalize from "short ETFL" to "long ETFS", etc.
        if message_data['ticker'] == 'NQ1!':
            #stock = Future('MNQ', '20220916', 'GLOBEX') # go with mini futures for Q's for now, keep risk managed
            stock = Future('NQ', '20220916', 'GLOBEX') # go with mini futures for Q's for now, keep risk managed
        elif message_data['ticker'] == 'QQQ': # assume QQQ->NQ (sometimes QQQ signals are helpful for gap plays)
            stock = Future('NQ', '20220916', 'GLOBEX')
            if (message_data['order_contracts'] > 0):
                message_data['order_contracts'] = 1
            else:
                message_data['order_contracts'] = -1
        elif message_data['ticker'] == 'ES1!':
            #stock = Future('MES', '20220916', 'GLOBEX') # go with mini futures for now
            stock = Future('ES', '20220916', 'GLOBEX') # go with mini futures for now
        elif message_data['ticker'] == 'SPY': # assume SPY->ES
            stock = Future('ES', '20220916', 'GLOBEX')
            if (message_data['order_contracts'] > 0):
                message_data['order_contracts'] = 1
            else:
                message_data['order_contracts'] = -1
        elif message_data['ticker'] == 'RTY1!':
            #stock = Future('M2K', '20220916', 'GLOBEX') # go with mini futures for now
            stock = Future('RTY', '20220916', 'GLOBEX') # go with mini futures for now
        elif message_data['ticker'] == 'CL1!':
            stock = Future('CL', '20220920', 'NYMEX')
        elif message_data['ticker'] == 'NG1!':
            stock = Future('NG', '20220920', 'NYMEX')
        elif message_data['ticker'] == 'HG1!':
            stock = Future('HG', '20220928', 'NYMEX')
        elif message_data['ticker'] == '6J1!':
            stock = Future('J7', '20220919', 'GLOBEX')
        elif message_data['ticker'] == 'HEN2022':
            stock = Future('HE', '20220715', 'NYMEX')
        else:
            stock = Stock(message_data['ticker'], 'SMART', 'USD')

        if account != message_data['strategy']['account']:
            print("Skipped; intended for another account: "+message_data['strategy']['account'])
        else:
            order = MarketOrder(message_data['strategy']['order_action'], message_data['strategy']['order_contracts'])
            #ib.qualifyOrder(order)
            trade = ib.placeOrder(stock, order)
            print(trade)
            

async def run_periodically(interval, periodic_function):
    global run
    while run < 3600: # quit about once an hour (and let the looping wrapper script restart this)
        await asyncio.gather(asyncio.sleep(interval), periodic_function())
        run = run + 1

asyncio.run(run_periodically(1, check_messages))

ib.run()
