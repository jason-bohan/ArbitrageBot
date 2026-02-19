import os
import time
import base64
import requests
import uuid
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv()

class KalshiDynamicTester:
    def __init__(self):
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self.base_url = "https://api.elections.kalshi.com"

    def sign_msg(self, message):
        with open(self.private_key_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        signature = key.sign(
            message.encode('utf-8'),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')

    def get_headers(self, method, path):
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": self.sign_msg(ts + method + path),
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json"
        }

    def find_active_xrp_ticker(self):
        """Finds the ticker for XRP that is actually open right now"""
        path = "/trade-api/v2/markets?status=open&series_ticker=KXXRP"
        res = requests.get(self.base_url + path, headers=self.get_headers("GET", path))
        if res.status_code == 200:
            markets = res.json().get('markets', [])
            if markets:
                return markets[0]['ticker']
        return None

    def execute_force_buy(self):
        ticker = self.find_active_xrp_ticker()
        if not ticker:
            print("❌ Could not find an active XRP market. Checking general markets...")
            # Fallback to the highest volume market if XRP is down
            path = "/trade-api/v2/markets?status=open&limit=1&order_by=volume"
            res = requests.get(self.base_url + path, headers=self.get_headers("GET", path))
            ticker = res.json().get('markets', [{}])[0].get('ticker')

        if not ticker:
            print("❌ No open markets found at all.")
            return

        path = "/trade-api/v2/portfolio/orders"
        payload = {
            "ticker": ticker,
            "action": "buy",
            "type": "market",
            "side": "yes",
            "count": 1,
            "yes_price": 75, # High limit to ensure it fills for the test
            "client_order_id": str(uuid.uuid4())
        }
        
        print(f"📡 Found Active Ticker: {ticker}")
        print(f"📡 Sending Force-Buy for {ticker}...")
        res = requests.post(self.base_url + path, json=payload, headers=self.get_headers("POST", path))
        
        if res.status_code == 201:
            print(f"✅ SUCCESS! 1 contract of {ticker} purchased.")
        else:
            print(f"❌ FAILED! Status Code: {res.status_code}")
            print(f"Reason: {res.text}")

if __name__ == "__main__":
    tester = KalshiDynamicTester()
    tester.execute_force_buy()