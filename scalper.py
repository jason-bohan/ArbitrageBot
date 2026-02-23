#!/usr/bin/env python3
"""
GoobClaw Scalper v1 — Tight spread scalper
Only trades liquid markets, 1-2¢ targets, quick exits.
No reversal traps.
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

# === SCALPER PARAMETERS ===
MIN_SPREAD_TO_TRADE = 0   # Accept any spread
MAX_SPREAD_TO_TRADE = 3   # Skip if spread > 3¢
TAKE_PROFIT_CENTS = 2     # Tight 2¢ target
STOP_LOSS_CENTS = 2       # Tight 2¢ stop
MAX_SECS_LEFT = 600       # Enter with ≤10 min left
MIN_SECS_LEFT = 120       # Exit if <2 min
CONTRACTS = 1
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"


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
    """Find liquid markets — widened time window."""
    now = datetime.now(timezone.utc)
    # Look for markets closing in 1-30 minutes (was 2-10 min)
    min_secs = 60   # 1 min
    max_secs = 1800  # 30 min
    path = f"/trade-api/v2/markets?status=open&min_close_ts={int(now.timestamp()+min_secs)}&max_close_ts={int(now.timestamp()+max_secs)}&limit=100"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except:
        pass
    return []


def should_enter(market, orderbook):
    """
    Scalper entry rules:
    1. Spread must be tight (<3¢)
    2. Price must be near 50 (liquid)
    3. Both sides must have depth
    """
    ya = market.get("yes_ask", 0)
    yb = market.get("yes_bid", 0)
    na = market.get("no_ask", 0)
    nb = market.get("no_bid", 0)
    
    # Check spreads
    yes_spread = ya - yb if ya and yb else 999
    no_spread = na - nb if na and nb else 999
    
    # Skip illiquid
    if yes_spread > MAX_SPREAD_TO_TRADE or no_spread > MAX_SPREAD_TO_TRADE:
        return None, "wide_spread"
    
    # Skip decided markets
    if ya >= 90 or na >= 90:
        return None, "decided"
    
    # Pick side with tighter spread and better price
    if yes_spread <= no_spread and ya <= 60:
        return "yes", f"yes_spread={yes_spread}c"
    elif no_spread < yes_spread and na <= 60:
        return "no", f"no_spread={no_spread}c"
    
    return None, "no_edge"


def scalp_market(market):
    """Execute one scalp trade with tight risk management."""
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
    flips = 0
    
    while True:
        time.sleep(3)
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
        
        # TAKE PROFIT
        if pnl >= TAKE_PROFIT_CENTS:
            print(f"  [{ts}] 💰 +{pnl}c profit | sell @ {current_bid}c")
            if AUTO_TRADE:
                place_order(ticker, side, current_bid, CONTRACTS, action="sell")
            tg(f"💰 *Scalp win* `{ticker}` +{pnl}c")
            return True
        
        # STOP LOSS — NO REVERSAL, JUST EXIT
        if pnl <= -STOP_LOSS_CENTS:
            loss = abs(pnl)
            print(f"  [{ts}] 🛑 Stop - {loss}c | sell @ {current_bid}c")
            if AUTO_TRADE:
                place_order(ticker, side, current_bid, CONTRACTS, action="sell")
            tg(f"🛑 *Scalp loss* `{ticker}` -{loss}c")
            return False
        
        # Status heartbeat
        if int(time.time()) % 15 == 0:
            print(f"  [{ts}] {side.upper()} {pnl:+.1f}c | {sl:.0f}s left | spread={spread}c")


def run():
    print("=" * 60)
    print("  GoobClaw Scalper v1 — Tight Spread Scalper")
    print(f"  Target: +{TAKE_PROFIT_CENTS}c | Stop: -{STOP_LOSS_CENTS}c")
    print(f"  Max spread: {MAX_SPREAD_TO_TRADE}c | Auto: {AUTO_TRADE}")
    print("=" * 60)
    tg("🦞 *Scalper v1 online* — tight spreads only")
    
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
            
            time.sleep(10)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()