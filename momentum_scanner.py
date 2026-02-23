#!/usr/bin/env python3
"""
GoobClaw Momentum Scanner — Catches last-minute squeezes
Watches markets closing in 1-10 min for:
1. OBI (Order Book Imbalance) shifts
2. Spread narrowing
3. Price acceleration
4. Volume spikes
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"

# === MOMENTUM PARAMETERS ===
MIN_SECS_LEFT = 60    # 1 min
MAX_SECS_LEFT = 600   # 10 min
MIN_VOLUME = 5000     # Skip illiquid
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"


def get_orderbook(ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("orderbook", {})
    except:
        pass
    return {}


def calculate_obi(orderbook, depth=5):
    """Order Book Imbalance — positive = buy pressure, negative = sell pressure."""
    yes_bids = orderbook.get("yes", [])
    no_bids = orderbook.get("no", [])
    
    if not yes_bids or not no_bids:
        return 0
    
    def get_vol(bids):
        best = bids[-1][0] if bids else 0
        return sum(vol for price, vol in bids if price >= best - depth)
    
    v_yes = get_vol(yes_bids)
    v_no = get_vol(no_bids)
    
    if v_yes + v_no == 0:
        return 0
    
    return (v_yes - v_no) / (v_yes + v_no)


def get_spread(market):
    """Get bid-ask spread for both sides."""
    ya = market.get("yes_ask", 0)
    yb = market.get("yes_bid", 0)
    na = market.get("no_ask", 0)
    nb = market.get("no_bid", 0)
    
    yes_spread = ya - yb if ya and yb else 999
    no_spread = na - nb if na and nb else 999
    
    return yes_spread, no_spread


def scan_for_momentum():
    """Scan markets for momentum signals."""
    now = datetime.now(timezone.utc)
    path = f"/trade-api/v2/markets?status=open&min_close_ts={int(now.timestamp()+MIN_SECS_LEFT)}&max_close_ts={int(now.timestamp()+MAX_SECS_LEFT)}&limit=100"
    
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=15)
        if res.status_code != 200:
            return []
        markets = res.json().get("markets", [])
    except Exception as e:
        print(f"Scan error: {e}")
        return []
    
    opportunities = []
    
    for m in markets:
        ticker = m.get("ticker", "")
        
        # Skip settled
        ya = m.get("yes_ask", 0)
        na = m.get("no_ask", 0)
        if ya == 0 or na == 0 or ya >= 95 or na >= 95:
            continue
        
        # Skip illiquid
        vol = m.get("volume", 0)
        if vol < MIN_VOLUME:
            continue
        
        # Get orderbook for OBI
        ob = get_orderbook(ticker)
        obi = calculate_obi(ob)
        
        # Get spreads
        yes_spread, no_spread = get_spread(m)
        
        # Calculate time left
        try:
            close = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
            secs_left = (close - datetime.now(timezone.utc)).total_seconds()
            mins_left = secs_left / 60
        except:
            continue
        
        # === MOMENTUM SIGNALS ===
        
        score = 0
        signals = []
        
        # 1. STRONG OBI — order book one-sided
        if abs(obi) >= 0.5:
            score += 3
            signals.append(f"OBI={obi:+.1f}")
        
        # 2. TIGHT SPREAD — liquid market
        if yes_spread <= 2 or no_spread <= 2:
            score += 2
            signals.append(f"spread={min(yes_spread, no_spread)}c")
        
        # 3. EXTREME PRICE — either side very cheap
        if ya <= 15:  # YES very cheap
            score += 2
            signals.append(f"YES={ya}c (cheap)")
        if na <= 15:  # NO very cheap
            score += 2
            signals.append(f"NO={na}c (cheap)")
        
        # 4. TIME PRESSURE — about to close
        if mins_left <= 3:
            score += 2
            signals.append(f"{mins_left:.0f}min left")
        
        # 5. ARBITRAGE EDGE — YES+NO < 100
        total = ya + na
        if total < 99:
            score += 5
            signals.append(f"ARB={total}c")
        
        if score >= 3:
            opportunities.append({
                "ticker": ticker,
                "score": score,
                "signals": signals,
                "yes_ask": ya,
                "no_ask": na,
                "yes_spread": yes_spread,
                "no_spread": no_spread,
                "obi": obi,
                "mins_left": mins_left,
                "volume": vol
            })
    
    return opportunities


def run():
    print("=" * 60)
    print("  GoobClaw Momentum Scanner")
    print(f"  Watching markets closing in {MIN_SECS_LEFT//60}-{MAX_SECS_LEFT//60} min")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)
    
    last_opps = []
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            opps = scan_for_momentum()
            
            if opps:
                opps = sorted(opps, key=lambda x: x["score"], reverse=True)
                
                # New opportunities?
                new_opps = [o for o in opps if o["ticker"] not in [x["ticker"] for x in last_opps]]
                
                if new_opps:
                    print(f"\n[{ts}] 🚨 NEW MOMENTUM SIGNALS ({len(opps)} total):")
                    for o in new_opps[:5]:
                        print(f"  🎯 {o['ticker'][-35:]}")
                        print(f"     Score: {o['score']} | {' | '.join(o['signals'])}")
                        print(f"     YES={o['yes_ask']} NO={o['no_ask']} | {o['mins_left']:.0f}min left")
                
                last_opps = opps
            else:
                if int(time.time()) % 30 == 0:
                    print(f"[{ts}] Scanning... (no momentum signals)")
            
            time.sleep(10)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
