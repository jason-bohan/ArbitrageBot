#!/usr/bin/env python3
"""
GoobClaw Flipper v2 — OBI-enhanced ratchet scalper
Uses Order Book Imbalance to pick direction, -2c stop/flip, +3c target.
Also sweeps all markets closing in next 2 min (not just ETH/BTC).
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
STOP_LOSS_CENTS   = 2
TAKE_PROFIT_CENTS = 3
MAX_ENTRY_PRICE   = 75   # don't enter if side already > 75c
MIN_SECS_LEFT     = 120  # scalp window: last 2 min
MAX_SECS_LEFT     = 780  # flipper entry: up to 13 min before close
CONTRACTS         = 1
AUTO_TRADE        = os.getenv("AUTO_TRADE", "true").lower() == "true"
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


def get_balance():
    path = "/trade-api/v2/portfolio/balance"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except:
        pass
    return None


def get_markets_closing_soon(within_secs=780):
    """Get all open markets closing within N seconds."""
    now = datetime.now(timezone.utc)
    max_close = (now + timedelta(seconds=within_secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
    min_close = (now + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = f"/trade-api/v2/markets?status=open&min_close_ts={int(now.timestamp()+10)}&max_close_ts={int((now + timedelta(seconds=within_secs)).timestamp())}&limit=50"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except:
        pass
    return []


def get_orderbook(ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=8)
        if res.status_code == 200:
            return res.json().get("orderbook", {})
    except:
        pass
    return {}


def calculate_obi(orderbook, depth=5):
    """Order Book Imbalance. Positive = YES-heavy (buy YES). Negative = NO-heavy (buy NO)."""
    yes_bids = orderbook.get("yes") or []
    no_bids  = orderbook.get("no")  or []

    def get_vol(bids):
        if not bids:
            return 0
        best = bids[-1][0]
        return sum(vol for price, vol in bids if price >= best - depth)

    v_yes = get_vol(yes_bids)
    v_no  = get_vol(no_bids)
    if v_yes + v_no == 0:
        return 0
    return (v_yes - v_no) / (v_yes + v_no)


def get_live_price(coin_id):
    try:
        res = requests.get(
            COINGECKO_URL,
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=8
        )
        if res.status_code == 200:
            return res.json()[coin_id]["usd"]
    except:
        pass
    return None


def pick_side(market, orderbook):
    """
    Pick YES or NO using OBI as primary signal.
    Falls back to floor_strike vs live price for BTC/ETH markets.
    Returns (side, entry_price_cents, confidence_str)
    """
    obi = calculate_obi(orderbook)
    series = market["ticker"].split("-")[0]

    # OBI signal
    if abs(obi) >= 0.15:
        side = "yes" if obi > 0 else "no"
        price = market.get("yes_ask" if side == "yes" else "no_ask", 50)
        return side, price, f"OBI={obi:+.2f}"

    # Fallback: CoinGecko for crypto markets
    coin = COIN_MAP.get(series)
    if coin:
        live = get_live_price(coin)
        floor = market.get("floor_strike", 0)
        if live and floor:
            edge_pct = (live - floor) / floor * 100
            if abs(edge_pct) >= 0.10:
                side = "yes" if live >= floor else "no"
                price = market.get("yes_ask" if side == "yes" else "no_ask", 50)
                return side, price, f"price_edge={edge_pct:+.2f}%"

    return None, None, "no_signal"


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
        res = requests.post(BASE_URL + path, json=payload, headers=headers, timeout=10)
        return res.status_code == 201, res.text if res.status_code != 201 else "ok"
    except Exception as e:
        return False, str(e)


def refresh_market(ticker):
    path = f"/trade-api/v2/markets/{ticker}"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=8)
        if res.status_code == 200:
            return res.json().get("market", {})
    except:
        pass
    return {}


def trade_market(market):
    """Enter and manage one market with flip logic."""
    ticker = market["ticker"]
    ob = get_orderbook(ticker)
    side, entry_price, signal = pick_side(market, ob)

    if not side:
        return
    if entry_price > MAX_ENTRY_PRICE:
        print(f"  Skip {ticker}: {side.upper()} @ {entry_price}c too expensive")
        return

    sl = secs_left(market["close_time"])
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 🎯 {ticker} | {side.upper()} @ {entry_price}c | {signal} | {sl:.0f}s left")

    if AUTO_TRADE:
        ok, err = place_order(ticker, side, entry_price, CONTRACTS)
        if not ok:
            print(f"  ❌ Entry failed: {err}")
            return

    tg(f"🎯 *Flipper entered* `{ticker}`\n{side.upper()} @ {entry_price}c | {signal} | {sl:.0f}s left")

    entry = entry_price
    total_loss = 0
    flips = 0

    while True:
        time.sleep(4)
        m = refresh_market(ticker)
        if not m:
            break

        sl = secs_left(m.get("close_time", ""))
        if sl is not None and sl <= 0:
            print(f"  ⏰ {ticker} expired. Flips: {flips}, base loss: {total_loss}c")
            tg(f"⏰ `{ticker}` expired | Flips: {flips} | Base loss: {total_loss}c")
            break

        bid = m.get("yes_bid" if side == "yes" else "no_bid", 0)
        pnl = bid - entry
        ts  = datetime.now().strftime("%H:%M:%S")

        if pnl >= TAKE_PROFIT_CENTS:
            print(f"  [{ts}] 💰 Take profit +{pnl}c | sell {side.upper()} @ {bid}c")
            if AUTO_TRADE:
                place_order(ticker, side, bid, CONTRACTS, action="sell")
            net = pnl - total_loss
            tg(f"💰 *Profit!* `{ticker}` +{pnl}c this leg | Net: {net:+}c")
            break

        if pnl <= -STOP_LOSS_CENTS:
            loss = entry - bid
            total_loss += loss
            flips += 1
            new_side = "no" if side == "yes" else "yes"
            new_price = m.get("yes_ask" if new_side == "yes" else "no_ask", 50)

            print(f"  [{ts}] 🔄 Flip #{flips} | -{loss}c | → {new_side.upper()} @ {new_price}c | total loss: {total_loss}c")

            if AUTO_TRADE:
                place_order(ticker, side, bid, CONTRACTS, action="sell")
                time.sleep(1)
                ok, err = place_order(ticker, new_side, new_price, CONTRACTS)
                if not ok:
                    print(f"  ❌ Flip failed: {err}")
                    tg(f"❌ Flip failed `{ticker}`: {err}")
                    break

            tg(f"🔄 *Flip #{flips}* `{ticker}` | -{loss}c | → {new_side.upper()} @ {new_price}c")
            side  = new_side
            entry = new_price
        else:
            if int(time.time()) % 20 == 0:
                print(f"  [{ts}] {side.upper()} {pnl:+}c | {sl:.0f}s left")


def run():
    print("=" * 60)
    print("  GoobClaw Flipper v2 — OBI + Ratchet")
    print(f"  Stop: -{STOP_LOSS_CENTS}c | Target: +{TAKE_PROFIT_CENTS}c")
    print(f"  Sweeps ALL markets closing in <{MAX_SECS_LEFT//60} min")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)
    tg("🦞 *Flipper v2 online* — OBI signal + sweeping all closing-soon markets")

    traded = set()

    while True:
        try:
            markets = get_markets_closing_soon(MAX_SECS_LEFT)
            ts = datetime.now().strftime("%H:%M:%S")

            for m in markets:
                ticker = m["ticker"]
                sl = secs_left(m.get("close_time", ""))
                if sl is None or sl <= 0:
                    continue
                if ticker in traded:
                    continue

                ya = m.get("yes_ask", 0)
                na = m.get("no_ask", 0)

                # Skip markets already decided — both sides should be live
                if ya >= 95 or na >= 95 or ya == 0 or na == 0:
                    continue
                # Skip if neither side is a reasonable entry
                if min(ya, na) > MAX_ENTRY_PRICE:
                    continue

                # Mark as seen so we don't double-enter
                traded.add(ticker)
                trade_market(m)

            # Clean old tickers from traded set every cycle
            if len(traded) > 200:
                traded.clear()

            time.sleep(15)

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(15)


if __name__ == "__main__":
    run()
