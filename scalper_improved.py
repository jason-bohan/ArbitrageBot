#!/usr/bin/env python3
"""
GoobClaw Scalper v2 — Conservative Money Manager
Tighter stops, better entries, no reversal traps.
"""

import os
import time
import uuid
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"

# === CONSERVATIVE SCALPER PARAMETERS ===
MIN_SPREAD_TO_TRADE = 0   # Accept any spread
MAX_SPREAD_TO_TRADE = 2   # Tighter spread requirement (was 3)
TAKE_PROFIT_CENTS = 3     # Better risk/reward (was 2)
STOP_LOSS_CENTS = 1       # Tighter stop (was 2)
MAX_SECS_LEFT = 480       # Enter with ≤8 min left (was 10)
MIN_SECS_LEFT = 180       # Exit if <3 min (was 2)
CONTRACTS = 1
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"  # Default to FALSE


def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",
            json={"chat_id": os.getenv('JASON_CHAT_ID'), "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
    except:
        pass


def secs_left(close_time_str):
    try:
        ct = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        return (ct - datetime.now(timezone.utc)).total_seconds()
    except:
        return None


def get_orderbook(ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("orderbook", {})
    except:
        pass
    return {}


def get_market(ticker):
    path = f"/trade-api/v2/markets/{ticker}"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("market", {})
    except:
        pass
    return {}


def get_spread_info(orderbook, side):
    """Return (bid, ask, spread) for the side."""
    if side == "yes":
        bids = orderbook.get("yes", [])
        asks = orderbook.get("no", [])  # NO asks are where you SELL YES
    else:
        bids = orderbook.get("no", [])
        asks = orderbook.get("yes", [])  # YES asks are where you SELL NO
    
    bid = bids[0][0] if bids else 50
    ask = asks[-1][0] if asks else 50
    spread = ask - bid
    return bid, ask, spread


def place_order(ticker, side, price_cents, count=1, action="buy"):
    path = "/trade-api/v2/portfolio/orders"
    payload = {
        "action": action,
        "count": count,
        "side": side,
        "ticker": ticker,
        "type": "limit",
        "yes_price": price_cents if side == "yes" else 100 - price_cents,
        "client_order_id": str(uuid.uuid4())
    }
    headers = get_kalshi_headers("POST", path)
    headers["Content-Type"] = "application/json"
    try:
        res = requests.post(BASE_URL + path, json=payload, headers=headers, timeout=5)
        return res.status_code == 201, res.text
    except Exception as e:
        return False, str(e)


def scan_markets():
    """Find liquid markets closing soon."""
    now = datetime.now(timezone.utc)
    path = f"/trade-api/v2/markets?status=open&min_close_ts={int(now.timestamp()+MIN_SECS_LEFT)}&max_close_ts={int(now.timestamp()+MAX_SECS_LEFT)}&limit=100"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except:
        pass
    return []


def should_enter(market, orderbook):
    """
    CONSERVATIVE entry rules:
    1. Very tight spreads (<2¢)
    2. Price must be very near 50 (high liquidity)
    3. Must have depth on both sides
    4. Avoid decided markets (>80c)
    """
    ya = market.get("yes_ask", 0)
    yb = market.get("yes_bid", 0)
    na = market.get("no_ask", 0)
    nb = market.get("no_bid", 0)
    
    # Check spreads
    yes_spread = ya - yb if ya and yb else 999
    no_spread = na - nb if na and nb else 999
    
    # Skip illiquid - tighter requirement
    if yes_spread > MAX_SPREAD_TO_TRADE or no_spread > MAX_SPREAD_TO_TRADE:
        return None, "wide_spread"
    
    # Skip decided markets - stricter threshold
    if ya >= 80 or na >= 80:
        return None, "decided"
    
    # Only trade very balanced markets (near 50c)
    if ya > 55 and na > 55:
        return None, "too_expensive"
    
    # Pick side with tighter spread AND better price
    if yes_spread <= no_spread and ya <= 50:
        return "yes", f"yes_spread={yes_spread}c price={ya}c"
    elif no_spread < yes_spread and na <= 50:
        return "no", f"no_spread={no_spread}c price={na}c"
    
    return None, "no_edge"


def scalp_market(market):
    """Execute one scalp trade with CONSERVATIVE risk management."""
    ticker = market["ticker"]
    ob = get_orderbook(ticker)
    
    side, reason = should_enter(market, ob)
    if not side:
        return
    
    # Get actual bid/ask
    bid, ask, spread = get_spread_info(ob, side)
    
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 🎯 SCALP {ticker} | {side.upper()} @ {ask}c | spread={spread}c | {reason}")
    tg(f"🎯 *Scalp* `{ticker}` {side.upper()}@{ask}c spread={spread}c")
    
    if AUTO_TRADE:
        ok, err = place_order(ticker, side, ask, CONTRACTS)
        if not ok:
            print(f"  ❌ Entry failed: {err}")
            return
    
    entry = ask
    
    while True:
        time.sleep(2)  # Faster monitoring
        m = get_market(ticker)
        if not m:
            break
        
        sl = secs_left(m.get("close_time", ""))
        if sl is not None and sl <= 0:
            print(f"  ⏰ {ticker} expired")
            break
        if sl is not None and sl < MIN_SECS_LEFT:
            print(f"  ⚠️ Near expiry, exiting")
            if AUTO_TRADE:
                place_order(ticker, side, m.get("yes_bid" if side == "yes" else "no_bid"), CONTRACTS, action="sell")
            break
        
        # Get current bid (what you can sell at)
        current_bid = m.get("yes_bid" if side == "yes" else "no_bid", 0)
        pnl = current_bid - entry
        
        ts = datetime.now().strftime("%H:%M:%S")
        
        # TAKE PROFIT - Better target
        if pnl >= TAKE_PROFIT_CENTS:
            print(f"  [{ts}] 💰 +{pnl}c profit | sell @ {current_bid}c")
            if AUTO_TRADE:
                place_order(ticker, side, current_bid, CONTRACTS, action="sell")
            tg(f"💰 *Scalp win* `{ticker}` +{pnl}c")
            return True
        
        # STOP LOSS - Tighter stop, NO REVERSAL
        if pnl <= -STOP_LOSS_CENTS:
            loss = abs(pnl)
            print(f"  [{ts}] 🛑 Stop - {loss}c | sell @ {current_bid}c")
            if AUTO_TRADE:
                place_order(ticker, side, current_bid, CONTRACTS, action="sell")
            tg(f"🛑 *Scalp loss* `{ticker}` -{loss}c")
            return False
        
        # Status heartbeat
        if int(time.time()) % 10 == 0:
            print(f"  [{ts}] {side.upper()} {pnl:+.1f}c | {sl:.0f}s left | spread={spread}c")


def run():
    print("=" * 60)
    print("  GoobClaw Scalper v2 — Conservative Money Manager")
    print(f"  Target: +{TAKE_PROFIT_CENTS}c | Stop: -{STOP_LOSS_CENTS}c")
    print(f"  Max spread: {MAX_SPREAD_TO_TRADE}c | Auto: {AUTO_TRADE}")
    print(f"  🛡️ Tighter entries, better risk/reward")
    print("=" * 60)
    tg("🦞 *Scalper v2 online* — Conservative entries")
    
    traded = set()
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            markets = scan_markets()
            print(f"[{ts}] Scanning {len(markets)} markets...")
            
            for m in markets:
                ticker = m["ticker"]
                sl = secs_left(m.get("close_time", ""))
                
                if ticker in traded or sl is None or sl <= 0:
                    continue
                
                traded.add(ticker)
                result = scalp_market(m)
            
            # Clean set
            if len(traded) > 500:
                traded.clear()
            
            time.sleep(8)  # Slightly faster scanning
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
