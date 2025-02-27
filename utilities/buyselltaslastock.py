from ibapi.client import *
from ibapi.wrapper import *

class TestApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
    
    def nextValidId(self, orderId: int):
        mycontract = Contract()
        mycontract.symbol = "AAPL"
        mycontract.secType = "STK"  
        mycontract.exchange = "SMART"
        mycontract.currency = "USD"

        self.reqContractDetails(orderId, mycontract)
    
    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        print("contractDetails: ", reqId, contractDetails.contract)

        myoder = Order()
        myoder.orderId = reqId
        myoder.action = "BUY"
        myoder.totalQuantity = 10
        myoder.orderType = "MKT"

        self.placeOrder(reqId, contractDetails.contract, myoder)

app = TestApp()
app.connect("127.0.0.1", 7497, 1000)
app.run()