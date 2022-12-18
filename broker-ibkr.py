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
        tmc = TextmagicRestClient(tmu, tmk)
        # if e is a string send it, otherwise send the first 300 chars of the traceback
        if isinstance(e, str):
            message = tmc.messages.create(phones=tmp, text="broker-ibkr " + bot + " FAIL " + e)
        else:
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

stock_cache = {}
def get_stock(symbol):
    # keep a cache of stocks to avoid repeated calls to IB
    if symbol in stock_cache:
        stock = stock_cache[symbol]
    else:
        stock = Stock(symbol, 'SMART', 'USD')
        stock_cache[symbol] = stock
    return stock

ticker_cache = {}
def get_price(symbol, stock):
    if stock is None:
        stock = get_stock(symbol)

    # keep a cache of tickers to avoid repeated calls to IB, but only for 5s
    if symbol in ticker_cache and time.time() - ticker_cache[symbol]['time'] < 5:
        ticker = ticker_cache[symbol]['ticker']
    else:
        [ticker] = ib.reqTickers(stock)
        ticker_cache[symbol] = {'ticker': ticker, 'time': time.time()}

    if math.isnan(ticker.last):
        if math.isnan(ticker.close):
            raise Exception("error trying to retrieve stock price for " + symbol)
        else:
            price = ticker.close
    else:
        price = ticker.last
    print(f"  get_price({symbol},{stock}) -> {price}")
    return price

def get_net_liquidity(account):
    # get the current net liquidity
    net_liquidity = 0
    accountSummary = ib.accountSummary(account)
    for value in accountSummary:
        if value.tag == 'NetLiquidation':
            net_liquidity = float(value.value)
            break

    return net_liquidity

def get_position_size(account, symbol, stock=None):
    if stock is None:
        stock = get_stock(symbol)

    # get the current position size
    for p in ib.positions(account):
        if p.contract.symbol == symbol:
            return p.position

    return 0

def set_position_size(account, symbol, stock, amount, round_precision):
    print(f"set_position_size({account},{symbol},{stock},{amount},{round_precision})")
    if stock is None:
        stock = get_stock(symbol)

    # get the current position size
    position_size = get_position_size(account, symbol, stock)

    # figure out how much to buy or sell
    position_variation = round(amount - position_size, 0)

    # if we need to buy or sell, do it with a limit order
    if position_variation != 0:
        price = get_price(symbol, stock)
        high_limit_price = x_round(price * 1.005, round_precision)
        low_limit_price  = x_round(price * 0.995, round_precision)

        if position_variation > 0:
            order = LimitOrder('BUY', position_variation, high_limit_price)
        else:
            order = LimitOrder('SELL', abs(position_variation), low_limit_price)
        order.outsideRth = True
        order.account = account

        print("  placing order: ", order)
        trade = ib.placeOrder(stock, order)
        print("    trade: ", trade)

        # wait for the order to be filled, up to 30s
        maxloops = 30
        print("    waiting for trade1: ", trade)
        while trade.orderStatus.status not in ['Filled','PreSubmitted','Cancelled','Inactive'] and maxloops > 0:
            ib.sleep(1)
            print("    waiting for trade2: ", trade)
            maxloops -= 1

        # throw exception on order failure
        if trade.orderStatus.status not in ['Filled','PreSubmitted']:
            msg = f"ORDER FAILED: set_position_size({account},{symbol},{stock},{amount},{round_precision}) -> {trade.orderStatus}"
            print(msg)
            handle_ex(msg)

        print("order filled")


