@app.route('/placeorder', methods=['POST'])
#@require_api_key
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

        if 'stock' not in data:
            return jsonify({
                'status': 'error',
                'message': 'Missing required parameter: stock'
            }), 400
        
        stock = data.get('stock')
        
        # start buy
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

        # Define the Tesla stock contract
        contract = Stock(stock, 'SMART', 'USD')

        # Request market data snapshot (avoiding live stream issues)
        logger.info("Requesting TSLA market data snapshot...")
        ticker = ib.reqMktData(contract, snapshot=True, regulatorySnapshot=False)
        ib.sleep(2)  # Allow IB time to return the data

        current_price = data.get('price')#ticker.last if ticker.last is not None else ticker.close
        if current_price is None:
            return jsonify({
                'status': 'error',
                'message': 'Unable to retrieve current TSLA price.'
            }), 500
        
        # Calculate the number of shares to buy (rounding down).
        quantity = int(amount_to_invest / current_price)
        print("", amount_to_invest)
        print("quantity",quantity)
        
        
        if quantity < 1:
            return jsonify({
                'status': 'error',
                'message': 'Insufficient funds to buy at least 1 share.'
            }), 400
        # end buy
        
        # Define the Tesla stock contract
        contract = Stock(stock, 'SMART', 'USD')
        order_type = data.get('ordertype')
        # Create a market order to buy the specified quantity
        order = MarketOrder(order_type, quantity)
        # Place the order
        trade = ib.placeOrder(contract, order)

        # Wait briefly for order confirmation
        time.sleep(1)

        return jsonify({
            'status': 'success',
            'orderId': trade.order.orderId,
            'message': f'Placed a {order_type} order for {quantity} {stock} share(s).'
        }), 200

    except Exception as e:
        logger.error(f"Error in placeorder endpoint: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500