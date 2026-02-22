#!/usr/bin/env python3
"""
GoobClaw Flipper v3 — REVERSAL DISABLED
Same entry logic, but NO FLIPS. Cut losses immediately.
"""

import os
import time
import uuid
import requests
import numpy as np
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL          = "https://api.elections.kalshi.com"
COINGECKO_URL     = "https://api.coingecko.com/api/v3/simple/price"
STOP_LOSS_CENTS   = 2    # Tighter stop
TAKE_PROFIT_CENTS = 3    # Better risk/reward
MAX_ENTRY_PRICE   = 55   # Stricter entry price
MIN_SECS_LEFT     = 300  # NEVER enter with less than 5 min left
MAX_SECS_LEFT     = 840  # flipper entry: up to 14 min before close
# 🚨 REVERSAL DISABLED 🚨
MAX_FLIPS         = 0    # NO FLIPS - CUT LOSSES IMMEDIATELY
CONTRACTS         = 1
FORCE_ENTRY_PRICE = 55   # if either side is <= this with no signal, enter anyway
AUTO_TRADE        = os.getenv("AUTO_TRADE", "false").lower() == "true"  # 🚨 DEFAULT TO FALSE
TELEGRAM_TOKEN    = "8327315190:AAGBDny1KAk9m27YOCGmxD2ElQofliyGdLI"
JASON_CHAT_ID     = "7478453115"

COIN_MAP = {"KXBTC15M": "bitcoin", "KXETH15M": "ethereum"}


def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": JASON_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=8
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


def get_live_price(coin):
    """Get live crypto price from CoinGecko."""
    try:
        res = requests.get(f"{COINGECKO_URL}?ids={coin}&vs_currencies=usd", timeout=5)
        if res.status_code == 200:
            return res.json()[coin]["usd"]
    except:
        pass
    return None


def calculate_obi(orderbook, depth=5):
    """Order Book Imbalance. Positive = YES-heavy (buy YES). Negative = NO-heavy (buy NO)."""
    yes_bids = orderbook.get("yes") or []
    no_bids  = orderbook.get("no")  or []
    
    yes_volume = sum(q for p, q in yes_bids[:depth])
    no_volume = sum(q for p, q in no_bids[:depth])
    
    total = yes_volume + no_volume
    if total == 0:
        return 0
    
    return (yes_volume - no_volume) / total


def pick_side(market, orderbook):
    """
    Pick YES or NO using OBI as primary signal.
    Falls back to floor_strike vs live price for BTC/ETH markets.
    Returns (side, entry_price_cents, confidence_str)
    """
    obi = calculate_obi(orderbook)
    series = market["ticker"].split("-")[0]

    # OBI signal — only use if the selected side is affordable
    if abs(obi) >= 0.10:
        side = "yes" if obi > 0 else "no"
        price = market.get("yes_ask" if side == "yes" else "no_ask", 50)
        if price <= MAX_ENTRY_PRICE:
            return side, price, f"OBI={obi:+.2f}"
        # OBI side too expensive — fall through to other checks

    # Fallback: CoinGecko for crypto markets
    coin = COIN_MAP.get(series)
    if coin:
        live_price = get_live_price(coin)
        if live_price:
            floor_strike = market.get("floor_strike", 0)
            if live_price > floor_strike:
                return "yes", market.get("yes_ask", 50), f"price_above_floor({live_price})"
            else:
                return "no", market.get("no_ask", 50), f"price_below_floor({live_price})"

    # Fallback: cheapest side
    ya = market.get("yes_ask", 50)
    na = market.get("no_ask", 50)
    if ya <= na and ya <= FORCE_ENTRY_PRICE:
        return "yes", ya, "cheapest_yes"
    elif na <= FORCE_ENTRY_PRICE:
        return "no", na, "cheapest_no"
    
    return None, 50, "no_edge"


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


def trade_market(market):
    """Enter and manage one market with NO FLIPS - CUT LOSSES IMMEDIATELY."""
    ticker = market["ticker"]
    ob = get_orderbook(ticker)
    side, entry_price, signal = pick_side(market, ob)
    
    if not side:
        return
    
    sl = secs_left(market.get("close_time", ""))
    if sl is None or sl <= 0:
        return
    
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 🎯 FLIPPER {ticker} | {side.upper()} @ {entry_price}c | {signal} | {sl:.0f}s left")
    
    if AUTO_TRADE:
        ok, err = place_order(ticker, side, entry_price, CONTRACTS)
        if not ok:
            print(f"  ❌ Entry failed: {err}")
            return

    tg(f"🎯 *Flipper entered* `{ticker}`\n{side.upper()} @ {entry_price}c | {signal} | {sl:.0f}s left")

    entry = entry_price
    current_obi = calculate_obi(ob)
    total_loss = 0
    flips = 0

    while True:
        time.sleep(4)
        m = get_market(ticker)
        if not m:
            break

        sl = secs_left(m.get("close_time", ""))
        if sl is not None and sl <= 0:
            print(f"  ⏰ {ticker} expired. Flips: {flips}, base loss: {total_loss}c")
            tg(f"⏰ `{ticker}` expired | Flips: {flips} | Base loss: {total_loss}c")
            break

        bid = m.get("yes_bid" if side == "yes" else "no_bid", 0)
        pnl = bid - entry

        # TAKE PROFIT
        if pnl >= TAKE_PROFIT_CENTS:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] 💰 +{pnl}c profit | sell @ {bid}c")
            if AUTO_TRADE:
                place_order(ticker, side, bid, CONTRACTS, action="sell")
            tg(f"💰 *Flipper win* `{ticker}` +{pnl}c")
            return True

        # 🚨 STOP LOSS - NO FLIPS, JUST EXIT 🚨
        if pnl <= -STOP_LOSS_CENTS:
            loss = entry - bid
            total_loss += loss
            flips += 1

            ts = datetime.now().strftime("%H:%M:%S")
            print(f"  [{ts}] 🛑 Stop -{loss}c | SELLING IMMEDIATELY (NO REVERSAL)")
            if AUTO_TRADE:
                place_order(ticker, side, bid, CONTRACTS, action="sell")
            tg(f"🛑 *Flipper stop* `{ticker}` -{loss}c | NO REVERSAL")
            break
        else:
            if int(time.time()) % 20 == 0:
                print(f"  [{ts}] {side.upper()} {pnl:+}c | {sl:.0f}s left | OBI: {current_obi:+.2f}")


def run():
    print("=" * 60)
    print("  GoobClaw Flipper v3 — NO REVERSALS")
    print(f"  Stop: -{STOP_LOSS_CENTS}c | Target: +{TAKE_PROFIT_CENTS}c")
    print(f"  🚨 FLIPS DISABLED - CUT LOSSES IMMEDIATELY")
    print(f"  Sweeps ALL markets closing in <{MAX_SECS_LEFT//60} min")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)
    tg("🦞 *Flipper v3 online* — NO REVERSALS - Cut losses immediately")

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
                trade_market(m)
            
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
