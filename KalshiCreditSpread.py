import os
import sys
import time
import base64
import requests
import uuid
import signal
import json
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from datetime import datetime, timedelta
from kalshi_connection import get_kalshi_headers

load_dotenv()

class KalshiCreditSpreadBot:
    """Headless Credit Spread Trading Bot."""
    
    def __init__(self):
        self.running = True
        self.log_file = "credit_spread_bot.log"
        self.state_file = "credit_spread_state.json"
        self.active_ticker = "KXETH15M-26FEB191230"
        
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
    
    def save_state(self, state_data):
        """Save bot state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            self.log_message(f"Failed to save state: {e}")
    
    def load_state(self):
        """Load bot state from file."""
        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except:
            return {}
    
    def get_kalshi_headers(self, method, path):
        """Get Kalshi API headers with content type for POST requests."""
        headers = get_kalshi_headers(method, path)
        if method == "POST":
            headers["Content-Type"] = "application/json"
        return headers
    
    def place_order(self, count=5):
        """Place a credit spread order."""
        path = "/trade-api/v2/portfolio/orders"
        url = "https://api.elections.kalshi.com" + path
        
        # Using a Limit Order at 99 cents to ensure it fills but doesn't overpay
        payload = {
            "action": "buy",
            "count": count,
            "side": "no",
            "ticker": self.active_ticker,
            "type": "limit",
            "yes_price": 99, 
            "client_order_id": str(uuid.uuid4())
        }
        
        try:
            res = requests.post(url, json=payload, headers=self.get_kalshi_headers("POST", path))
            if res.status_code == 201:
                self.log_message(f"✅ ORDER PLACED: {count} contracts on {self.active_ticker}")
                return True
            else:
                self.log_message(f"❌ API Error: {res.text}")
                return False
        except Exception as e:
            self.log_message(f"Order Error: {str(e)}")
            return False
    
    def check_balance(self):
        """Check current account balance."""
        try:
            b_path = "/trade-api/v2/portfolio/balance"
            base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
            url = base_url + b_path
            res = requests.get(url, headers=get_kalshi_headers("GET", b_path))
            if res.status_code == 200:
                balance = res.json().get('balance', 0) / 100
                return balance
        except Exception as e:
            self.log_message(f"Error checking balance: {e}")
        return None
    
    def get_market_data(self, ticker):
        """Get market data for a specific ticker."""
        try:
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
            res = requests.get(url, headers=get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
            if res.status_code == 200:
                return res.json().get('market', {})
        except Exception as e:
            self.log_message(f"Error getting market data for {ticker}: {e}")
        return None
    
    def calculate_time_to_expiry(self):
        """Calculate time until next 30-minute mark."""
        now = datetime.now()
        target = now.replace(minute=30, second=0, microsecond=0)
        if now.minute >= 30: 
            target += timedelta(hours=1)
        remaining = target - now
        return f"{remaining.seconds // 60:02d}:{remaining.seconds % 60:02d}"
    
    def scan_opportunities(self):
        """Scan for credit spread opportunities."""
        try:
            # Check balance
            balance = self.check_balance()
            if balance is not None:
                self.log_message(f"Current balance: ${balance:.2f}")
            
            # Get market data
            market_data = self.get_market_data(self.active_ticker)
            if market_data:
                yes_price = market_data.get('yes_ask', 0)
                no_price = market_data.get('no_ask', 0)
                cushion = 100 - (yes_price + no_price)
                
                time_left = self.calculate_time_to_expiry()
                
                self.log_message(f"Market: {self.active_ticker}")
                self.log_message(f"Cushion: ${cushion/100:.2f}, Yes: {yes_price}¢, No: {no_price}¢")
                self.log_message(f"Time to expiry: {time_left}")
                
                # Save current state
                self.save_state({
                    "last_scan": datetime.now().isoformat(),
                    "active_ticker": self.active_ticker,
                    "cushion": cushion,
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "balance": balance,
                    "time_to_expiry": time_left
                })
                
                # Auto-trade logic (optional - can be enabled/disabled)
                # if cushion > 150:  # If cushion is more than $1.50
                #     self.log_message("Opportunity detected - placing order...")
                #     self.place_order()
                
            else:
                self.log_message(f"Failed to get market data for {self.active_ticker}")
                
        except Exception as e:
            self.log_message(f"Error in scan_opportunities: {e}")
    
    def run(self):
        """Main bot loop."""
        self.log_message("Kalshi Credit Spread Bot starting...")
        self.log_message(f"PID: {os.getpid()}")
        self.log_message(f"Active ticker: {self.active_ticker}")
        
        # Initial scan
        self.scan_opportunities()
        
        # Main loop - scan every 10 seconds, update countdown every second
        countdown_counter = 0
        while self.running:
            try:
                if countdown_counter % 10 == 0:
                    self.scan_opportunities()
                else:
                    # Just update countdown
                    time_left = self.calculate_time_to_expiry()
                    self.log_message(f"Time to expiry: {time_left}")
                
                time.sleep(1)
                countdown_counter += 1
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log_message(f"Error in main loop: {e}")
                time.sleep(5)  # Wait before retrying
        
        self.log_message("Kalshi Credit Spread Bot stopped")

if __name__ == "__main__":
    bot = KalshiCreditSpreadBot()
    bot.run()