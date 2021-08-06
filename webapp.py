import redis, sqlite3, time
from flask import Flask, render_template, request, g, current_app

app = Flask(__name__)

r = redis.Redis(host='localhost', port=6379, db=0)

conn = sqlite3.connect('trade.db')
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
        ticker,
        order_action,
        order_contracts,
        order_price
    )
""")
conn.commit()

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect('trade.db')
        g.db.row_factory = sqlite3.Row

    return g.db

@app.get('/')
def dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM signals
    """)
    signals = cursor.fetchall()

    return render_template('dashboard.html', signals=signals)

@app.post("/webhook")
def webhook():
    data = request.data

    if data:
        r.publish('tradingview', data)

        data_dict = request.json

        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO signals (ticker, order_action, order_contracts, order_price) 
            VALUES (?, ?, ?, ?)
        """, (data_dict['ticker'], 
                data_dict['strategy']['order_action'], 
                data_dict['strategy']['order_contracts'],
                data_dict['strategy']['order_price']))

        db.commit()

        return data

    return {
        "code": "success"
    }