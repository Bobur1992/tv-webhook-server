from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ TradingView Webhook Server ishlayapti!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("📩 Yangi signal qabul qilindi:", data)
    return jsonify({'status': 'success', 'message': 'Signal qabul qilindi'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Render avtomatik portni ishlatadi
    app.run(host='0.0.0.0', port=port)
