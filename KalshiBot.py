import os
import time
import base64
import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv()

class KalshiArbScanner:
    def __init__(self):
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self.base_url = "https://api.elections.kalshi.com"
        
        with open(self.private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(f.read(), password=None)

    def sign_msg(self, message):
        signature = self.private_key.sign(
            message.encode('utf-8'),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')

    def get_headers(self, method, path):
        timestamp = str(int(time.time() * 1000))
        msg = timestamp + method + path
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": self.sign_msg(msg),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }

    def scan_market(self, ticker):
        path = f"/trade-api/v2/markets/{ticker}/orderbook"
        try:
            res = requests.get(self.base_url + path, headers=self.get_headers("GET", path))
            if res.status_code == 200:
                ob = res.json().get('orderbook', {})
                yes_side = ob.get('yes')
                no_side = ob.get('no')

                if not yes_side or not no_side:
                    print(f"⚠️ {ticker}: No active bids/asks found.")
                    return

                # Best Bid for Yes is the last item in the 'yes' list
                # Best Bid for No is the last item in the 'no' list
                best_yes_bid = yes_side[-1][0]
                best_no_bid = no_side[-1][0]
                
                # Math: Cost to buy both sides
                yes_cost = (100 - best_no_bid) / 100
                no_cost = (100 - best_yes_bid) / 100
                total_cost = yes_cost + no_cost
                
                print(f"\n📊 TICKER: {ticker}")
                print(f"Combined Cost: ${total_cost:.2f}")

                if total_cost < 1.00:
                    print(f"🚀 ARBITRAGE! Profit: ${1.00 - total_cost:.2f}")
                else:
                    print(f"❌ Cost is ${total_cost:.2f} (No Arb)")
            else:
                print(f"❌ Error {res.status_code} for {ticker}")
        except Exception as e:
            print(f"❌ Script Error: {e}")

if __name__ == "__main__":
    scanner = KalshiArbScanner()
    # Updated tickers based on your current screen
    # Note: Ticker strings usually follow a pattern. 
    # Check the URL of the specific '66,500 or above' market for the exact ID.
    active_tickers = [
        "BTC-26FEB19-T66500", 
        "NDX-26FEB19-T24850"
    ] 
    
    for t in active_tickers:
        scanner.scan_market(t)