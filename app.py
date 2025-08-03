from telegram import Bot
from flask import Flask, render_template
import requests
import pandas as pd
from datetime import datetime, time as dtime
import time
import os

# ====== Telegram Configuration ======
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Debug prints to verify if env variables are loaded
print(f"🔍 TELEGRAM_TOKEN: {TELEGRAM_TOKEN}")
print(f"🔍 CHAT_ID: {CHAT_ID}")

# Initialize Telegram Bot safely
if TELEGRAM_TOKEN and CHAT_ID:
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
    except Exception as e:
        print(f"⚠️ Telegram Bot initialization failed: {e}")
        bot = None
else:
    print("⚠️ TELEGRAM_TOKEN or CHAT_ID missing. Telegram alerts disabled.")
    bot = None

alerted_boxes = set()

app = Flask(__name__)

from playwright.sync_api import sync_playwright

def fetch_option_chain():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0")
            page = context.new_page()

print("🌐 Visiting NSE option chain page...")
page.goto("https://www.nseindia.com/option-chain", timeout=60000)
page.wait_for_timeout(5000)  # let JS cookies load

print("📦 Fetching raw option chain JSON data...")
response = context.request.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY")
print(f"HTTP Response Status: {response.status}")

if response.status != 200:
    print(f"❌ Failed to fetch data from NSE. Status code: {response.status}")
    return pd.DataFrame(), datetime.now().strftime("%d-%b-%Y %H:%M:%S")

data = response.json()

browser.close()


        all_expiries = data['records']['expiryDates']
        current_expiry = all_expiries[0]
        underlying = data['records'].get('underlyingValue', 0)
        records = data['records']['data']

        strike_min = int((underlying - 500) // 50 * 50)
        strike_max = int((underlying + 500) // 50 * 50)

        options = []

        for item in records:
            strike = item['strikePrice']
            if strike < strike_min or strike > strike_max:
                continue

            ce = item.get('CE')
            pe = item.get('PE')

            if not ce or not pe:
                continue

            if ce.get('expiryDate') != current_expiry or pe.get('expiryDate') != current_expiry:
                continue

            if ce.get("bidprice", 0) == 0 and ce.get("askPrice", 0) == 0:
                continue
            if pe.get("bidprice", 0) == 0 and pe.get("askPrice", 0) == 0:
                continue

            options.append({
                'strike': strike,
                'call_ltp': ce.get('lastPrice', 0),
                'put_ltp': pe.get('lastPrice', 0),
                'call_bid': ce.get('bidprice', 0),
                'call_ask': ce.get('askPrice', 0),
                'put_bid': pe.get('bidprice', 0),
                'put_ask': pe.get('askPrice', 0),
                'call_oi': ce.get('openInterest', 0),
                'put_oi': pe.get('openInterest', 0),
                'call_vol': ce.get('totalTradedVolume', 0),
                'put_vol': pe.get('totalTradedVolume', 0)
            })

        timestamp = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        return pd.DataFrame(options), timestamp

    except Exception as e:
        print(f"❌ Playwright fetch failed: {e}")
        return pd.DataFrame(), datetime.now().strftime("%d-%b-%Y %H:%M:%S")

def find_profitable_boxes(df):
    boxes = []
    for i in range(len(df)):
        for j in range(i + 1, len(df)):
            A = df.iloc[i]
            B = df.iloc[j]

            if A['strike'] >= B['strike']:
                continue

            legs_ok = (
                A['call_bid'] > 0 and A['call_ask'] > 0 and
                B['call_bid'] > 0 and B['call_ask'] > 0 and
                A['put_bid'] > 0 and A['put_ask'] > 0 and
                B['put_bid'] > 0 and B['put_ask'] > 0 and
                A['call_oi'] >= 1000 and B['call_oi'] >= 1000 and
                A['put_oi'] >= 1000 and B['put_oi'] >= 1000
            )
            if not legs_ok:
                continue

            call_spread = A['call_ask'] - B['call_bid']
            put_spread = B['put_ask'] - A['put_bid']
            box_cost = call_spread + put_spread
            box_value = B['strike'] - A['strike']
            profit = round(box_value - box_cost, 2)

            box_key = (A['strike'], B['strike'])

            if profit > 15 and box_key not in alerted_boxes:
                alerted_boxes.add(box_key)
                alert_msg = f"""📦 Nifty Box Arbitrage Alert!

Strike A: {A['strike']}
Strike B: {B['strike']}
Box Value: ₹{box_value}
Box Cost: ₹{round(box_cost, 2)}
📈 Profit: ₹{profit} per lot
"""
                if bot:
                    try:
                        bot.send_message(chat_id=CHAT_ID, text=alert_msg)
                    except Exception as e:
                        print(f"Telegram error: {e}")

            boxes.append({
                'Strike A': A['strike'],
                'Strike B': B['strike'],
                'Call Buy @A (Ask)': A.get('call_ask', 0),
                'Call Sell @B (Bid)': B.get('call_bid', 0),
                'Put Buy @B (Ask)': B.get('put_ask', 0),
                'Put Sell @A (Bid)': A.get('put_bid', 0),
                'Box Value': box_value,
                'Box Cost': round(box_cost, 2),
                'Profit': profit
            })

    return sorted(boxes, key=lambda x: x['Profit'], reverse=True)[:10]

@app.route('/')
def home():
    try:
        now = datetime.now().time()
        market_open = dtime(9, 15)
        market_close = dtime(15, 30)

        if market_open <= now <= market_close:
            df, timestamp = fetch_option_chain()
            boxes = find_profitable_boxes(df)
        else:
            boxes = []
            timestamp = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
            print("⏰ Outside market hours. Skipping data fetch.")

    except Exception as e:
        print(f"App error: {e}")
        boxes = []
        timestamp = datetime.now().strftime("%d-%b-%Y %H:%M:%S")

    return render_template("index.html", boxes=boxes, timestamp=timestamp)

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=10000)
