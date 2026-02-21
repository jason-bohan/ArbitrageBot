#!/usr/bin/env python3
"""
GoobClaw Near-Expiry Scalper
Watches 15-min BTC/ETH markets. In the last 2 minutes, if price is clearly
above/below the floor_strike (opening price), buys the winning side.
Uses CoinGecko for live price. Resolves = free money.
"""

import os
import sys
import time
import uuid
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL       = "https://api.elections.kalshi.com"
COINGECKO_URL  = "https://api.coingecko.com/api/v3/simple/price"
SCALP_WINDOW   = 120      # seconds before close to enter (2 min)
MIN_EDGE_PCT   = 0.15     # price must be 0.15% above/below strike to act
MAX_CONTRACTS  = 3        # max contracts per trade
AUTO_TRADE     = os.getenv("AUTO_TRADE", "true").lower() == "true"

TELEGRAM_TOKEN = "8327315190:AAGBDny1KAk9m27YOCGmxD2ElQofliyGdLI"
JASON_CHAT_ID  = "7478453115"

SERIES = {
    "KXBTC15M": "bitcoin",
    "KXETH15M": "ethereum",
}


def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": JASON_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=8
        )
    except:
        pass


def get_live_price(coin_id):
    """Get live price from CoinGecko (free, no key needed)."""
    try:
        res = requests.get(
            COINGECKO_URL,
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=8
        )
        if res.status_code == 200:
            return res.json()[coin_id]["usd"]
    except Exception as e:
        print(f"  [CoinGecko error] {e}")
    return None


def get_active_market(series_ticker):
    """Get the currently active market for a series."""
    path = f"/trade-api/v2/markets?series_ticker={series_ticker}&status=open&limit=1"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            markets = res.json().get("markets", [])
            if markets:
                return markets[0]
    except Exception as e:
        print(f"  [market error] {series_ticker}: {e}")
    return None


def seconds_to_close(close_time_str):
    try:
        ct = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        return (ct - datetime.now(timezone.utc)).total_seconds()
    except:
        return None


def place_order(ticker, side, price_cents, count=1):
    """Place a market-limit order."""
    path = "/trade-api/v2/portfolio/orders"
    payload = {
        "action": "buy",
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
        if res.status_code == 201:
            return True, res.json()
        else:
            return False, res.text
    except Exception as e:
        return False, str(e)


def get_balance():
    path = "/trade-api/v2/portfolio/balance"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except:
        pass
    return None


def evaluate_trade(market, live_price):
    """
    Decide whether to trade and which side.
    Returns: (side, price_cents, edge_pct) or None
    """
    floor_strike = market.get("floor_strike")
    if not floor_strike or not live_price:
        return None

    edge_pct = (live_price - floor_strike) / floor_strike * 100

    if edge_pct >= MIN_EDGE_PCT:
        # Price clearly above opening price → YES wins
        yes_ask = market.get("yes_ask", 0)
        if yes_ask > 0 and yes_ask < 97:  # don't overpay
            return ("yes", yes_ask, edge_pct)

    elif edge_pct <= -MIN_EDGE_PCT:
        # Price clearly below opening price → NO wins
        no_ask = market.get("no_ask", 0)
        if no_ask > 0 and no_ask < 97:
            return ("no", no_ask, edge_pct)

    return None


def scan_loop():
    print("=" * 60)
    print("  GoobClaw Near-Expiry Scalper")
    print(f"  Scalp window: last {SCALP_WINDOW//60} min | Edge: >{MIN_EDGE_PCT}%")
    print(f"  Auto-trade: {AUTO_TRADE} | Max contracts: {MAX_CONTRACTS}")
    print("=" * 60)

    tg("🔪 *Scalper online* — watching last 2 min of each 15-min BTC/ETH market.")

    traded_tickers = set()  # don't double-trade the same market
    last_status = 0

    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            now_epoch = time.time()

            for series, coin_id in SERIES.items():
                market = get_active_market(series)
                if not market:
                    continue

                ticker = market["ticker"]
                close_time = market.get("close_time", "")
                secs_left = seconds_to_close(close_time)

                if secs_left is None:
                    continue

                mins_left = secs_left / 60

                # Print status every 2 minutes
                if now_epoch - last_status > 120:
                    floor = market.get("floor_strike", "?")
                    ya = market.get("yes_ask", "?")
                    na = market.get("no_ask", "?")
                    print(f"[{ts}] {series} | strike=${floor:,.2f} | yes={ya}¢ no={na}¢ | {mins_left:.1f}min left")

                # Are we in the scalp window?
                if 0 < secs_left <= SCALP_WINDOW and ticker not in traded_tickers:
                    live_price = get_live_price(coin_id)
                    if not live_price:
                        continue

                    floor_strike = market.get("floor_strike", 0)
                    edge_pct = (live_price - floor_strike) / floor_strike * 100 if floor_strike else 0

                    print(f"\n[{ts}] 🎯 SCALP WINDOW: {ticker}")
                    print(f"       Live: ${live_price:,.2f} | Strike: ${floor_strike:,.2f} | Edge: {edge_pct:+.2f}%")
                    print(f"       Time left: {secs_left:.0f}s")

                    trade = evaluate_trade(market, live_price)

                    if trade:
                        side, price_cents, edge = trade
                        profit_per = (100 - price_cents) / 100
                        contracts = min(MAX_CONTRACTS, max(1, int(get_balance() or 1)))

                        print(f"       ✅ Trade signal: BUY {side.upper()} @ {price_cents}¢ | profit/contract: ${profit_per:.2f}")

                        msg = (
                            f"🔪 *Scalp signal!*\n"
                            f"`{ticker}`\n"
                            f"Live: ${live_price:,.2f} | Strike: ${floor_strike:,.2f}\n"
                            f"Edge: {edge:+.2f}% | Buy {side.upper()} @ {price_cents}¢\n"
                            f"Profit if wins: ${profit_per*contracts:.2f} ({contracts} contracts)"
                        )

                        if AUTO_TRADE:
                            ok, result = place_order(ticker, side, price_cents, count=contracts)
                            if ok:
                                print(f"       🚀 ORDER PLACED: {contracts}x {side.upper()}")
                                tg(msg + f"\n✅ *Order placed!*")
                            else:
                                print(f"       ❌ Order failed: {result}")
                                tg(msg + f"\n❌ Order failed: {result}")
                        else:
                            print(f"       (AUTO_TRADE off — would have traded)")
                            tg(msg + "\n_(auto-trade off)_")

                        traded_tickers.add(ticker)

                    else:
                        edge_str = f"{edge_pct:+.2f}%"
                        print(f"       ⏳ No clear edge yet ({edge_str}) — watching...")

            if now_epoch - last_status > 120:
                last_status = now_epoch

            time.sleep(10)

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"[{ts}] Error: {e}")
            time.sleep(15)


if __name__ == "__main__":
    scan_loop()
