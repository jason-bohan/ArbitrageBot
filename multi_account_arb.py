#!/usr/bin/env python3
"""
GoobClaw Multi-Account Arb Hunter
Uses TWO accounts:
- Account 1: Buys YES
- Account 2: Buys NO
Executes both legs simultaneously for guaranteed arbitrage.
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers, place_order, get_balance

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"

# === CONFIG ===
ACCOUNT_YES = 1  # Account that buys YES
ACCOUNT_NO = 2   # Account that buys NO


def get_all_markets():
    """Get all open markets."""
    now = datetime.now(timezone.utc)
    path = "/trade-api/v2/markets?status=open&limit=200"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except:
        pass
    return []


def find_arbs(markets):
    """Find arbitrage opportunities (YES + NO < 99¢)."""
    arbs = []
    
    for m in markets:
        ya = m.get("yes_ask", 0)
        na = m.get("no_ask", 0)
        ticker = m.get("ticker", "")
        
        # Skip settled
        if ya == 0 or na == 0:
            continue
        
        total = ya + na
        
        # ARB: YES + NO < 99¢
        if total < 99:
            profit = 100 - total
            arbs.append({
                "ticker": ticker,
                "yes_ask": ya,
                "no_ask": na,
                "total": total,
                "profit": profit
            })
    
    return sorted(arbs, key=lambda x: x["profit"], reverse=True)


def execute_dual_arb(arb, pairs=1):
    """Execute arbitrage: YES on account 1, NO on account 2."""
    ticker = arb["ticker"]
    yes_price = arb["yes_ask"]
    no_price = arb["no_ask"]
    
    print(f"\n{'='*50}")
    print(f"🚨 EXECUTING DUAL ACCOUNT ARB")
    print(f"{'='*50}")
    print(f"Ticker: {ticker[-40:]}")
    print(f"YES @ {yes_price}c (Account {ACCOUNT_YES})")
    print(f"NO  @ {no_price}c (Account {ACCOUNT_NO})")
    print(f"Total cost: {arb['total']}c | Profit: +{arb['profit']:.1f}c/pair")
    print(f"Pairs: {pairs}")
    
    # Check balances first
    bal1 = get_balance(ACCOUNT_YES)
    bal2 = get_balance(ACCOUNT_NO)
    print(f"\nBalances: Account1=${bal1 or '?'} | Account2=${bal2 or '?'}")
    
    if not AUTO_TRADE:
        print("\n📝 PAPER TRADE — No orders placed")
        return True
    
    # Place BOTH orders simultaneously
    print(f"\n🔄 Placing orders...")
    
    ok1, res1 = place_order(ticker, "yes", yes_price, pairs, action="buy", account=ACCOUNT_YES)
    ok2, res2 = place_order(ticker, "no", no_price, pairs, action="buy", account=ACCOUNT_NO)
    
    if ok1 and ok2:
        print(f"   ✅ YES order filled (Account {ACCOUNT_YES})")
        print(f"   ✅ NO order filled (Account {ACCOUNT_NO})")
        print(f"\n🎉 ARB COMPLETE! Hold to expiration for +${pairs * arb['profit'] / 100:.2f}")
        return True
    else:
        print(f"   ❌ YES failed: {res1[:100]}")
        print(f"   ❌ NO failed: {res2[:100]}")
        return False


def run():
    print("=" * 60)
    print("  GoobClaw Multi-Account Arb Hunter")
    print("  Account 1 → Buys YES")
    print("  Account 2 → Buys NO")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)
    
    # Test both connections
    print("\n🔗 Testing connections...")
    bal1 = get_balance(ACCOUNT_YES)
    bal2 = get_balance(ACCOUNT_NO)
    
    if bal1:
        print(f"   ✅ Account 1: ${bal1:.2f}")
    else:
        print(f"   ❌ Account 1: Connection failed")
    
    if bal2:
        print(f"   ✅ Account 2: ${bal2:.2f}")
    else:
        print(f"   ⚠️  Account 2: Not configured (set KALSHI_API_KEY_ID_2 and KALSHI_PRIVATE_KEY_PATH_2)")
    
    if not bal1:
        print("\n❌ Account 1 failed — cannot continue")
        return
    
    last_arbs = set()
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            markets = get_all_markets()
            arbs = find_arbs(markets)
            
            if arbs:
                for arb in arbs:
                    ticker = arb["ticker"]
                    
                    if ticker not in last_arbs:
                        print(f"\n[{ts}] 🚨 NEW ARB: {ticker[-40:]}")
                        print(f"   YES={arb['yes_ask']} + NO={arb['no_ask']} = {arb['total']}c (+{arb['profit']:.1f}c)")
                        
                        # Execute
                        execute_dual_arb(arb)
                        
                        last_arbs.add(ticker)
            else:
                if int(time.time()) % 10 == 0:
                    print(f"[{ts}] Scanning {len(markets)} markets... (no arbs)", end="\r")
            
            # Clean old
            if len(last_arbs) > 50:
                last_arbs = set()
            
            time.sleep(3)  # Scan every 3 seconds
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    run()