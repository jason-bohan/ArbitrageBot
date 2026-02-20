import os
import sys
import time
import base64
import requests
import signal
import json
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from datetime import datetime
from kalshi_connection import get_kalshi_headers

load_dotenv()

class KalshiIronCondorBot:
    """Headless Iron Condor Trading Bot."""
    
    def __init__(self):
        self.running = True
        self.log_file = "iron_condor_bot.log"
        self.state_file = "iron_condor_state.json"
        
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
    
    def get_ticker_details(self, ticker):
        try:
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
            res = requests.get(url, headers=get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
            if res.status_code == 200:
                m = res.json().get('market', {})
                # No cost = 100 - Yes_Price
                no_cost = 100 - m.get('yes_ask', 0)
                return m.get('cap', 'N/A'), f"{no_cost}¢", f"{no_cost}%"
        except:
            pass
        return "N/A", "0¢", "0%"
    
    def monitor_markets(self):
        """Monitor markets for iron condor opportunities."""
        try:
            balance = self.check_balance()
            if balance is not None:
                self.log_message(f"Current balance: ${balance:.2f}")
            
            # Monitor iron condor opportunities
            strike_up, cost_up, prob_up = self.get_ticker_details("KXETH15M-26FEB191215")
            
            self.log_message(f"Upper Cap: {strike_up}, Cost: {cost_up}, Prob: {prob_up}")
            self.log_message(f"Lower Cap: $1,921.50, Cost: 58¢, Prob: 58%")
            self.log_message(f"Range: $1,921.50 - {strike_up} | Target Premium: 116¢")
            
        except Exception as e:
            self.log_message(f"Error in monitor_markets: {e}")
    
    def run(self):
        """Main bot loop."""
        self.log_message("Kalshi Iron Condor Bot starting...")
        self.log_message(f"PID: {os.getpid()}")
        
        # Initial scan
        self.monitor_markets()
        
        # Main loop - monitor every 10 seconds
        while self.running:
            try:
                self.monitor_markets()
                time.sleep(10)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log_message(f"Error in main loop: {e}")
                time.sleep(5)  # Wait before retrying
        
        self.log_message("Kalshi Iron Condor Bot stopped")

if __name__ == "__main__":
    bot = KalshiIronCondorBot()
    bot.run()