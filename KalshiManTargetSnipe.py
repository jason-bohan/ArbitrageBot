import os
import sys
import time
import base64
import requests
import uuid
import signal
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv()

class KalshiManTargetSnipeBot:
    """Headless Manual Target Sniper Bot."""
    
    def __init__(self):
        self.running = True
        self.log_file = "man_target_snipe_bot.log"
        self.state_file = "man_target_snipe_state.json"
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID")
        self.private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        # Switching to the primary trading API for better reliability
        self.base_url = "https://trading-api.kalshi.com" 
        self.active_positions = {}
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.log_message(f"Received signal {signum}, shutting down...")
        self.running = False
        
    def log_message(self, message: str):
        """Log messages to file with timestamp."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}\n"
        
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
            print(log_entry.strip())  # Also print to console for debugging
        except Exception as e:
            print(f"Failed to write to log: {e}")

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

    def get_active_markets(self):
        path = "/trade-api/v2/markets?status=open&limit=5&order_by=closing"
        res = requests.get(self.base_url + path, headers=self.get_headers("GET", path))
        if res.status_code == 200:
            return res.json().get('markets', [])
        return []

    def monitor_and_execute(self, ticker):
        path = f"/trade-api/v2/markets/{ticker}/orderbook"
        res = requests.get(self.base_url + path, headers=self.get_headers("GET", path))
        
        if res.status_code == 200:
            ob = res.json().get('orderbook', {})
            # 'yes' is the list of people wanting to SELL Yes contracts to you
            yes_asks = ob.get('yes', []) 
            
            if not yes_asks:
                return

            # The price we actually pay to buy RIGHT NOW
            current_ask_price = yes_asks[0][0] 

            if ticker in self.active_positions:
                # Stop Loss Check
                if current_ask_price <= 50:
                    self.log_message(f"⚠️ STOP LOSS: {ticker} @ {current_ask_price}%")
                    self.place_order(ticker, "sell", 5)
                    del self.active_positions[ticker]
            else:
                # Diagnostics: Print exactly what the bot is seeing
                self.log_message(f"{ticker[:12]} Ask: {current_ask_price}% | Target: 60%+")
                
                if current_ask_price >= 60:
                    self.log_message(f"🎯 THRESHOLD MET! Buying 5 contracts of {ticker} at {current_ask_price}%")
                    if self.place_order(ticker, "buy", 5):
                        self.active_positions[ticker] = current_ask_price

    def place_order(self, ticker, action, count):
        path = "/trade-api/v2/portfolio/orders"
        payload = {
            "ticker": ticker, "action": action, 
            "type": "market", "side": "yes", "count": count, 
            "client_order_id": str(uuid.uuid4())
        }
        res = requests.post(self.base_url + path, json=payload, headers=self.get_headers("POST", path))
        if res.status_code == 201:
            self.log_message(f"✅ {action.upper()} order successful.")
            return True
        self.log_message(f"❌ {action.upper()} FAILED: {res.text}")
        return False
    
    def save_state(self, state_data):
        """Save bot state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            self.log_message(f"Failed to save state: {e}")
    
    def run(self):
        """Main bot loop."""
        self.log_message("Kalshi Manual Target Sniper Bot starting...")
        self.log_message(f"PID: {os.getpid()}")
        
        try:
            while self.running:
                markets = self.get_active_markets()
                for m in markets:
                    if not self.running:
                        break
                    self.monitor_and_execute(m['ticker'])
                time.sleep(0.5) # Faster polling
        except KeyboardInterrupt:
            pass
        finally:
            # Save current state
            self.save_state({
                "last_run": datetime.now().isoformat(),
                "active_positions": self.active_positions
            })
            self.log_message("Kalshi Manual Target Sniper Bot stopped")

if __name__ == "__main__":
    bot = KalshiManTargetSnipeBot()
    bot.run()