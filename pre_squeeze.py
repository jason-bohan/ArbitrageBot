#!/usr/bin/env python3
"""
GoobClaw Pre-Squeeze Detector — Catches momentum BEFORE it happens
Watches:
1. Order book depth changes (accumulation)
2. OBI shifts (sentiment change)
3. Spread compression (liquidity squeeze)
4. Crypto price spikes (underlying move)
"""

import os
import time
import requests
from datetime import datetime, timezone
from collections import deque
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# === PARAMETERS ===
MIN_SECS_LEFT = 60    # 1 min
MAX_SECS_LEFT = 600   # 10 min
MIN_VOLUME = 5000
HISTORY_SIZE = 5      # Track last 5 scans for changes


def get_orderbook(ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("orderbook", {})
    except:
        pass
    return {}


def get_crypto_prices():
    """Get BTC/ETH prices to detect underlying moves."""
    try:
        res = requests.get(
            COINGECKO_URL,
            params={"ids": "bitcoin,ethereum", "vs_currencies": "usd"},
            timeout=5
        )
        if res.status_code == 200:
            return res.json()
    except:
        pass
    return {}


def analyze_orderbook(orderbook, side="yes"):
    """Extract depth metrics from orderbook."""
    bids = orderbook.get(side, [])
    if not bids:
        return {"total_vol": 0, "best_bid": 0, "depth_5": 0, "depth_10": 0}
    
    total_vol = sum(vol for _, vol in bids)
    best_bid = bids[0][0] if bids else 0
    
    # Depth at different levels
    best = best_bid
    depth_5 = sum(vol for price, vol in bids if price >= best - 5)
    depth_10 = sum(vol for price, vol in bids if price >= best - 10)
    
    return {
        "total_vol": total_vol,
        "best_bid": best_bid,
        "depth_5": depth_5,
        "depth_10": depth_10
    }


def calculate_obi(orderbook):
    """Order Book Imbalance."""
    yes_bids = orderbook.get("yes", [])
    no_bids = orderbook.get("no", [])
    
    def get_vol(bids, depth=10):
        if not bids:
            return 0
        best = bids[-1][0]
        return sum(vol for price, vol in bids if price >= best - depth)
    
    v_yes = get_vol(yes_bids)
    v_no = get_vol(no_bids)
    
    if v_yes + v_no == 0:
        return 0
    
    return (v_yes - v_no) / (v_yes + v_no)


class MarketTracker:
    """Tracks market state over time to detect changes."""
    
    def __init__(self):
        self.history = {}  # ticker -> deque of snapshots
    
    def snapshot(self, ticker, market, orderbook, crypto_prices):
        """Take a snapshot of current state."""
        ya = market.get("yes_ask", 0)
        yb = market.get("yes_bid", 0)
        na = market.get("no_ask", 0)
        nb = market.get("no_bid", 0)
        
        yes_depth = analyze_orderbook(orderbook, "yes")
        no_depth = analyze_orderbook(orderbook, "no")
        
        obi = calculate_obi(orderbook)
        
        # Time left
        try:
            close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
            secs_left = (close - datetime.now(timezone.utc)).total_seconds()
        except:
            secs_left = 999
        
        snapshot = {
            "ts": time.time(),
            "yes_ask": ya,
            "yes_bid": yb,
            "no_ask": na,
            "no_bid": nb,
            "yes_depth": yes_depth,
            "no_depth": no_depth,
            "obi": obi,
            "secs_left": secs_left,
            "volume": market.get("volume", 0),
            "btc_price": crypto_prices.get("bitcoin", {}).get("usd", 0),
            "eth_price": crypto_prices.get("ethereum", {}).get("usd", 0)
        }
        
        if ticker not in self.history:
            self.history[ticker] = deque(maxlen=HISTORY_SIZE)
        
        self.history[ticker].append(snapshot)
        return snapshot
    
    def detect_momentum(self, ticker):
        """Analyze history to detect pre-squeeze patterns."""
        if ticker not in self.history:
            return None
        
        hist = self.history[ticker]
        if len(hist) < 2:
            return None
        
        current = hist[-1]
        previous = hist[-2]
        
        # Need recent data (within 30 seconds)
        if current["ts"] - previous["ts"] > 30:
            return None
        
        signals = []
        score = 0
        
        # === 1. OBI SHIFT — sentiment change ===
        obi_change = current["obi"] - previous["obi"]
        if abs(obi_change) >= 0.2:
            score += 3
            direction = "YES" if obi_change > 0 else "NO"
            signals.append(f"OBI shift: {previous['obi']:.2f}→{current['obi']:.2f} ({direction})")
        
        # === 2. DEPTH ACCUMULATION — big money positioning ===
        yes_depth_change = current["yes_depth"]["depth_5"] / max(previous["yes_depth"]["depth_5"], 1)
        no_depth_change = current["no_depth"]["depth_5"] / max(previous["no_depth"]["depth_5"], 1)
        
        if yes_depth_change >= 1.5:
            score += 3
            signals.append(f"YES depth +{yes_depth_change:.0%}")
        if no_depth_change >= 1.5:
            score += 3
            signals.append(f"NO depth +{no_depth_change:.0%}")
        
        # === 3. SPREAD COMPRESSION — liquidity squeeze ===
        current_spread = (current["yes_ask"] - current["yes_bid"])
        previous_spread = (previous["yes_ask"] - previous["yes_bid"])
        
        if current_spread <= 2 and previous_spread > current_spread:
            score += 2
            signals.append(f"Spread: {previous_spread}→{current_spread}c")
        
        # === 4. CRYPTO MOVE — underlying catalyst ===
        btc_change = (current["btc_price"] - previous["btc_price"]) / max(previous["btc_price"], 1) * 100
        eth_change = (current["eth_price"] - previous["eth_price"]) / max(previous["eth_price"], 1) * 100
        
        if abs(btc_change) >= 1:
            score += 2
            signals.append(f"BTC {btc_change:+.1f}%")
        if abs(eth_change) >= 1:
            score += 2
            signals.append(f"ETH {eth_change:+.1f}%")
        
        # === 5. PRICE ACCELERATION ===
        yes_move = current["yes_ask"] - previous["yes_ask"]
        no_move = current["no_ask"] - previous["no_ask"]
        
        if abs(yes_move) >= 3 or abs(no_move) >= 3:
            score += 2
            signals.append(f"Price move: {yes_move:+.0f}/{no_move:+.0f}")
        
        # === 6. TIME PRESSURE ===
        if current["secs_left"] < 180:  # < 3 min
            score += 1
            signals.append(f"{current['secs_left']:.0f}s left")
        
        if score >= 4:
            return {
                "score": score,
                "signals": signals,
                "current": current,
                "previous": previous
            }
        
        return None


def scan_markets():
    """Get markets closing soon."""
    now = datetime.now(timezone.utc)
    path = f"/trade-api/v2/markets?status=open&min_close_ts={int(now.timestamp()+MIN_SECS_LEFT)}&max_close_ts={int(now.timestamp()+MAX_SECS_LEFT)}&limit=100"
    
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=15)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except:
        pass
    return []


