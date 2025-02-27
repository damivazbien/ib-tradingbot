import threading
import time
from flask import Flask, request, jsonify
from ib_insync import IB, Stock, MarketOrder
import asyncio

app = Flask(__name__)

# Global dictionary to store the latest account summary values.
account_summary_data = {}
account_lock = threading.Lock()

# Connect to Interactive Brokers TWS (demo account)
ib = IB()
# ib.connect('127.0.0.1', 7497, clientId=1)

def onAccountSummary(item, updated):
    """
    Callback function that is called whenever account summary data is updated.
    It updates the global account_summary_data dictionary.
    """
    with account_lock:
        account_summary_data[item.tag] = item.value
        account_summary_data["initial session balance"] = item.value

def ib_thread_func():
    """
    Connect to IB and run its event loop in a dedicated thread.
    Subscribe to account summary updates.
    """
    ib.connect('127.0.0.1', 7497, clientId=1)
    # Subscribe to account summary updates.
    ib.accountSummaryEvent += onAccountSummary
    # Request account summary data (this request will trigger the callback).
    ib.reqAccountSummary()
    ib.run()  # Keeps the IB event loop running indefinitely

# Start the IB thread as a daemon so it stops with the main program.
ib_thread = threading.Thread(target=ib_thread_func, daemon=True)
ib_thread.start()

@app.route('/buy', methods=['POST'])
def buy():
    try:
        data = request.get_json()
        percentage = data.get('percentage', 5)
        #quantity = data.get('quantity', 1)  # default to 1 share if not specified

        # Read the latest cash balance from our shared variable.
        with account_lock:
            cash_balance = account_summary_data.get('TotalCashValue')
        if cash_balance is None:
            return jsonify({
                'status': 'error',
                'message': 'Account summary data not available.'
            }), 408

        cash_balance = float(cash_balance)
        
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
        contract = Stock('TSLA', 'SMART', 'USD')

        # Create a market order to buy the specified quantity
        order = MarketOrder('BUY', quantity)

        # Place the order
        trade = ib.placeOrder(contract, order)

        # Optional: wait briefly for order confirmation
        ib.sleep(1)

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'message': f'Placed a BUY order for {quantity} TSLA share(s).'
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/sell', methods=['POST'])
def sell():
    try:
        data = request.get_json()
        quantity = data.get('quantity', 1)  # default to 1 share if not specified

        # Define the Tesla stock contract
        contract = Stock('TSLA', 'SMART', 'USD')

        # Create a market order to sell the specified quantity
        order = MarketOrder('SELL', quantity)

        # Place the order
        trade = ib.placeOrder(contract, order)

        # Optional: wait briefly for order confirmation
        ib.sleep(1)

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'message': f'Placed a SELL order for {quantity} TSLA share(s).'
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/accountinfo', methods=['GET'])
def get_account_info():
    try:
        summary = ib.accountSummary()
        ib.sleep(5)  # wait longer if necessary
        for item in summary:
            print(f'{item.tag}: {item.value}')
        ib.disconnect()
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/balance', methods=['GET'])
def get_balance():
    """
    Returns the latest cash balance (e.g. 'TotalCashValue') from the account.
    Instead of calling ib.accountSummary() directly, it reads the shared data.
    """
    # Give IB a moment to update the account summary data.
    time.sleep(2)
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

@app.route('/buyPercentage', methods=['POST'])
def buy_percentage():
    """
    Endpoint that receives a JSON payload with a 'percentage' value.
    It calculates the dollar amount to invest (percentage of available cash)
    and then calculates the number of TSLA shares to buy based on the current market price.
    """
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

        print("account_summary_data",account_summary_data)
        # Read the latest cash balance from our shared variable.
        with account_lock:
            cash_balance = account_summary_data.get('TotalCashValue')
        if cash_balance is None:
            return jsonify({
                'status': 'error',
                'message': 'Account summary data not available.'
            }), 408

        cash_balance = float(cash_balance)
        # Calculate the amount to invest.
        amount_to_invest = cash_balance * (percentage / 100.0)

        # Retrieve the current market price for TSLA.
        contract = Stock('TSLA', 'SMART', 'USD')
        #ib.qualifyContracts(contract)
        #ticker = ib.reqMktData(contract)
        # Wait briefly for market data to arrive.
        #ib.sleep(2)
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

        # Place a market order for TSLA.
        # order = MarketOrder('BUY', quantity)
        # trade = ib.placeOrder(contract, order)
        # ib.sleep(1)  # Give IB time to process the order

        return jsonify({
            'status': 'success',
            #'orderId': trade.order.orderId,
            'quantity': quantity,
            'invested_amount': amount_to_invest,
            'current_price': current_price,
            'message': f'Placed a BUY order for {quantity} TSLA share(s) representing {percentage}% of cash balance.'
        }), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# @app.route('/buyPercentage', methods=['POST'])
# def buy_percentage():
#     """
#     Endpoint that receives a JSON payload with a 'percentage' value.
#     It calculates the dollar amount to invest (percentage of available cash)
#     and then calculates the number of TSLA shares to buy based on the current market price.
#     """
#     try:
#         data = request.get_json()
#         percentage = data.get('percentage')
#         if percentage is None:
#             return jsonify({
#                 'status': 'error',
#                 'message': 'Percentage parameter is required.'
#             }), 400

#         try:
#             percentage = float(percentage)
#         except ValueError:
#             return jsonify({
#                 'status': 'error',
#                 'message': 'Percentage must be a number.'
#             }), 400

#         if percentage <= 0 or percentage > 100:
#             return jsonify({
#                 'status': 'error',
#                 'message': 'Percentage must be between 0 and 100.'
#             }), 400

#         print("account_summary_data",account_summary_data)
#         # Read the latest cash balance from our shared variable.
#         with account_lock:
#             cash_balance = account_summary_data.get('TotalCashValue')
#         if cash_balance is None:
#             return jsonify({
#                 'status': 'error',
#                 'message': 'Account summary data not available.'
#             }), 408

#         cash_balance = float(cash_balance)
#         # Calculate the amount to invest.
#         amount_to_invest = cash_balance * (percentage / 100.0)

#         # Retrieve the current market price for TSLA.
#         contract = Stock('TSLA', 'SMART', 'USD')
#         ib.qualifyContracts(contract)
#         ticker = ib.reqMktData(contract)
#         # Wait briefly for market data to arrive.
#         ib.sleep(2)
#         current_price = ticker.last if ticker.last is not None else ticker.close
#         if current_price is None:
#             return jsonify({
#                 'status': 'error',
#                 'message': 'Unable to retrieve current TSLA price.'
#             }), 500

#         # Calculate the number of shares to buy (rounding down).
#         quantity = int(amount_to_invest / current_price)
#         if quantity < 1:
#             return jsonify({
#                 'status': 'error',
#                 'message': 'Insufficient funds to buy at least 1 share.'
#             }), 400

#         # Place a market order for TSLA.
#         order = MarketOrder('Sell', quantity)
#         trade = ib.placeOrder(contract, order)
#         ib.sleep(1)  # Give IB time to process the order

#         return jsonify({
#             'status': 'success',
#             'orderId': trade.order.orderId,
#             'quantity': quantity,
#             'invested_amount': amount_to_invest,
#             'current_price': current_price,
#             'message': f'Placed a BUY order for {quantity} TSLA share(s) representing {percentage}% of cash balance.'
#         }), 200

#     except Exception as e:
#         return jsonify({
#             'status': 'error',
#             'message': str(e)
#         }), 500

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
