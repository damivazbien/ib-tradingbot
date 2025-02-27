from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import *
import threading
import time

class IBapi(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.nextorderId = None

    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.nextorderId = orderId
        print('The next valid order id is: ', self.nextorderId)

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        print('orderStatus - orderid:', orderId, 'status:', status, 'filled', filled, 'remaining', remaining, 'lastFillPrice', lastFillPrice)

    def openOrder(self, orderId, contract, order, orderState):
        print('openOrder id:', orderId, contract.symbol, contract.secType, '@', contract.exchange, ':', order.action, order.orderType, order.totalQuantity, orderState.status)

    def execDetails(self, reqId, contract, execution):
        print('Order Executed: ', reqId, contract.symbol, contract.secType, contract.currency, execution.execId, execution.orderId, execution.shares, execution.lastLiquidity)

def run_loop():
    app.run()

app = IBapi()
app.connect('127.0.0.1', 7497, 123)

api_thread = threading.Thread(target=run_loop, daemon=True)
api_thread.start()

# Wait for the connection to be established
while app.nextorderId is None:
    time.sleep(1)

order = Order()
order.action = 'BUY'
order.totalQuantity = 0.05
order.orderType = 'MKT'
order.eTradeOnly = False
order.firmQuoteOnly = False

# Place order
app.placeOrder(app.nextorderId, FX_order("BTC", "CASH", "USD", "PAXOS"), order)

time.sleep(3)

# Cancel order
print('cancelling order')
app.cancelOrder(app.nextorderId)

time.sleep(3)
app.disconnect()