def run():
    print("=" * 60)
    print("  GoobClaw PRE-SQUEEZE Detector")
    print("  Watching for order book accumulation BEFORE the move")
    print("=" * 60)
    
    tracker = MarketTracker()
    last_alerts = set()
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            
            # Get crypto prices
            crypto_prices = get_crypto_prices()
            
            # Scan markets
            markets = scan_markets()
            
            # Take snapshots
            for m in markets:
                ticker = m.get("ticker", "")
                
                # Skip settled
                ya = m.get("yes_ask", 0)
                na = m.get("no_ask", 0)
                if ya == 0 or na == 0 or ya >= 95 or na >= 95:
                    continue
                
                # Skip illiquid
                if m.get("volume", 0) < MIN_VOLUME:
                    continue
                
                # Get orderbook
                ob = get_orderbook(ticker)
                
                # Snapshot
                tracker.snapshot(ticker, m, ob, crypto_prices)
                
                # Check for momentum
                momentum = tracker.detect_momentum(ticker)
                
                if momentum and ticker not in last_alerts:
                    print(f"\n[{ts}] 🚨 PRE-SQUEEZE DETECTED: {ticker[-40:]}")
                    print(f"   Score: {momentum['score']} | {' | '.join(momentum['signals'])}")
                    print(f"   YA={momentum['current']['yes_ask']} YB={momentum['current']['yes_bid']} | NA={momentum['current']['no_ask']} NB={momentum['current']['no_bid']}")
                    print(f"   Time left: {momentum['current']['secs_left']:.0f}s")
                    
                    last_alerts.add(ticker)
            
            # Clear old alerts
            if len(last_alerts) > 20:
                last_alerts.clear()
            
            if int(time.time()) % 20 == 0:
                print(f"[{ts}] Scanning {len(markets)} markets...")
            
            time.sleep(10)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
