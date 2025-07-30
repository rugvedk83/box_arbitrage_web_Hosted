from telegram import Bot
from flask import Flask, render_template
import requests
import pandas as pd
from datetime import datetime, time as dtime
import time

# Telegram Configuration
import os
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
alerted_boxes = set()


app = Flask(__name__)

def fetch_option_chain():
    url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/"
    }

    session = requests.Session()
    try_count = 3
    delay = 2

    for attempt in range(try_count):
        try:
            session.get("https://www.nseindia.com", headers=headers)
            response = session.get(url, headers=headers)
            data = response.json()

            all_expiries = data['records']['expiryDates']
            current_expiry = all_expiries[0]  # Only nearest expiry
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

                # ✅ Match expiry for both CE and PE
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
            print(f"Attempt {attempt + 1} failed: {e}")
            time.sleep(delay)

    print("❌ All attempts to fetch NSE data failed.")
    return pd.DataFrame(), datetime.now().strftime("%d-%b-%Y %H:%M:%S")


def find_profitable_boxes(df):
    boxes = []
    for i in range(len(df)):
        for j in range(i + 1, len(df)):
            A = df.iloc[i]
            B = df.iloc[j]

            if A['strike'] >= B['strike']:
                continue

            # ✅ Liquidity and bid/ask check
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

            call_spread = A['call_ask'] - B['call_bid']  # Buy A call, sell B call
            put_spread = B['put_ask'] - A['put_bid']     # Buy B put, sell A put
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
from datetime import datetime, time as dtime

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

