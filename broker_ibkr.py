from ib_insync import *
import time
import nest_asyncio
import configparser
import traceback
import math
from textmagic.rest import TextmagicRestClient

nest_asyncio.apply()

ibconn_cache = {}
stock_cache = {}
ticker_cache = {}

# declare a class to represent the IB driver
class broker_ibkr:
    def __init__(self, bot, account):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.bot = bot
        self.account = account
        self.aconfig = self.config[account]
        self.conn = None

        # pick up a cached IB connection if it exists; cache lifetime is 5 mins
        ibcachekey = f"{self.aconfig['host']}:{self.aconfig['port']}"
        if account in ibconn_cache and ibconn_cache[ibcachekey]['time'] > time.time() - 300:
            self.conn = ibconn_cache[ibcachekey]['ib']

        if self.conn is None:
            self.conn = IB()
            try:
                print(f"IB: Trying to connect...")
                self.conn.connect(self.aconfig['host'], self.aconfig['port'], clientId=1)
            except Exception as e:
                self.handle_ex(e)
                raise

            # cache the connection
            ibconn_cache[ibcachekey] = {'ib': self.conn, 'time': time.time()}
            print("IB: Connected")

    def handle_ex(self, e):
        tmu = self.config['DEFAULT']['textmagic-username']
        tmk = self.config['DEFAULT']['textmagic-key']
        tmp = self.config['DEFAULT']['textmagic-phone']
        if tmu != '':
            tmc = TextmagicRestClient(tmu, tmk)
            # if e is a string send it, otherwise send the first 300 chars of the traceback
            if isinstance(e, str):
                message = tmc.messages.create(phones=tmp, text=f"broker-ibkr " + self.bot + " FAIL " + e)
            else:
                message = tmc.messages.create(phones=tmp, text=f"broker-ibkr " + self.bot + " FAIL " + traceback.format_exc()[0:300])

    # function to round to the nearest decimal. y=10 for dimes, y=4 for quarters, y=100 for pennies
    def x_round(self,x,y):
        return round(x*y)/y

    def get_stock(self, symbol):
        # keep a cache of stocks to avoid repeated calls to IB
        if symbol in stock_cache:
            stock = stock_cache[symbol]
        else:
            # normalization of the symbol, from TV to IB forms
            if symbol == 'BRK.B':
                symbol = 'BRK/B'
            elif symbol == 'BRK.A':
                symbol = 'BRK/A'


            if symbol == 'NQ1!':
                symbol = 'NQ'
                stock = Future(symbol, '20221216', 'GLOBEX')
                stock.is_futures = 1
                stock.round_precision = 4
            elif symbol == 'ES1!':
                symbol = 'ES'
                stock = Future(symbol, '20221216', 'GLOBEX')
                stock.is_futures = 1
                stock.round_precision = 4
            elif symbol == 'RTY1!':
                symbol = 'RTY'
                stock = Future(symbol, '20221216', 'GLOBEX')
                stock.is_futures = 1
                stock.round_precision = 10
            elif symbol == 'CL1!':
                symbol = 'CL'
                stock = Future(symbol, '20221220', 'NYMEX')
                stock.is_futures = 1
                stock.round_precision = 10
            elif symbol == 'NG1!':
                symbol = 'NG'
                stock = Future(symbol, '20221220', 'NYMEX')
                stock.is_futures = 1
                stock.round_precision = 10
            elif symbol == 'HG1!':
                symbol = 'HG'
                stock = Future(symbol, '20220928', 'NYMEX')
                stock.is_futures = 1
                stock.round_precision = 10
            elif symbol == '6J1!':
                symbol = 'J7'
                stock = Future(symbol, '20220919', 'GLOBEX')
                stock.is_futures = 1
                stock.round_precision = 10
            elif symbol == 'HEN2022':
                symbol = 'HE'
                stock = Future(symbol, '20220715', 'NYMEX')
                stock.is_futures = 1
                stock.round_precision = 10
            elif symbol in ['HXU', 'HXD', 'HQU', 'HQD', 'HEU', 'HED', 'HSU', 'HSD', 'HGU', 'HGD', 'HBU', 'HBD', 'HNU', 'HND', 'HOU', 'HOD', 'HCU', 'HCD']:
                stock = Stock(symbol, 'SMART', 'CAD')
                stock.is_futures = 0
                stock.round_precision = 100
            else:
                stock = Stock(symbol, 'SMART', 'USD')
                stock.is_futures = 0
                stock.round_precision = 100

            stock_cache[symbol] = stock
        return stock

    def get_price(self, symbol):
        stock = self.get_stock(symbol)

        # keep a cache of tickers to avoid repeated calls to IB, but only for 5s
        if symbol in ticker_cache and time.time() - ticker_cache[symbol]['time'] < 5:
            ticker = ticker_cache[symbol]['ticker']
        else:
            [ticker] = self.conn.reqTickers(stock)
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

    def get_net_liquidity(self):
        # get the current net liquidity
        net_liquidity = 0
        accountSummary = self.conn.accountSummary(self.account)
        for value in accountSummary:
            if value.tag == 'NetLiquidation':
                net_liquidity = float(value.value)
                break

        return net_liquidity

    def get_position_size(self, symbol):
        if stock is None:
            stock = self.get_stock(symbol)

        # get the current position size
        for p in self.conn.positions(self.account):
            if p.contract.symbol == symbol:
                return p.position

        return 0

    async def set_position_size(self, symbol, amount):
        print(f"set_position_size({self.account},{symbol},{amount})")
        stock = self.get_stock(symbol)

        # get the current position size
        position_size = self.get_position_size(self.account, symbol, stock)

        # figure out how much to buy or sell
        position_variation = round(amount - position_size, 0)

        # if we need to buy or sell, do it with a limit order
        if position_variation != 0:
            price = self.get_price(symbol, stock)
            high_limit_price = self.x_round(price * 1.005, stock.round_precision)
            low_limit_price  = self.x_round(price * 0.995, stock.round_precision)

            if position_variation > 0:
                order = LimitOrder('BUY', position_variation, high_limit_price)
            else:
                order = LimitOrder('SELL', abs(position_variation), low_limit_price)
            order.outsideRth = True
            order.account = self.account

            print("  placing order: ", order)
            trade = self.conn.placeOrder(stock, order)
            print("    trade: ", trade)

            # wait for the order to be filled, up to 30s
            maxloops = 30
            print("    waiting for trade1: ", trade)
            while trade.orderStatus.status not in ['Filled','PreSubmitted','Cancelled','Inactive'] and maxloops > 0:
                self.conn.sleep(1)
                print("    waiting for trade2: ", trade)
                maxloops -= 1

            # throw exception on order failure
            if trade.orderStatus.status not in ['Filled','PreSubmitted']:
                msg = f"ORDER FAILED: set_position_size({self.account},{symbol},{stock},{amount},{stock.round_precision}) -> {trade.orderStatus}"
                print(msg)
                self.handle_ex(msg)

            print("order filled")

    def health_check(self):
        self.get_net_liquidity()
