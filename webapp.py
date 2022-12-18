import redis, sqlite3, time, os, hashlib, math
from flask import Flask, render_template, request, g, current_app

app = Flask(__name__)

r = redis.Redis(host='localhost', port=6379, db=0)
p = r.pubsub()
p.subscribe('health')
p.get_message(timeout=3)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('trade.db')
        g.db.row_factory = sqlite3.Row

    return g.db

# initial setup of db (if it doesn't exist)
conn = sqlite3.connect('trade.db')
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
        ticker,
        order_action,
        order_contracts,
        order_price,
        order_message text
    )
""")
conn.commit()

# migrations for db, if you have older schemas
cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN order_message text")
    conn.commit()
except: pass

cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN bot text")
    conn.commit()
except: pass

cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN market_position text")
    conn.commit()
except: pass

cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE signals ADD COLUMN market_position_size text")
    conn.commit()
except: pass


@app.context_processor
def add_imports():
    # Note: we only define the top-level module names!
    return dict(hashlib=hashlib, time=time, os=os, math=math)

## ROUTES

# GET /
@app.get('/')
def dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT datetime(timestamp, 'localtime') as timestamp,
        ticker,
        bot,
        order_action,
        order_contracts,
        market_position,
        market_position_size,
        order_price,
        order_message
        FROM signals
        order by timestamp desc
    """)
    signals = cursor.fetchall()
    #hashlib.sha1(row['order_message'])

    return render_template('dashboard.html', signals=signals, sha1=hashlib.sha1)

# POST /resend?hash=xxx
@app.post('/resend')
def resend():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT order_message
        FROM signals
        order by timestamp desc
    """)
    signals = cursor.fetchall()
    for row in signals:
        if request.form.get("hash") == hashlib.sha1(row["order_message"]).hexdigest():
            r.publish('tradingview', row["order_message"])
            return "<html><body>Found it!<br><br><a href=/>Back to Home</a></body></html>"
    return "<html><body>Didn't find it!<br><br><a href=/>Back to Home</a></body></html>"

# POST /webhook
@app.post("/webhook")
def webhook():
    data = request.data

    if data:
        r.publish('tradingview', data)

        #print('got message: ' + request.get_data())

        data_dict = request.json

        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO signals (ticker, bot, order_action, order_contracts, market_position, market_position_size, order_price, order_message) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (data_dict['ticker'], 
                data_dict['strategy']['bot'],
                data_dict['strategy']['order_action'], 
                data_dict['strategy']['order_contracts'],
                data_dict['strategy']['market_position'],
                data_dict['strategy']['market_position_size'],
                data_dict['strategy']['order_price'],
                request.get_data()))
        db.commit()

        return data

    return {"code": "success"}

# GET /health
@app.get("/health")
def health():

    # send a message to the redis channel to test connectivity
    r.publish('tradingview', 'health check')
    # check if we got a response (we want two)
    message = p.get_message(timeout=1)
    if message and message['type'] == 'message':
        message = p.get_message(timeout=1)
        if message and message['type'] == 'message':
            return {"code": "success"}

    if message != None:
        return {"code": "failure", "message-type": message['type'], "message": message['data']}, 500
    else:
        return {"code": "failure", "message-type": "timeout", "message": "no message received"}, 500





