from flask import Flask, request, jsonify
import pandas as pd
import datetime
import os

app = Flask(__name__)

LOG_FILE = "signals_log.csv"


@app.route('/')
def home():
    return "<h2>✅ TradingView Webhook Server ishlayapti!</h2>"


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)

        symbol = data.get("symbol", "Unknown")
        action = data.get("action", "None")
        price = data.get("price", "N/A")
        time_utc = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # CSV log
        df = pd.DataFrame([{
            "time_utc": time_utc,
            "symbol": symbol,
            "action": action,
            "price": price
        }])

        if not os.path.exists(LOG_FILE):
            df.to_csv(LOG_FILE, index=False)
        else:
            df.to_csv(LOG_FILE, mode='a', header=False, index=False)

        print(f"✅ Signal: {symbol} - {action} @ {price}")

        return jsonify({"status": "ok", "message": "Signal qabul qilindi"}), 200

    except Exception as e:
        print(f"❌ Xatolik: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
