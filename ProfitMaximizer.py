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

class ProfitMaximizerBot:
    """Headless Profit Maximizer Bot."""
    
    def __init__(self):
        self.running = True
        self.log_file = "profit_maximizer_bot.log"
        self.state_file = "profit_maximizer_state.json"
        
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
    
    def calculate_profit_potential(self, cost_cents):
        """Calculate profit potential based on cost."""
        if cost_cents <= 0:
            return 0
        # Profit = (100 - cost) / cost * 100
        profit_percentage = ((100 - cost_cents) / cost_cents) * 100
        return profit_percentage
    
    def scan_high_profit_opportunities(self):
        """Scan for high-profit opportunities (>300% returns)."""
        try:
            balance = self.check_balance()
            if balance is not None:
                self.log_message(f"Current balance: ${balance:.2f}")
            
            # Monitor specific tickers for high-profit opportunities
            tickers = [
                "KXETH15M-26FEB191215",
                # Add more tickers as needed
            ]
            
            opportunities = []
            
            for ticker in tickers:
                market_data = self.get_market_data(ticker)
                if market_data:
                    cap = market_data.get('cap', 'N/A')
                    yes_ask = market_data.get('yes_ask', 0)  # in cents
                    no_ask = market_data.get('no_ask', 0)   # in cents
                    
                    # Check Yes side opportunities (cost between 10-25 cents)
                    if 10 <= yes_ask <= 25:
                        yes_profit = self.calculate_profit_potential(yes_ask)
                        if yes_profit > 300:
                            opportunities.append({
                                "ticker": ticker,
                                "strike": cap,
                                "side": "Yes (Up)",
                                "cost": f"{yes_ask}¢",
                                "profit_percentage": yes_profit
                            })
                            self.log_message(f"HIGH-PROFIT OPPORTUNITY: {ticker}")
                            self.log_message(f"Strike: {cap} | Yes: {yes_ask}¢ | Profit: {yes_profit:.0f}%")
                    
                    # Check No side opportunities (cost between 10-25 cents)
                    if 10 <= no_ask <= 25:
                        no_profit = self.calculate_profit_potential(no_ask)
                        if no_profit > 300:
                            opportunities.append({
                                "ticker": ticker,
                                "strike": cap,
                                "side": "No (Down)",
                                "cost": f"{no_ask}¢",
                                "profit_percentage": no_profit
                            })
                            self.log_message(f"HIGH-PROFIT OPPORTUNITY: {ticker}")
                            self.log_message(f"Strike: {cap} | No: {no_ask}¢ | Profit: {no_profit:.0f}%")
                else:
                    self.log_message(f"Failed to get market data for {ticker}")
            
            # Save opportunities to state
            if opportunities:
                self.log_message(f"Found {len(opportunities)} high-leverage opportunities")
                self.save_state({
                    "last_scan": datetime.now().isoformat(),
                    "opportunities": opportunities,
                    "balance": balance
                })
            else:
                self.log_message("No high-profit opportunities found (target: >300% returns)")
                
        except Exception as e:
            self.log_message(f"Error in scan_high_profit_opportunities: {e}")
    
    def save_state(self, state_data):
        """Save bot state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            self.log_message(f"Failed to save state: {e}")
    
    def run(self):
        """Main bot loop."""
        self.log_message("Profit Maximizer Bot starting...")
        self.log_message(f"PID: {os.getpid()}")
        self.log_message("Scanning for high-leverage dips (>300% returns)...")
        
        # Initial scan
        self.scan_high_profit_opportunities()
        
        # Main loop - scan every 5 seconds (fast scanning for opportunities)
        while self.running:
            try:
                self.scan_high_profit_opportunities()
                time.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log_message(f"Error in main loop: {e}")
                time.sleep(5)  # Wait before retrying
        
        self.log_message("Profit Maximizer Bot stopped")

if __name__ == "__main__":
    bot = ProfitMaximizerBot()
    bot.run()