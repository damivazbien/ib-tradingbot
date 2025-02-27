from flask import Flask, jsonify, request
import sys
import os

# Add the directory containing utilities to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

app = Flask(__name__)

# import utilities.buyBTC as buyBTC
import utilities.buyselltaslastock as buyselltaslastock


orders = [
    { 'action': 'BUY', 'totalQuantity': 0.05, 'orderType': 'LMT', 'price': '1.10' }
]

# @app.route("/buyBTC", methods=['GET'])
# def buy_btc():
#     # trigger bu order api
#     buyBTC.BUY_BTC()
#     return "Hello, World!"

@app.route("/buyTSLA", methods=['GET'])
def buytesla():
    buyselltaslastock.BUY_TSLA()
    return "Hello, World!"

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)