print("Waiting for webhook messages...")
async def check_messages():
    try:

        #print(f"{time.time()} - checking for tradingview webhook messages")

        message = p.get_message()
        if message is not None and message['type'] == 'message':
            print("*** ",datetime.datetime.now())
            print(message)

            if message['data'] == b'health check':
                print("health check received")
                ib.sleep(1)
                r.publish('health', 'ok')
                return

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

            for account in accounts:
                ## PLACING THE ORDER

                print("")

                # set up variables for this account, normalizing market position to be positive or negative based on long or short
                desired_position = market_position_size_orig
                if market_position_orig == "short": desired_position = -market_position_size_orig
                order_symbol = order_symbol_orig
                stock = stock_orig
                #order_price = order_price_orig
                order_price = get_price(order_symbol, stock)

                print(f"** WORKING ON TRADE for account {account} symbol {order_symbol} to position {desired_position} at price {order_price}")

                # check for account and security specific percentage of net liquidity in config
                # (if it's not a goflat order
                if not is_futures and desired_position != 0 and account in config and f"{order_symbol} pct" in config[account]:
                    percent = float(config[account][f"{order_symbol} pct"])
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
                    net_liquidity = get_net_liquidity(account)
                    # and then we find the desired position in shares
                    new_desired_position = round(net_liquidity * (percent/100) / order_price)
                    if desired_position < 0: new_desired_position = -new_desired_position
                    print(f"using account specific net liquidity {percent}% for {order_symbol}: {desired_position} -> {new_desired_position}")
                    desired_position = new_desired_position

                # check for security conversion (generally futures to ETF); format is "mult x ETF"
                if order_symbol_orig in config[account]:
                    print("switching from ", order_symbol_orig, " to ", config[account][order_symbol_orig])
                    [switchmult, x, order_symbol] = config[account][order_symbol_orig].split()
                    switchmult = float(switchmult)
                    desired_position = round(desired_position * switchmult)
                    stock = Stock(order_symbol, 'SMART', 'USD') # TODO: have to make this assumption for now
                    order_price = get_price(order_symbol, stock)
                    is_futures = 0

                # check for global multipliers, vs whatever position sizes are coming in from TV
                if not is_futures and "multiplier" in config['DEFAULT'] and config['DEFAULT']["multiplier"] != "":
                    print("multiplying position by ",float(config['DEFAULT']["multiplier"]))
                    desired_position = round(desired_position * float(config['DEFAULT']["multiplier"]))

                # check for overall multipliers on the account, vs whatever position sizes are coming in from TV
                if (not is_futures and account != "DEFAULT"
                        and account in config 
                        and "multiplier" in config[account] 
                        and config[account]["multiplier"] != ""
                        ):
                    print("multiplying position by ",float(config[account]["multiplier"]))
                    desired_position = round(desired_position * float(config[account]["multiplier"]))

                # check for futures permissions (default is allow)
                if is_futures and 'use-futures' in config[account] and config[account]['use-futures'] == 'no':
                    print("this account doesn't allow futures; skipping")
                    continue

                # switch from short a long ETF to long a short ETF, if this account needs it
                if (desired_position < 0
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

                    # now continue with the short ETF
                    order_symbol = short_symbol
                    short_price = get_price(order_symbol, stock)
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

                current_position = get_position_size(account, order_symbol, stock)

                # if this account uses long and short ETF's, close them both
                if (desired_position == 0
                    and order_symbol in config['inverse-etfs']
                    and account != 'DEFAULT' 
                    and 'use-inverse-etf' in config[account] 
                    and config[account]['use-inverse-etf'] == 'yes'
                    ):

                    print('sending order to reduce long position to flat')
                    short_symbol = config['inverse-etfs'][order_symbol]
                    if data_dict['exchange'] == 'TSX':
                        short_stock = Stock(short_symbol, 'SMART', 'CAD')
                    else:
                        short_stock = Stock(short_symbol, 'SMART', 'USD')
                    set_position_size(account, order_symbol, stock, 0, round_precision)

                    short_symbol = config['inverse-etfs'][order_symbol]
                    if data_dict['exchange'] == 'TSX':
                        short_stock = Stock(short_symbol, 'SMART', 'CAD')
                    else:
                        short_stock = Stock(short_symbol, 'SMART', 'USD')
                    print('sending order to reduce short position to flat')
                    set_position_size(account, short_symbol, short_stock, 0, round_precision)
                else:
                    # existing position is in the opposite direction of order
                    opposite_sides = (current_position < 0 and desired_position > 0) or (current_position > 0 and desired_position < 0)
                    if opposite_sides:
                        print('sending order to reduce short position to flat')
                        set_position_size(account, order_symbol, stock, 0, round_precision)
                        current_position = 0
                        print('done order')

                    # now let's go ahead and place the order to reach the desired position
                    if desired_position != current_position:
                        print(f"sending order to reach desired position of {desired_position} shares")
                        set_position_size(account, order_symbol, stock, desired_position, round_precision)
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
