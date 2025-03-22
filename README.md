# 📈 IB Trading Bot API (TSLA & BTC)

This is a Python Flask-based trading API that connects to **Interactive Brokers (IB)** via the `ib_insync` library. It allows you to:

- Place **BUY/SELL orders** for TSLA stock
- Buy **TSLA based on cash or portfolio percentage**
- Monitor **account balance and positions**
- Receive **webhook signals** (e.g. from TradingView)
- Place **BTC trades** (when using a real paper/live account)

> ⚠️ **BTC trading is only available in a real Paper or Live IB account** — not in the TWS Demo System.

---

## 🚀 Features

- ✅ Real-time integration with Interactive Brokers via `ib_insync`
- ✅ Buy/Sell Stock (TSLA/APPL) manually or via webhook
- ✅ Calculate how many shares to buy based on cash or % of portfolio
- ✅ Check cash balance, account summary, and positions
- ✅ Webhook endpoint compatible with **TradingView alerts**
- ✅ Basic order logging and error handling

---

## 📦 Requirements

- Python 3.8+
- Interactive Brokers Trader Workstation (TWS) or IB Gateway
- Enabled API access in IB
- Optional: ngrok (to expose your local API for TradingView)

---

## 🧪 Installation

```bash
git clone https://github.com/damivazbien/ib-tradingbot.git
cd ib-tradingbot
python -m venv env
env\Scripts\activate      # On Windows
# source env/bin/activate # On macOS/Linux
pip install -r requirements.txt
```

---

## 🧪 Body Request

{
    "quantity":10,
    "percentage": 100,
    "stock": "AAPL"
}

---

## License

[MIT](https://choosealicense.com/licenses/mit/)