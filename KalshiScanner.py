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

class KalshiScannerBot:
    """Headless Arbitrage & Spread Scanner Bot."""
    
    def __init__(self):
        self.running = True
        self.log_file = "scanner_bot.log"
        self.state_file = "scanner_state.json"
        
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
    
    def get_market_data(self, ticker):
        """Calculates the gap between 'Yes' and 'No' costs."""
        try:
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
            res = requests.get(url, headers=get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
            if res.status_code == 200:
                m = res.json().get('market', {})
                yes_cost = m.get('yes_bid', 0)
                no_cost = m.get('no_bid', 0)
                # Total cost should be 100. Anything less is a 'Spread Gap'
                gap = 100 - (yes_cost + no_cost)
                target = m.get('cap', 'N/A')
                return {
                    "yes_cost": yes_cost,
                    "no_cost": no_cost,
                    "gap": gap,
                    "target": target,
                    "status": m.get('status', 'unknown').upper()
                }
        except Exception as e:
            self.log_message(f"Error getting market data for {ticker}: {e}")
            return None
        return None
    
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
    
    def scan_opportunities(self):
        """Main scanning logic for arbitrage opportunities."""
        try:
            # Check balance
            balance = self.check_balance()
            if balance is not None:
                self.log_message(f"Current balance: ${balance:.2f}")
            
            # Monitor specific tickers
            tickers = [
                "KXETH15M-26FEB191215",  # ETH 15m
                # Add more tickers as needed
            ]
            
            opportunities = []
            
            for ticker in tickers:
                data = self.get_market_data(ticker)
                if data:
                    gap = data['gap']
                    if gap > 1:  # Only log if there's a meaningful gap
                        self.log_message(f"OPPORTUNITY: {ticker} - Gap: {gap}¢, Yes: {data['yes_cost']}¢, No: {data['no_cost']}¢")
                        opportunities.append({
                            "ticker": ticker,
                            "gap": gap,
                            "yes_cost": data['yes_cost'],
                            "no_cost": data['no_cost'],
                            "status": data['status']
                        })
                    else:
                        self.log_message(f"MONITOR: {ticker} - Gap: {gap}¢ (no opportunity)")
            
            # Save opportunities to state
            if opportunities:
                self.save_state({
                    "last_scan": datetime.now().isoformat(),
                    "opportunities": opportunities,
                    "balance": balance
                })
                
        except Exception as e:
            self.log_message(f"Error in scan_opportunities: {e}")
    
    def run(self):
        """Main bot loop."""
        self.log_message("Kalshi Scanner Bot starting...")
        self.log_message(f"PID: {os.getpid()}")
        
        # Initial scan
        self.scan_opportunities()
        
        # Main loop - scan every 10 seconds
        while self.running:
            try:
                self.scan_opportunities()
                time.sleep(10)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log_message(f"Error in main loop: {e}")
                time.sleep(5)  # Wait before retrying
        
        self.log_message("Kalshi Scanner Bot stopped")

if __name__ == "__main__":
    bot = KalshiScannerBot()
    bot.run()