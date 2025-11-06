from flask import Flask, request, jsonify

app = Flask(__name__)
@app.route('/')
def home():
    return '✅ TradingView Webhook Server ishlayapti!'

@app.route('/')
def home():
    return "✅ TradingView Webhook Server ishlayapti!"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("📩 Yangi signal qabul qilindi:", data)
    # Bu yerda siz MT5 yoki Google Sheetga yozish kodini qo‘shasiz
    return jsonify({'status': 'success', 'message': 'Signal qabul qilindi!'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
