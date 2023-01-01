import redis, json
import asyncio, time, random, datetime
import sys
import nest_asyncio
import configparser
import traceback
from textmagic.rest import TextmagicRestClient

nest_asyncio.apply()

from broker_ibkr import broker_ibkr
from broker_alpaca import broker_alpaca


# arguments: broker.py [bot]
if len(sys.argv) != 2:
    print("Usage: " + sys.argv[0] + " [bot]")
    quit()

bot = sys.argv[1]

last_time_traded = {}

config = configparser.ConfigParser()
config.read('config.ini')

def handle_ex(e):
    tmu = config['DEFAULT']['textmagic-username']
    tmk = config['DEFAULT']['textmagic-key']
    tmp = config['DEFAULT']['textmagic-phone']
    if tmu != '':
        tmc = TextmagicRestClient(tmu, tmk)
        # if e is a string send it, otherwise send the first 300 chars of the traceback
        if isinstance(e, str):
            message = tmc.messages.create(phones=tmp, text="broker-ibkr " + bot + " FAIL " + e)
        else:
            message = tmc.messages.create(phones=tmp, text="broker-ibkr " + bot + " FAIL " + traceback.format_exc()[0:300])

# connect to Redis and subscribe to tradingview messages
r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('tradingview')

# function to round to the nearest decimal. y=10 for dimes, y=4 for quarters, y=100 for pennies
def x_round(x,y):
    return round(x*y)/y

# figure out what account list to use, if any is specified
accountlist = config[f"bot-{bot}"]['accounts']
accounts = accountlist.split(",")


