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

Make sure you have Python and pip3 installed for your OS

Then run this:

```
pip3 install -r requirements.txt
```

## How to Run the Server

First edit config.txt to contain your shared password and preferred subdomain

Then install and run an access method to Interactive Brokers. Trader Workstation is a full trading interface with graphs and stuff, and the Gateway is just the API with a small screen to show the logs. Either of these will work. Download either one at https://www.interactivebrokers.com/en/home.php when you click on the Log In button.

Then log into whichever mode of whichever IB app you want (paper vs live, TW vs Gateway), and turn on API access, turn off Read Only, and accept the warnings.

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
		"order_contracts", {{strategy.order.contracts}},
		"order_price", {strategy.order.price}},
		"order_id": "{{strategy.order_id}}",
		"market_position": "{{strategy.market_position}}",
		"market_position_size": {{strategy.market_position_size}},
		"prev_market_position": "{{strategy.prev_market_position}}",
		"prev_market_position_size", {{strategy.prev_market_position_size}}
	},
	"passphrase": "YOUR-SIGNALS-PASSWORD"
}

```

## References, Tools, and Libraries Used:

* ngrok - https://ngrok.com - provides tunnel to localhost
* Flask - https://flask.palletsprojects.com/ - webapp
* Redis - https://pypi.org/project/redis/ - Redis client for Python
* ib_insync - https://ib-insync.readthedocs.io
* Redis pubsub - https://www.twilio.com/blog/sms-microservice-python-twilio-redis-pub-sub, https://redislabs.com/ebook/part-2-core-concepts/chapter-3-commands-in-redis/3-6-publishsubscribe/
* asyncio snippet - https://stackoverflow.com/questions/54153332/schedule-asyncio-task-to-execute-every-x-seconds
* ib_insyc examples - https://github.com/hackingthemarkets/interactive-brokers-demo/blob/main/order.py
