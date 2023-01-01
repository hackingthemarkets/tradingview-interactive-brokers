import asyncio
import sys
import time
import configparser
import traceback
import math
from textmagic.rest import TextmagicRestClient
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest, GetOrdersRequest, LimitOrderRequest
from alpaca.trading.enums import AssetClass, OrderSide, TimeInForce, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

alpacaconn_cache = {}
stock_cache = {}
ticker_cache = {}

class StockStub:
    def __init__(self, symbol):
        self.symbol = symbol
        self.is_futures = 0

# declare a class to represent the IB driver
class broker_alpaca:
    def __init__(self, bot, account):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.bot = bot
        self.account = account
        self.aconfig = self.config[account]
        self.conn = None
        self.dataconn = None

        # pick up a cached IB connection if it exists; cache lifetime is 5 mins
        alcachekey = f"{self.aconfig['key']}"
        if alcachekey in alpacaconn_cache and alpacaconn_cache[alcachekey]['time'] > time.time() - 300:
            self.conn = alpacaconn_cache[alcachekey]['conn']
            self.dataconn = alpacaconn_cache[alcachekey]['dataconn']

        if self.conn is None:
            try:
                print(f"Alpaca: Trying to connect...")
                paper = True if self.aconfig['paper'] == 'yes' else False
                self.conn = TradingClient(api_key=self.aconfig['key'], secret_key=self.aconfig['secret'], paper=paper)
                self.dataconn = StockHistoricalDataClient(api_key=self.aconfig['key'], secret_key=self.aconfig['secret'])

            except Exception as e:
                self.handle_ex(e)
                raise

            # cache the connection
            alpacaconn_cache[alcachekey] = {'conn': self.conn, 'dataconn': self.dataconn, 'time': time.time()}
            print("Alpaca: Connected")

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

    def get_stock(self, symbol):
        if symbol in stock_cache:
            stock = stock_cache[symbol]
        else:
            # normalization of the symbol, from TV to Alpaca form
            stock = StockStub(symbol)
            if symbol == 'NQ1!':
                stock.is_futures = 1
            elif symbol == 'ES1!':
                stock.is_futures = 1
            elif symbol == 'RTY1!':
                stock.is_futures = 1
            elif symbol == 'CL1!':
                stock.is_futures = 1
            elif symbol == 'NG1!':
                stock.is_futures = 1
            elif symbol == 'HG1!':
                stock.is_futures = 1
            elif symbol == '6J1!':
                stock.is_futures = 1
            elif symbol == 'HEN2022':
                stock.is_futures = 1
            else:
                stock.is_futures = 0

            stock_cache[symbol] = stock
        return stock

    def get_price(self, symbol):
        stock = self.get_stock(symbol)

        # keep a cache of tickers to avoid repeated calls to IB, but only for 5s
        if symbol in ticker_cache and time.time() - ticker_cache[symbol]['time'] < 5:
            ticker = ticker_cache[symbol]['ticker']
        else:
            multisymbol_request_params = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            latest_multisymbol_quotes = self.dataconn.get_stock_latest_quote(multisymbol_request_params)
            ticker = latest_multisymbol_quotes[symbol]
            ticker_cache[symbol] = {'ticker': ticker, 'time': time.time()}

        price = ticker.ask_price
        print(f"  get_price({symbol}) -> {price}")
        return price

    def get_net_liquidity(self):
        # get the current Alpaca net liquidity in USD
        net_liquidity = self.conn.get_account().last_equity
        print(f"  get_net_liquidity() -> {net_liquidity}")
        return net_liquidity

    def get_position_size(self, symbol):
        if stock is None:
            stock = self.get_stock(symbol)

        # get the current Alpaca position size for this stock and this account
        position_size = 0
        for position in self.conn.list_positions():
            if position.symbol == symbol:
                position_size = position.qty
                break
        return position_size


    async def set_position_size(self, symbol, amount):
        print(f"set_position_size({self.account},{symbol},{amount})")
        stock = self.get_stock(symbol)

        # get the current position size
        position_size = self.get_position_size(symbol, stock)

        # figure out how much to buy or sell
        position_variation = round(amount - position_size, 0)

        # if we need to buy or sell, do it with a limit order
        if position_variation != 0:
            price = self.get_price(symbol, stock)
            high_limit_price = round(price * 1.005, 2)
            low_limit_price  = round(price * 0.995, 2)

            if position_variation > 0:
                limit_order_data = LimitOrderRequest(
                    symbol=symbol,
                    limit_price=high_limit_price,
                    notional=position_variation,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.GTC,
                    extended_hours = True
                   )
            else:
                limit_order_data = LimitOrderRequest(
                    symbol=symbol,
                    limit_price=low_limit_price,
                    notional=position_variation,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC,
                    extended_hours = True
                   )

            print("  placing order: ", limit_order_data)
            trade = self.conn.submit_order(order_data=limit_order_data)
            print("    trade: ", trade)

            # wait for the order to be filled, up to 30s
            maxloops = 30
            print("    waiting for trade1: ", trade)
            trade = self.conn.get_order(trade.id)
            while trade.status in ['new','partially_filled'] and maxloops > 0:
                await asyncio.sleep(1)
                print("    waiting for trade2: ", trade)
                maxloops -= 1
                trade = self.conn.get_order(trade.id)

            # throw exception on order failure
            if trade.status not in ['filled']:
                msg = f"ORDER FAILED: set_position_size({self.account},{symbol},{stock},{amount}) -> {trade.orderStatus}"
                print(msg)
                self.handle_ex(msg)

            print("order filled")


    def health_check(self):
        self.get_net_liquidity()
        self.get_price('SPY')
