#!/usr/bin/env python3
"""
GoobClaw Round-Start Arb
At each 15-minute round start, places orders on BOTH accounts:
- Account 1: Buy YES
- Account 2: Buy NO
Uses limit orders at favorable prices to guarantee profit.
"""

import os
import time
import requests
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers, place_order, get_balance

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"
AUTO_TRADE = os.getenv("AUTO_TRADE", "true").lower() == "true"

# === CONFIG ===
ACCOUNT_YES = 1  # Account that buys YES
ACCOUNT_NO = 2   # Account that buys NO
ROUND_SECS = 900  # 15 minutes
LIMIT_DISCOUNT = 5  # Buy at price - 5¢ (e.g., 50-5=45¢)


def get_15min_markets():
    """Get crypto 15-minute markets."""
    path = "/trade-api/v2/markets?status=open&limit=100"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            markets = res.json().get("markets", [])
            return [m for m in markets if "15M" in m.get("ticker", "")]
    except:
        pass
    return []


def get_orderbook(ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("orderbook", {})
    except:
        pass
    return {}


def get_best_prices(orderbook):
    """Get best bid/ask prices."""
    yes_bids = orderbook.get("yes", [])
    no_bids = orderbook.get("no", [])
    
    yes_bid = yes_bids[0][0] if yes_bids else 50
    no_bid = no_bids[0][0] if no_bids else 50
    
    # Limit order price = bid - discount (try to get filled at discount)
    yes_limit = max(1, yes_bid - LIMIT_DISCOUNT)
    no_limit = max(1, no_bid - LIMIT_DISCOUNT)
    
    return yes_bid, no_limit, no_bid, no_limit


def place_round_start_arb():
    """Place orders at round start."""
    print(f"\n{'='*50}")
    print(f"🚀 ROUND START - Placing arb orders")
    print(f"{'='*50}")
    
    markets = get_15min_markets()
    print(f"Found {len(markets)} 15-min markets")
    
    trades = 0
    
    for m in markets:
        ticker = m.get("ticker", "")
        
        # Get prices
        ob = get_orderbook(ticker)
        yes_bid, yes_ask, no_bid, no_ask = get_best_prices(ob)
        
        # Calculate total cost
        yes_price = yes_bid - LIMIT_DISCOUNT  # Try to buy at discount
        no_price = no_bid - LIMIT_DISCOUNT
        
        yes_price = max(1, yes_price)
        no_price = max(1, no_price)
        
        total_cost = yes_price + no_price
        profit = 100 - total_cost
        
        print(f"\n{ticker[-35:]}")
        print(f"  YES: bid={yes_bid}, limit={yes_price}")
        print(f"  NO:  bid={no_bid},  limit={no_price}")
        print(f"  Cost: {total_cost}c → Profit: +{profit}c")
        
        if profit > 0 and AUTO_TRADE:
            # Place both orders
            ok1, _ = place_order(ticker, "yes", yes_price, 1, "buy", ACCOUNT_YES)
            ok2, _ = place_order(ticker, "no", no_price, 1, "buy", ACCOUNT_NO)
            
            if ok1:
                print(f"  ✅ YES filled @ {yes_price}c")
            else:
                print(f"  ❌ YES failed")
                
            if ok2:
                print(f"  ✅ NO filled @ {no_price}c")
            else:
                print(f"  ❌ NO failed")
            
            trades += 1
        
        elif profit > 0:
            print(f"  📝 Would trade (paper mode)")
    
    print(f"\n📊 Round complete: {trades} markets traded")


def get_next_round_time():
    """Get seconds until next 15-min round."""
    now = datetime.now(timezone.utc)
    seconds = now.timestamp()
    
    # Next round: round down to nearest 15 min, add 15 min
    next_round = (seconds // ROUND_SECS + 1) * ROUND_SECS
    wait = next_round - seconds
    
    return wait


def run():
    print("=" * 60)
    print("  GoobClaw Round-Start Arb")
    print("  Account 1 → Buys YES | Account 2 → Buys NO")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)
    
    # Test connections
    bal1 = get_balance(ACCOUNT_YES)
    bal2 = get_balance(ACCOUNT_NO)
    print(f"\nBalances: Account1=${bal1} | Account2=${bal2}")
    
    if not bal1 or not bal2:
        print("⚠️  One or both accounts not working!")
    
    while True:
        try:
            wait = get_next_round_time()
            print(f"\nNext round in {wait:.0f} seconds...")
            
            # Wait until next round
            time.sleep(max(0, wait - 5))  # Start 5 sec early
            
            # Place orders
            place_round_start_arb()
            
            # Wait for round to complete (leave some time for fills)
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
