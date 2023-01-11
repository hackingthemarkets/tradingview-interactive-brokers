
from unittest import skip


class broker_root:
    def __init__(self, bot, account):
        pass

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
        pass

    def get_price(self, symbol):
        pass

    def get_net_liquidity(self):
        pass

    def get_position_size(self, symbol):
        pass

    async def set_position_size(self, symbol, amount):
        pass

    def health_check(self):
        pass