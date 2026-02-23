#!/usr/bin/env python3
"""
GoobClaw 15-Minute Arb Hunter
Scans crypto 15-min markets EVERY SECOND for arb windows.
Catches brief price dislocations in volatile markets.
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"


def get_15min_markets():
    """Get all 15-minute markets."""
    now = datetime.now(timezone.utc)
    path = "/trade-api/v2/markets?status=open&limit=100"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            markets = res.json().get("markets", [])
            # Filter for 15-minute markets
            fifteen_min = [m for m in markets if "15M" in m.get("ticker", "")]
            return fifteen_min
    except:
        pass
    return []


def find_arbs(markets):
    """Find all arbitrage opportunities."""
    arbs = []
    
    for m in markets:
        ya = m.get("yes_ask", 0)
        na = m.get("no_ask", 0)
        ticker = m.get("ticker", "")
        
        # Skip settled
        if ya == 0 or na == 0:
            continue
        
        total = ya + na
        
        # ARB: YES + NO < 99¢ (huge arb!)
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


def place_order(ticker, side, price, count=1):
    """Place a limit order."""
    import uuid
    path = "/trade-api/v2/portfolio/orders"
    payload = {
        "action": "buy",
        "count": count,
        "side": side,
        "ticker": ticker,
        "type": "limit",
        "yes_price": price if side == "yes" else 100 - price,
        "client_order_id": str(uuid.uuid4())
    }
    headers = get_kalshi_headers("POST", path)
    headers["Content-Type"] = "application/json"
    
    try:
        res = requests.post(BASE_URL + path, json=payload, headers=headers, timeout=5)
        return res.status_code == 201
    except:
        return False


def run():
    print("=" * 60)
    print("  GoobClaw 15-Min Arb Hunter")
    print("  Scanning EVERY SECOND for arb windows!")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)
    
    last_arbs = {}
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            markets = get_15min_markets()
            
            if not markets:
                if int(time.time()) % 10 == 0:
                    print(f"[{ts}] No 15-min markets found...")
                time.sleep(1)
                continue
            
            arbs = find_arbs(markets)
            
            if arbs:
                for arb in arbs:
                    ticker = arb["ticker"]
                    was_known = ticker in last_arbs
                    
                    # New arb or still active?
                    if not was_known:
                        print(f"\n[{ts}] 🚨 ARB FOUND: {ticker[-40:]}")
                        print(f"   YES={arb['yes_ask']} + NO={arb['no_ask']} = {arb['total']}c")
                        print(f"   💰 PROFIT: +{arb['profit']:.1f}¢ per pair!")
                    
                    last_arbs[ticker] = arb
                    
                    # Execute if auto-trade
                    if AUTO_TRADE:
                        ok1 = place_order(ticker, "yes", arb["yes_ask"])
                        ok2 = place_order(ticker, "no", arb["no_ask"])
                        if ok1 and ok2:
                            print(f"   ✅ BOTH ORDERS PLACED!")
                        else:
                            print(f"   ❌ Order failed")
            
            # Clean old arbs
            for ticker in list(last_arbs.keys()):
                if ticker not in [a["ticker"] for a in arbs]:
                    del last_arbs[ticker]
            
            # Quiet output during scan
            if int(time.time()) % 5 == 0 and not arbs:
                print(f"[{ts}] Scanning {len(markets)} markets...", end="\r")
            
            time.sleep(1)  # SCAN EVERY SECOND!
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    run()