import threading
import time
from flask import Flask, request, jsonify, abort
from functools import wraps
from ib_insync import IB, symbol, MarketOrder, Crypto, Forex, Future, Option, Contract
import asyncio
import logging
import nest_asyncio
from waitress import serve
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()
API_KEY = os.getenv('API_KEY')
IB_HOST = os.getenv('IB_HOST', '127.0.0.1')  # default if missing
IB_PORT = int(os.getenv('IB_PORT', 7497))
ALLOWED_IPS = set(os.getenv('ALLOWED_IPS', '127.0.0.1').split(','))


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

def build_contract(symbol: str):
    symbol = symbol.upper()

    if symbol == 'BTC':
        return Crypto('BTC', 'PAXOS', 'USD')
    elif symbol == 'XAUUSD_CMDTY':
        # London Gold spot commodity contract
        c = Contract()
        c.symbol = 'XAU'
        c.secType = 'CMDTY'
        c.exchange = 'SMART'
        c.currency = 'USD'
        return c
    elif symbol == 'GC':
        # Gold Futures (optional)
        return Future('GC', 'COMEX', 'USD', lastTradeDateOrContractMonth='202406')
    else:
        return symbol(symbol, 'SMART', 'USD')

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

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-KEY') or request.json.get('api_key')
        if not api_key or api_key != API_KEY:
            abort(401)  # Unauthorized
        return f(*args, **kwargs)
    return decorated

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

def get_asset_position(symbol: str):
    """
    Get current number of shares and market price for a given symbol symbol.
    """
    positions = ib.positions()
    for pos in positions:
        if pos.contract.symbol.upper() == symbol.upper():
            return pos.position
    return 0  # No position

def buy(data: dict, percentage: float) -> int:
    # start buy
    # Read the latest cash balance from our shared variable.
    with account_lock:
        cash_balance = float(account_summary_data.get('TotalCashValue',0))
    if cash_balance is None:
        return jsonify({
            'status': 'error',
            'message': 'Account summary data not available.'
        }), 408
        
    cash_balance = float(cash_balance)

    # Calculate the amount to invest.
    amount_to_invest = cash_balance * (percentage / 100.0)

    current_price = data.get('price')#ticker.last if ticker.last is not None else ticker.close
    if current_price is None:
        return jsonify({
            'status': 'error',
            'message': 'Unable to retrieve current TSLA price.'
        }), 500
        
    # Calculate the number of shares to buy (rounding down).
    quantity = int(amount_to_invest / current_price)
        
    if quantity < 1:
        raise valueError('Insufficient funds to buy at least 1 share.')
    # end buy
    return quantity

def sell(symbol: str, percentage: float) -> int:
    if not symbol or percentage <= 0:
        raise ValueError("Missing or invalid symbol or percentage.")

    shares_held = get_asset_position(symbol)

    if shares_held <= 0:
        raise ValueError(f"No open position in {symbol} to sell.")

    shares_to_sell = int(shares_held * (percentage / 100.0))

    if shares_to_sell < 1:
        raise ValueError("Calculated shares to sell is less than 1.")

    return shares_to_sell

@app.route('/placeorder', methods=['POST'])
@require_api_key
@restrict_ip
def placeorder():
    if not wait_for_ib_ready():
        return jsonify({
            'status': 'error',
            'message': 'Interactive Brokers connection not ready'
        }), 503
    
    try:
        data = request.get_json()
        percentage = data.get('percentage', 5)
        symbol = data.get('symbol')
        order_type = data.get('ordertype', 'BUY').upper()
        expyire = data.get('expiry')
        price = data.get('price', 0)

        if 'symbol' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing required parameter: symbol'
            }), 400
        
        if not order_type or order_type.lower() not in ["buy", "sell"]:
            return jsonify({
                'status': 'error',
                'message': 'Missing or invalid ordertype. Must be "buy" or "sell".'
            }), 400

        # calculate quantity (buy: based on portfolio %, sell: based on position)
        if order_type == 'BUY':
            quantity = buy(data, percentage)
        elif order_type == 'SELL':
            quantity = sell(symbol, percentage)
        else:
            return jsonify({'status': 'error', 'message': 'Invalid order type'}), 400
        
        if(quantity < 1):
            return jsonify({
                'status': 'error',
                'message': 'Insufficient funds to buy at least 1 share.'
            }), 400
        
        symbol = symbol.upper()
        contract = build_contract(symbol)
        
        # Create a market order to buy the specified quantity
        order = MarketOrder(order_type, quantity)
        # Place the order
        trade = ib.placeOrder(contract, order)

        # Wait briefly for order confirmation
        time.sleep(1)

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'message': f'Placed a {order_type} order for {quantity} {symbol} share(s).'
        }), 200

    except Exception as e:
        logger.error(f"Error in placeorder endpoint: {str(e)}")
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