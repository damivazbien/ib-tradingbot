import threading
import time
from flask import Flask, request, jsonify
from ib_insync import IB, Stock, MarketOrder
import asyncio

app = Flask(__name__)

# Global dictionary to store the latest account summary values.
account_summary_data = {}
account_lock = threading.Lock()

ib = IB()

def onAccountSummary(item, updated):
    """
    Callback to update global account summary data.
    """
    with account_lock:
        account_summary_data[item.tag] = item.value

def ib_thread_func():
    """
    Dedicated IB thread that creates its own event loop, connects to IB,
    subscribes to account summary updates, and runs the event loop.
    """
    # Create and set a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Connect to TWS
    ib.connect('127.0.0.1', 7497, clientId=1)
    ib.accountSummaryEvent += onAccountSummary
    ib.reqAccountSummary()
    # Run the IB event loop indefinitely
    ib.run()

# Start IB in its own dedicated thread.
ib_thread = threading.Thread(target=ib_thread_func, daemon=True)
ib_thread.start()

@app.route('/balance', methods=['GET'])
def get_balance():
    """
    Endpoint to return the latest cash balance from the global account summary data.
    """
    # Allow some time for account summary data to be received.
    time.sleep(200)
    with account_lock:
        cash_balance = account_summary_data.get('TotalCashValue')
    if cash_balance is None:
        return jsonify({
            'status': 'error',
            'message': 'Account summary data not available yet.'
        }), 408
    return jsonify({
        'status': 'success',
        'balance': cash_balance
    }), 200

if __name__ == '__main__':
    # Disable the reloader to prevent multiple threads.
    app.run(debug=True, use_reloader=False)