print("Waiting for webhook messages...")
async def check_messages():

    #print(f"{time.time()} - checking for tradingview webhook messages")

    message = p.get_message()
    if message is not None and message['type'] == 'message':
        print("*** ",datetime.datetime.now())
        print(message)

        if message['data'] == b'health check':
            try:
                print("health check received; checking every account")
                for account in accounts:
                    print("checking account",account)
                    config.read('config.txt')
                    aconfig = config[account]
                    if aconfig['driver'] == 'ibkr':
                        driver = broker_ibkr(bot, account)
                    elif aconfig['driver'] == 'alpaca':
                        driver = broker_alpaca(bot, account)
                    else:
                        raise Exception("Unknown driver: " + aconfig['driver'])
                    driver.health_check()

                r.publish('health', 'ok')
            except Exception as e:
                print(f"health check failed: {e}")

            return

        try:
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
            market_position_orig       = data_dict['strategy']['market_position']        # order direction: long, short, or flat
            market_position_size_orig  = data_dict['strategy']['market_position_size']   # desired position after order per TV


            for account in accounts:
                ## PLACING THE ORDER

                print("")

                aconfig = config[account]
                if aconfig['driver'] == 'ibkr':
                    driver = broker_ibkr(bot, account)
                elif aconfig['driver'] == 'alpaca':
                    driver = broker_alpaca(bot, account)
                else:
                    raise Exception("Unknown driver: " + aconfig['driver'])

                # set up variables for this account, normalizing market position to be positive or negative based on long or short
                desired_position = market_position_size_orig
                if market_position_orig == "short": desired_position = -market_position_size_orig
                order_symbol = order_symbol_orig
                order_price = driver.get_price(order_symbol)
                order_stock = driver.get_stock(order_symbol)

                print(f"** WORKING ON TRADE for account {account} symbol {order_symbol} to position {desired_position} at price {order_price}")


                # if it's a long-short transition, we need to first go flat
                current_position = driver.get_position_size(account, order_symbol, stock)
                if desired_position < 0 and current_position > 0:
                    print("going flat first")
                    await driver.set_position_size(account, order_symbol, stock, 0, order_price)

                # check for account and security specific percentage of net liquidity in config
                # (if it's not a goflat order)
                if not order_stock.is_futures and desired_position != 0 and f"{order_symbol} pct" in aconfig:
                    percent = float(aconfig[f"{order_symbol} pct"])
                    # first, we find the value of the desired position in dollars, and set up some tiers
                    # to support various levels of take-profits
                    if round(abs(desired_position) * order_price) < 5000:
                        # assume it's a 99% take-profit level
                        percent = percent * 0.01
                    elif round(abs(desired_position) * order_price) < 35000:
                        # assume it's a 80% take-profit level
                        percent = percent * 0.2
                    # otherwise just go with the default full buy

                    # now we find the net liquidity in dollars
                    net_liquidity = driver.get_net_liquidity()
                    # and then we find the desired position in shares
                    new_desired_position = round(net_liquidity * (percent/100) / order_price)
                    if desired_position < 0: new_desired_position = -new_desired_position
                    print(f"using account specific net liquidity {percent}% for {order_symbol}: {desired_position} -> {new_desired_position}")
                    desired_position = new_desired_position

                # check for security conversion (generally futures to ETF); format is "mult x ETF"
                if order_symbol_orig in aconfig:
                    print("switching from ", order_symbol_orig, " to ", aconfig[order_symbol_orig])
                    [switchmult, x, order_symbol] = aconfig[order_symbol_orig].split()
                    switchmult = float(switchmult)
                    desired_position = round(desired_position * switchmult)
                    stock = driver.get_stock(order_symbol) # TODO: have to make this assumption for now
                    order_price = driver.get_price(order_symbol)
                    is_futures = 0

                # check for global multipliers, vs whatever position sizes are coming in from TV
                if not order_stock.is_futures and "multiplier" in config['DEFAULT'] and config['DEFAULT']["multiplier"] != "":
                    print("multiplying position by ",float(config['DEFAULT']["multiplier"]))
                    desired_position = round(desired_position * float(config['DEFAULT']["multiplier"]))

                # check for overall multipliers on the account, vs whatever position sizes are coming in from TV
                if not order_stock.is_futures and aconfig.get("multiplier", "") != "":
                    print("multiplying position by ",float(aconfig["multiplier"]))
                    desired_position = round(desired_position * float(aconfig["multiplier"]))

                # check for futures permissions (default is allow)
                if order_stock.is_futures and aconfig.get('use-futures', 'yes') == 'no':
                    print("this account doesn't allow futures; skipping")
                    continue

                # switch from short a long ETF to long a short ETF, if this account needs it
                if desired_position < 0 and aconfig.get('use-inverse-etf', 'no') == 'yes':
                    long_price = driver.get_price(order_symbol)
                    short_symbol = config['inverse-etfs'][order_symbol]

                    # now continue with the short ETF
                    order_symbol = short_symbol
                    short_price = driver.get_price(order_symbol)
                    order_price = short_price
                    desired_position = abs(round(desired_position * long_price / short_price))
                    print(f"switching to inverse ETF {order_symbol}, to position {desired_position} at price ", order_price)

                    # TODO: handle long-short transitions

                # skip if two signals came out of order and we got a goflat after a non-goflat order
                current_time = datetime.datetime.now()
                last_time = datetime.datetime(1970,1,1)
                if order_symbol+bot in last_time_traded:
                    last_time = last_time_traded[order_symbol+bot+account] 
                delta = current_time - last_time
                last_time_traded[order_symbol+bot+account] = current_time

                if delta.total_seconds() < 120:
                    if desired_position == 0:
                        print("skipping order, seems to be a direction changing exit")
                        return

                current_position = driver.get_position_size(account, order_symbol)

                opposite_sides = (current_position < 0 and desired_position > 0) or (current_position > 0 and desired_position < 0)
                # if we're going flat or opposite sides, if this account uses long and short ETF's, close them both
                if (desired_position == 0 or opposite_sides) and aconfig.get('use-inverse-etf', 'no') == 'yes':

                    print('sending order to reduce long position to flat')
                    await driver.set_position_size(account, order_symbol, 0)

                    print('sending order to reduce short position to flat')
                    short_symbol = config['inverse-etfs'][order_symbol]
                    await driver.set_position_size(account, short_symbol, 0)
            
                # now let's go ahead and place the order to reach the desired position
                if desired_position != current_position:
                    print(f"sending order to reach desired position of {desired_position} shares")
                    await driver.set_position_size(account, order_symbol, desired_position)
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

