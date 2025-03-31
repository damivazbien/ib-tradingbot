import threading
import time
from flask import Flask, request, jsonify
from ib_insync import IB, Stock, MarketOrder, Crypto
import asyncio
import logging
import nest_asyncio
from waitress import serve

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

# List of allowed IP addresses
ALLOWED_IPS = {'127.0.0.1', '1.2.3.4'}  # Add your trusted IPs here

# Create IB instance
ib = IB()

def onAccountSummary(accountValue):
    """
    Callback function for account summary updates.
    The ib_insync library has changed - it only passes one argument (accountValue)
    to the callback function.
    """
    try:
        with account_lock:
            account_summary_data[accountValue.tag] = accountValue.value
            if accountValue.tag == 'TotalCashValue':
                # Set initial session balance only once
                if "initial_session_balance" not in account_summary_data:
                    account_summary_data["initial_session_balance"] = accountValue.value
        logger.info(f"Updated account summary: {accountValue.tag} = {accountValue.value}")
    except Exception as e:
        logger.error(f"Error in onAccountSummary: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

async def periodic_account_summary():
    """
    Periodically fetch account summary data from IB.
    This runs in the background and updates `account_summary_data`.
    """
    while True:
        if ib.isConnected():
            ib.reqAccountSummary()
        await asyncio.sleep(10000000)  # Request every 10 seconds

def restrict_ip(f):
    def wrapped(*args, **kwargs):
        requester_ip = request.remote_addr
        if requester_ip not in ALLOWED_IPS:
            logger.warning(f"Unauthorized IP attempted access: {requester_ip}")
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    wrapped.__name__ = f.__name__  # Needed to avoid Flask routing issues
    return wrapped

async def async_ib_connect():
    logger.info("Connecting to Interactive Brokers...")
    await ib.connectAsync('127.0.0.1', 7497, clientId=1)
    logger.info("Connected to Interactive Brokers")
    
    # Subscribe to account summary updates
    ib.accountSummaryEvent += onAccountSummary
    
    # Request account summary data
    #ib.reqAccountSummary()
    # Start periodic updates
    asyncio.create_task(periodic_account_summary())
    
    # Set the event to signal that IB is connected and ready
    ib_ready.set()

def ib_thread_func():
    """
    Connect to IB and run its event loop in a dedicated thread.
    Creates a new event loop for the thread and runs the connection.
    """
    try:
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Connect to IB using the async method properly
        loop.run_until_complete(async_ib_connect())
        
        # Keep the IB event loop running indefinitely
        ib.run()
    except Exception as e:
        logger.error(f"Error in IB thread: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

# Start the IB thread as a daemon so it stops with the main program
ib_thread = threading.Thread(target=ib_thread_func, daemon=True)
ib_thread.start()

def wait_for_ib_ready():
    """Wait for IB to be ready or return False"""
    return ib_ready.wait(timeout=15)  # Wait up to 15 seconds

@app.route('/buyStock', methods=['POST'])
@restrict_ip
def buy():
    if not wait_for_ib_ready():
        return jsonify({
            'status': 'error',
            'message': 'Interactive Brokers connection not ready'
        }), 503
    
    try:
        data = request.get_json()
        percentage = data.get('percentage', 5)

        if 'stock' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing required parameter: stock'
            }), 400
        
        stock = data.get('stock')
        
        # Read the latest cash balance from our shared variable.
        with account_lock:
            cash_balance = account_summary_data.get('TotalCashValue')
        if cash_balance is None:
            return jsonify({
                'status': 'error',
                'message': 'Account summary data not available.'
            }), 408
        
        cash_balance = float(cash_balance)

        print(cash_balance)

        # Calculate the amount to invest.
        amount_to_invest = cash_balance * (percentage / 100.0)

        current_price = 281#ticker.last if ticker.last is not None else ticker.close
        if current_price is None:
            return jsonify({
                'status': 'error',
                'message': 'Unable to retrieve current TSLA price.'
            }), 500
        
        # Calculate the number of shares to buy (rounding down).
        quantity = int(amount_to_invest / current_price)
        print("quantity",quantity)
        if quantity < 1:
            return jsonify({
                'status': 'error',
                'message': 'Insufficient funds to buy at least 1 share.'
            }), 400

        # Define the Tesla stock contract
        contract = Stock(stock, 'SMART', 'USD')

        # Create a market order to buy the specified quantity
        order = MarketOrder('BUY', quantity)

        # Place the order
        trade = ib.placeOrder(contract, order)

        # Wait briefly for order confirmation
        time.sleep(1)

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'message': f'Placed a BUY order for {quantity} TSLA share(s).'
        }), 200

    except Exception as e:
        logger.error(f"Error in buy endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/buyBTC', methods=['POST'])
def buy_btc():
    if not wait_for_ib_ready():
        return jsonify({'status': 'error', 'message': 'IB not ready'}), 503

    try:
        data = request.get_json()
        percentage = float(data.get('percentage', 0))

        if percentage <= 0 or percentage > 100:
            return jsonify({'status': 'error', 'message': 'Invalid percentage'}), 400

        with account_lock:
            portfolio_value = float(account_summary_data.get('NetLiquidation', 0))

        if portfolio_value == 0:
            return jsonify({'status': 'error', 'message': 'Portfolio value not available'}), 408

        amount_to_invest = portfolio_value * (percentage / 100)

        # Define BTC/USD crypto contract
        contract = Crypto('BTC', 'PAXOS', 'USD')
        ib.qualifyContracts(contract)

        # Use delayed market data
        ib.reqMarketDataType(3)
        ticker = ib.reqMktData(contract, snapshot=True)
        ib.waitOnUpdate(timeout=5)

        current_price = ticker.last or ticker.close
        if current_price is None:
            return jsonify({'status': 'error', 'message': 'Could not get BTC price'}), 500

        quantity = round(amount_to_invest / current_price, 6)

        order = MarketOrder('BUY', quantity)
        trade = ib.placeOrder(contract, order)
        ib.sleep(1)

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'quantity': quantity,
            'invested_amount': amount_to_invest,
            'current_price': current_price,
            'message': f'Placed BUY order for {quantity} BTC'
        }), 200

    except Exception as e:
        logger.error(f"Error buying BTC: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/sellStock', methods=['POST'])
@restrict_ip
def sell():
    if not wait_for_ib_ready():
        return jsonify({
            'status': 'error',
            'message': 'Interactive Brokers connection not ready'
        }), 503
        
    try:
        data = request.get_json()
        quantity = data.get('quantity', 1)  # default to 1 share if not specified
        
        if 'stock' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing required parameter: stock'
            }), 400
        
        stock = data.get('stock')

        # Define the Tesla stock contract
        contract = Stock(stock, 'SMART', 'USD')

        # Create a market order to sell the specified quantity
        order = MarketOrder('SELL', quantity)

        # Place the order
        trade = ib.placeOrder(contract, order)

        # Wait briefly for order confirmation
        time.sleep(1)

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'message': f'Placed a SELL order for {quantity} TSLA share(s).'
        }), 200

    except Exception as e:
        logger.error(f"Error in sell endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/accountinfo', methods=['GET'])
def get_account_info():
    """
    Returns the latest cached account summary.
    """
    if not wait_for_ib_ready():
        return jsonify({
            'status': 'error',
            'message': 'Interactive Brokers connection not ready'
        }), 503

    # Use cached data instead of requesting a new summary
    with account_lock:
        result = account_summary_data.copy()  # Safe copy of latest data

    if not result:
        return jsonify({
            'status': 'error',
            'message': 'Account summary data not available yet.'
        }), 408

    return jsonify({
        'status': 'success',
        'account_info': result
    }), 200


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

    # Just return the last known balance (already updated in the background)
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
            return jsonify({
                'status': 'error',
                'message': 'Percentage parameter is required.'
            }), 400

        try:
            percentage = float(percentage)
        except ValueError:
            return jsonify({
                'status': 'error',
                'message': 'Percentage must be a number.'
            }), 400

        if percentage <= 0 or percentage > 100:
            return jsonify({
                'status': 'error',
                'message': 'Percentage must be between 0 and 100.'
            }), 400

        # Use cached account data instead of requesting fresh data
        with account_lock:
            portfolio_value = account_summary_data.get('NetLiquidation')  # Total portfolio value

        if portfolio_value is None:
            return jsonify({
                'status': 'error',
                'message': 'Portfolio value not available yet. Try again later.'
            }), 408

        portfolio_value = float(portfolio_value)

        # Calculate the amount to invest (percentage of total portfolio)
        amount_to_invest = portfolio_value * (percentage / 100.0)

        # Define TSLA contract
        contract = Stock('TSLA', 'SMART', 'USD')
        ib.qualifyContracts(contract)

        # Request market data snapshot (avoiding live stream issues)
        logger.info("Requesting TSLA market data snapshot...")
        ticker = ib.reqMktData(contract, snapshot=True, regulatorySnapshot=False)
        ib.sleep(2)  # Allow IB time to return the data

        # Get price from market data
        current_price = ticker.last if ticker.last else ticker.close
        logger.info(f"Market data received: last={ticker.last}, close={ticker.close}")

        if current_price is None:
            return jsonify({
                'status': 'error',
                'message': 'Unable to retrieve current TSLA price. Check IB market data subscription.'
            }), 500

        # Calculate the number of shares to buy (rounding down)
        quantity = int(amount_to_invest / current_price)
        if quantity < 1:
            return jsonify({
                'status': 'error',
                'message': 'Insufficient funds to buy at least 1 share.'
            }), 400

        # Ensure IB connection is active before placing order
        if not ib.isConnected():
            logger.error("IB connection lost before placing order!")
            return jsonify({
                'status': 'error',
                'message': 'Interactive Brokers connection lost.'
            }), 503

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
        logger.error(f"Error in buyPercentage endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/positions', methods=['GET'])
def get_positions():
    """
    Endpoint to get current positions
    """
    if not wait_for_ib_ready():
        return jsonify({
            'status': 'error',
            'message': 'Interactive Brokers connection not ready'
        }), 503
    
    try:
        positions = ib.positions()
        
        result = []
        for position in positions:
            result.append({
                'symbol': position.contract.symbol,
                'exchange': position.contract.exchange,
                'currency': position.contract.currency,
                'position': position.position,
                'avgCost': position.avgCost
            })
            
        return jsonify({
            'status': 'success',
            'positions': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error in positions endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    # Give IB connection time to establish before starting Flask
    time.sleep(5)
    #app.run(debug=True, use_reloader=False)
    serve(app, host='0.0.0.0', port=5000)