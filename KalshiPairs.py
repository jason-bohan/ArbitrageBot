import os
import sys
import time
import math
import signal
import json
import requests
from dotenv import load_dotenv
from datetime import datetime
from kalshi_connection import get_kalshi_headers

load_dotenv()

class KalshiPairsBot:
    """Headless Pairs Arbitrage Bot."""
    
    def __init__(self):
        self.running = True
        self.log_file = "pairs_bot.log"
        self.state_file = "pairs_state.json"
        
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
    
    def calculate_kalshi_arbitrage(self, account_balance, price_yes, price_no):
        """
        One-stop calculator for Kalshi arbitrage. 
        Accounts for typical taker fees and total capital allocation.
        """
        # 1. Fee Calculation 
        price_sum = price_yes + price_no
        profit_potential = 1.00 - price_sum
        
        # Simple fee estimate (adjust based on your actual tier)
        estimated_fee_per_pair = 0.07 * price_sum * (1 - price_sum)
        
        total_cost_per_pair = price_sum + estimated_fee_per_pair
        
        # 2. Capital Allocation
        if total_cost_per_pair >= 1.00:
            return None, "NO ARBITRAGE: The total cost (with fees) is >= $1.00. You would lose money."

        total_pairs = math.floor(account_balance / total_cost_per_pair)
        total_investment = total_pairs * total_cost_per_pair
        guaranteed_payout = total_pairs * 1.00
        net_profit = guaranteed_payout - total_investment
        roi_percent = (net_profit / total_investment) * 100

        return {
            "balance": account_balance,
            "yes_price": price_yes,
            "no_price": price_no,
            "total_cost_per_pair": total_cost_per_pair,
            "total_pairs": total_pairs,
            "total_investment": total_investment,
            "guaranteed_payout": guaranteed_payout,
            "net_profit": net_profit,
            "roi_percent": roi_percent
        }, None
    
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
    
    def get_market_prices(self, ticker):
        """Get yes/no prices for a market."""
        try:
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
            res = requests.get(url, headers=get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
            if res.status_code == 200:
                market = res.json().get('market', {})
                yes_price = market.get('yes_ask', 0) / 100  # Convert from cents to dollars
                no_price = market.get('no_ask', 0) / 100
                return yes_price, no_price
        except Exception as e:
            self.log_message(f"Error getting market prices for {ticker}: {e}")
        return None, None
    
    def scan_arbitrage_opportunities(self):
        """Scan for arbitrage opportunities across markets."""
        try:
            balance = self.check_balance()
            if balance is None:
                return
            
            self.log_message(f"Current balance: ${balance:.2f}")
            
            # Monitor specific tickers for arbitrage
            tickers = [
                "KXETH15M-26FEB191215",
                # Add more tickers as needed
            ]
            
            opportunities = []
            
            for ticker in tickers:
                yes_price, no_price = self.get_market_prices(ticker)
                if yes_price is not None and no_price is not None:
                    result, error = self.calculate_kalshi_arbitrage(balance, yes_price, no_price)
                    
                    if result:
                        self.log_message(f"ARBITRAGE OPPORTUNITY: {ticker}")
                        self.log_message(f"Yes: ${yes_price:.2f} | No: ${no_price:.2f}")
                        self.log_message(f"Net Profit: ${result['net_profit']:.2f} | ROI: {result['roi_percent']:.2f}%")
                        opportunities.append(result)
                    elif error:
                        self.log_message(f"No arbitrage for {ticker}: {error}")
                else:
                    self.log_message(f"Failed to get prices for {ticker}")
            
            # Save opportunities to state
            if opportunities:
                self.save_state({
                    "last_scan": datetime.now().isoformat(),
                    "opportunities": opportunities,
                    "balance": balance
                })
                
        except Exception as e:
            self.log_message(f"Error in scan_arbitrage_opportunities: {e}")
    
    def save_state(self, state_data):
        """Save bot state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            self.log_message(f"Failed to save state: {e}")
    
    def run(self):
        """Main bot loop."""
        self.log_message("Kalshi Pairs Arbitrage Bot starting...")
        self.log_message(f"PID: {os.getpid()}")
        
        # Initial scan
        self.scan_arbitrage_opportunities()
        
        # Main loop - scan every 30 seconds (arbitrage doesn't change as fast)
        while self.running:
            try:
                self.scan_arbitrage_opportunities()
                time.sleep(30)
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log_message(f"Error in main loop: {e}")
                time.sleep(5)  # Wait before retrying
        
        self.log_message("Kalshi Pairs Arbitrage Bot stopped")

if __name__ == "__main__":
    bot = KalshiPairsBot()
    bot.run()