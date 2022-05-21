# tradingview-interactive-brokers
TradingView Interactive Brokers Integration using Webhooks

## Demo Video:

https://www.youtube.com/watch?v=zsYKfzCNPPU

## Support Part Time Larry's Work

__Visit Interactive Brokers__

https://www.interactivebrokers.com/mkt/?src=ptlg&url=%2Fen%2Findex.php%3Ff%3D1338

__Buy Him a Coffee__

https://buymeacoffee.com/parttimelarry

## Diagram 

![Diagram](diagram.png)

## Prerequisites / Installation

Install redis as per https://redis.io/docs/getting-started/

Install either Trader Workstation or Gateway from Interactive Brokers, at https://www.interactivebrokers.com/en/home.php (Login button)

Make sure you have Python and pip3 installed for your OS

Then run this:

```
pip3 install -r requirements.txt
```

## How to Run the Server

First edit config.txt to contain your shared password and preferred subdomain

Then run an access method to Interactive Brokers. Trader Workstation is a full trading interface with graphs and stuff, and the Gateway is just the API with a small screen to show the logs. Either of these will work. Download either one at https://www.interactivebrokers.com/en/home.php when you click on the Log In button.

Then log into whichever mode of whichever IB app you want (paper vs live, TW vs Gateway), and turn on "ActiveX and Socket Clients", turn off "Read Only API", and accept the warnings.

Then, on three terminals, run the three start scripts. One is for the web API, the second is for the broker command processor, and the third is to start up ngrok.

Then set up a Tradingview alert to hit your webhook, and use the message below! Make sure to change the password to match.


## Sample Webhook Message

```
{
	"time": "{{timenow}}",
	"exchange": "{{exchange}}",
	"ticker": "{{ticker}}",
	"bar": {
		"time": "{{time}}",
		"open": {{open}},
		"high": {{high}},
		"low": {{low}},
		"close": {{close}},
		"volume": {{volume}}
	},
	"strategy": {
		"position:size": {{strategy.position_size}},
		"order_action": "{{strategy.order.action}}",
		"order_contracts": {{strategy.order.contracts}},
		"order_price": {{strategy.order.price}},
        "order_id": "{{strategy.order.id}}",
		"market_position": "{{strategy.market_position}}",
		"market_position_size": {{strategy.market_position_size}},
		"prev_market_position": "{{strategy.prev_market_position}}",
		"prev_market_position_size": {{strategy.prev_market_position_size}}
	},
	"passphrase": "YOUR-SIGNALS-PASSWORD"
}

```

Make sure to send this to https://yoursubdomain.ngrok.com/webhook in the Tradingview alert configuration (note the /webhook part)

## Watchouts

Here are some common issues to watch out for, both in setup and operations

* Your TW or Gateway login will be finicky. Prepare to do a bit of babysitting. This won't be 100% set and forget.
	* If you log in to your IB account somewhere else, TW/GW will be logged out and you have to fix that.
	* TW has a daily restart that you can't avoid.
* The script doesn't convert from "shorting a long ETF" to "going long on a short ETF". So for e.g. if the TV strategy wants to short SOXL, then it will short SOXL rather than buying SOXS. There's a good chance this is actually higher performance anyway.
* It's possible the bot and your IB account will get out of sync, like if you miss a buy signal because of a network flub and the sell comes in later and that turns into a short. Keep it simple, with just a couple algos triggering your bot, and when your algos are all in cash, make sure IB is all cash. Don't let the odd flub eat away at your profits.
* Set your TV alerts to send to your phone and email as well as the bot. The email is helpful because it's the full signal, and you can use a tool like Insomnia to resend the message if it failed to get in.
* If the buy signal doesn't get through, it will currently go the opposite way later on when it tries to sell out. Best option is to force the failed buy signal in using Insomnia for now, or wait til the sell so you can reverse it.




## References, Tools, and Libraries Used:

* ngrok - https://ngrok.com - provides tunnel to localhost
* Flask - https://flask.palletsprojects.com/ - webapp
* Redis - https://pypi.org/project/redis/ - Redis client for Python
* ib_insync - https://ib-insync.readthedocs.io
* Redis pubsub - https://www.twilio.com/blog/sms-microservice-python-twilio-redis-pub-sub, https://redislabs.com/ebook/part-2-core-concepts/chapter-3-commands-in-redis/3-6-publishsubscribe/
* asyncio snippet - https://stackoverflow.com/questions/54153332/schedule-asyncio-task-to-execute-every-x-seconds
* ib_insyc examples - https://github.com/hackingthemarkets/interactive-brokers-demo/blob/main/order.py
