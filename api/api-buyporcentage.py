import threading
import time
from flask import Flask, request, jsonify
from ib_insync import IB, Stock, MarketOrder
import asyncio
import logging
import nest_asyncio

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global dictionary to store the latest account summary values
account_summary_data = {}
account_lock = threading.Lock()
ib_ready = threading.Event()  # Event to signal when IB is connected and ready

# Create IB instance
ib = IB()

def onAccountSummary(accountValue):
    """
    Callback function for account summary updates.
    """
    try:
        with account_lock:
            account_summary_data[accountValue.tag] = accountValue.value
            if accountValue.tag == 'TotalCashValue':
                if "initial_session_balance" not in account_summary_data:
                    account_summary_data["initial_session_balance"] = accountValue.value
        logger.info(f"Updated account summary: {accountValue.tag} = {accountValue.value}")
    except Exception as e:
        logger.error(f"Error in onAccountSummary: {str(e)}", exc_info=True)

async def periodic_account_summary():
    """
    Periodically fetch account summary data from IB.
    """
    while True:
        if ib.isConnected():
            ib.reqAccountSummary()
        await asyncio.sleep(10)  # Request every 10 seconds

async def async_ib_connect():
    logger.info("Connecting to Interactive Brokers...")
    await ib.connectAsync('127.0.0.1', 7497, clientId=1)
    logger.info("Connected to Interactive Brokers")

    # Subscribe to account summary updates
    ib.accountSummaryEvent += onAccountSummary

    # Start periodic updates
    asyncio.create_task(periodic_account_summary())

    # Set IB ready event
    ib_ready.set()

def ib_thread_func():
    """
    Connect to IB and run its event loop in a dedicated thread.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(async_ib_connect())
        ib.run()
    except Exception as e:
        logger.error(f"Error in IB thread: {str(e)}", exc_info=True)

# Start the IB thread as a daemon
ib_thread = threading.Thread(target=ib_thread_func, daemon=True)
ib_thread.start()

def wait_for_ib_ready():
    """Wait for IB to be ready or return False"""
    return ib_ready.wait(timeout=15)  # Wait up to 15 seconds

@app.route('/balance', methods=['GET'])
def get_balance():
    """
    Returns the latest cached cash balance from the account.
    """
    if not wait_for_ib_ready():
        return jsonify({
            'status': 'error',
            'message': 'Interactive Brokers connection not ready'
        }), 503

    with account_lock:
        cash_balance = account_summary_data.get('TotalCashValue')
        initial_balance = account_summary_data.get('initial_session_balance')

    if cash_balance is None:
        return jsonify({
            'status': 'error',
            'message': 'Account summary data not available yet. Please try again later.'
        }), 408

    return jsonify({
        'status': 'success',
        'current_balance': cash_balance,
        'initial_session_balance': initial_balance
    }), 200

@app.route('/buyPercentage', methods=['POST'])
def buy_percentage():
    """
    Buy a percentage of the total portfolio value in TSLA shares.
    """
    if not wait_for_ib_ready():
        return jsonify({
            'status': 'error',
            'message': 'Interactive Brokers connection not ready'
        }), 503

    try:
        data = request.get_json()
        percentage = data.get('percentage')

        if percentage is None:
            return jsonify({'status': 'error', 'message': 'Percentage parameter is required.'}), 400
        try:
            percentage = float(percentage)
        except ValueError:
            return jsonify({'status': 'error', 'message': 'Percentage must be a number.'}), 400
        if percentage <= 0 or percentage > 100:
            return jsonify({'status': 'error', 'message': 'Percentage must be between 0 and 100.'}), 400

        # Use cached account data instead of requesting fresh data
        with account_lock:
            portfolio_value = account_summary_data.get('NetLiquidation')

        if portfolio_value is None:
            return jsonify({'status': 'error', 'message': 'Portfolio value not available yet. Try again later.'}), 408

        portfolio_value = float(portfolio_value)

        # Calculate the amount to invest
        amount_to_invest = portfolio_value * (percentage / 100.0)

        # Define TSLA contract
        contract = Stock('TSLA', 'SMART', 'USD')
        ib.qualifyContracts(contract)

        # Request market data snapshot (avoiding live stream issues)
        logger.info("Requesting TSLA market data snapshot...")
        ib.reqMarketDataType(3)  # Use delayed data if real-time is unavailable

        ticker = ib.reqMktData(contract, snapshot=True, regulatorySnapshot=False)

        # Wait for IB to return market data (max 5 seconds)
        ib.waitOnUpdate(timeout=5)

        # Ensure we received market data
        current_price = ticker.last if ticker.last is not None else ticker.close
        logger.info(f"Market data received: last={ticker.last}, close={ticker.close}")

        if current_price is None:
            return jsonify({'status': 'error', 'message': 'Market data request failed. Check IB market data subscription.'}), 500

        # Calculate the number of shares to buy
        quantity = int(amount_to_invest / current_price)
        if quantity < 1:
            return jsonify({'status': 'error', 'message': 'Insufficient funds to buy at least 1 share.'}), 400

        # Ensure IB connection is active before placing order
        if not ib.isConnected():
            logger.error("IB connection lost before placing order!")
            return jsonify({'status': 'error', 'message': 'Interactive Brokers connection lost.'}), 503

        # Place a market order for TSLA
        logger.info(f"Placing market order: BUY {quantity} shares of TSLA...")
        order = MarketOrder('BUY', quantity)
        trade = ib.placeOrder(contract, order)

        # Wait for order confirmation
        ib.sleep(1)
        logger.info(f"Trade details: {trade}")

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'quantity': quantity,
            'invested_amount': amount_to_invest,
            'current_price': current_price,
            'message': f'Placed a BUY order for {quantity} TSLA share(s), representing {percentage}% of portfolio value.'
        }), 200

    except Exception as e:
        logger.error(f"Error in buyPercentage endpoint: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    time.sleep(5)
    app.run(debug=True, use_reloader=False)
