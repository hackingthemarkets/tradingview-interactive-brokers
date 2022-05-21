import redis, sqlite3, time
from flask import Flask, render_template, request, g, current_app

app = Flask(__name__)

r = redis.Redis(host='localhost', port=6379, db=0)

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
except:
    pass

# web url routes below
@app.get('/')
def dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT datetime(timestamp, 'localtime') as timestamp,
        ticker,
        order_action,
        order_contracts,
        order_price,
        order_message
        FROM signals
        order by timestamp desc
    """)
    signals = cursor.fetchall()
    return render_template('dashboard.html', signals=signals)

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
            INSERT INTO signals (ticker, order_action, order_contracts, order_price, order_message) 
            VALUES (?, ?, ?, ?, ?)
        """, (data_dict['ticker'], 
                data_dict['strategy']['order_action'], 
                data_dict['strategy']['order_contracts'],
                data_dict['strategy']['order_price'],
                request.get_data()))

        db.commit()

        return data

    return {
        "code": "success"
    }
