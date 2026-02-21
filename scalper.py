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
SCALP_WINDOW      = 240   # seconds before close to enter (4 min)
MIN_EDGE_PCT      = 0.10  # price must be 0.10% above/below strike to act
HIGH_CONF_PRICE   = 85    # if a side is priced >= this, it's high-confidence
RISK_PCT          = 0.25  # risk 25% of balance on high-confidence trades
RISK_PCT_NORMAL   = 0.10  # risk 10% on normal trades
MAX_CONTRACTS     = 10    # hard cap
AUTO_TRADE        = os.getenv("AUTO_TRADE", "true").lower() == "true"

# Reversal detection: if a side drops this many cents in this many seconds → buy opposite
REVERSAL_DROP     = 10    # cents dropped triggers reversal signal
REVERSAL_WINDOW   = 45    # seconds to look back
REVERSAL_MIN_PRICE = 60   # only watch for reversals when side was at least this high

TELEGRAM_TOKEN = "8327315190:AAGBDny1KAk9m27YOCGmxD2ElQofliyGdLI"
JASON_CHAT_ID  = "7478453115"

SERIES = {
    "KXBTC15M": "bitcoin",
    "KXETH15M": "ethereum",
}

# For non-crypto markets we can't use CoinGecko but we can still scalp
# based purely on price (if one side is ≥85c with 2min left, it's high-conf)
PRICE_ONLY_THRESHOLD = 85  # enter any market where one side is this confident


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


def check_reversal(ticker, price_history):
    """
    Detect rapid price collapse. If YES dropped REVERSAL_DROP+ cents in REVERSAL_WINDOW secs
    from a high of REVERSAL_MIN_PRICE+, return ('no', drop_amount). Vice versa for NO.
    """
    history = price_history.get(ticker, [])
    if len(history) < 2:
        return None

    now = time.time()
    recent = [(t, ya, na) for t, ya, na in history if now - t <= REVERSAL_WINDOW]
    if len(recent) < 2:
        return None

    oldest_ya = recent[0][1]
    oldest_na = recent[0][2]
    latest_ya = recent[-1][1]
    latest_na = recent[-1][2]

    ya_drop = oldest_ya - latest_ya
    na_drop = oldest_na - latest_na

    # YES collapsing from high → buy NO
    if oldest_ya >= REVERSAL_MIN_PRICE and ya_drop >= REVERSAL_DROP:
        return ("no", ya_drop, oldest_ya, latest_ya)

    # NO collapsing from high → buy YES
    if oldest_na >= REVERSAL_MIN_PRICE and na_drop >= REVERSAL_DROP:
        return ("yes", na_drop, oldest_na, latest_na)

    return None


def get_all_closing_soon():
    """Sweep ALL open markets closing within SCALP_WINDOW seconds."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    max_ts = int((now + timedelta(seconds=SCALP_WINDOW)).timestamp())
    min_ts = int(now.timestamp() + 5)
    path = f"/trade-api/v2/markets?status=open&min_close_ts={min_ts}&max_close_ts={max_ts}&limit=100"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except:
        pass
    return []


def try_scalp(market, traded_tickers, ts, live_price=None):
    """Evaluate and potentially enter a scalp trade on one market."""
    ticker = market["ticker"]
    if ticker in traded_tickers:
        return

    secs = seconds_to_close(market.get("close_time", ""))
    if not secs or secs <= 0:
        return

    ya = market.get("yes_ask", 0)
    na = market.get("no_ask", 0)
    if not ya or not na:
        return

    # Determine trade
    trade = None
    edge_label = ""

    if live_price:
        # CoinGecko-verified edge
        trade = evaluate_trade(market, live_price)
        if trade:
            edge_label = f"CoinGecko edge {trade[2]:+.2f}%"
    
    # Price-only fallback: if one side is very high confidence
    if not trade:
        if ya >= PRICE_ONLY_THRESHOLD and ya < 97:
            trade = ("yes", ya, float(ya))
            edge_label = f"price-only {ya}c"
        elif na >= PRICE_ONLY_THRESHOLD and na < 97:
            trade = ("no", na, float(na))
            edge_label = f"price-only {na}c"

    if not trade:
        print(f"       ⏳ {ticker[-20:]} | yes={ya}c no={na}c | no clear edge")
        return

    side, price_cents, edge = trade
    profit_per = (100 - price_cents) / 100
    balance = get_balance() or 1

    if price_cents >= HIGH_CONF_PRICE:
        risk_amt = balance * RISK_PCT
        conf_label = "HIGH CONF 25%"
    else:
        risk_amt = balance * RISK_PCT_NORMAL
        conf_label = "normal 10%"

    contracts = min(MAX_CONTRACTS, max(1, int(risk_amt / (price_cents / 100))))

    print(f"\n[{ts}] 🎯 SCALP: {ticker[-25:]}")
    print(f"       {secs:.0f}s left | {side.upper()} @ {price_cents}c | {conf_label} | {contracts} contracts | {edge_label}")
    print(f"       Profit if wins: ${profit_per*contracts:.2f}")

    msg = (
        f"🔪 *Scalp!* [{conf_label}]\n"
        f"`{ticker}`\n"
        f"Buy {side.upper()} @ {price_cents}c | {secs:.0f}s left\n"
        f"{contracts} contracts | Profit: ${profit_per*contracts:.2f}\n"
        f"Signal: {edge_label}"
    )

    if AUTO_TRADE:
        ok, result = place_order(ticker, side, price_cents, count=contracts)
        if ok:
            print(f"       ✅ ORDER PLACED")
            tg(msg + "\n✅ *Placed!*")
        else:
            print(f"       ❌ Failed: {result}")
            tg(msg + f"\n❌ Failed: {result}")
    else:
        tg(msg + "\n_(auto-trade off)_")

    traded_tickers.add(ticker)


def scan_loop():
    print("=" * 60)
    print("  GoobClaw Near-Expiry Scalper")
    print(f"  Scalp window: last {SCALP_WINDOW//60} min | Edge: >{MIN_EDGE_PCT}% or price >{PRICE_ONLY_THRESHOLD}c")
    print(f"  Auto-trade: {AUTO_TRADE} | Max contracts: {MAX_CONTRACTS}")
    print(f"  Scanning: BTC/ETH (CoinGecko) + ALL closing-soon markets")
    print("=" * 60)

    tg(f"🔪 *Scalper online* — sweeping ALL markets closing in last {SCALP_WINDOW//60} min.")

    traded_tickers = set()
    last_status = 0
    price_history = {}  # ticker → [(timestamp, yes_ask, no_ask), ...]

    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            now_epoch = time.time()

            # Build market list: priority BTC/ETH + all closing soon
            all_markets = {}
            live_prices = {}

            for series, coin_id in SERIES.items():
                market = get_active_market(series)
                if market:
                    all_markets[market["ticker"]] = (market, coin_id)
                    price = get_live_price(coin_id)
                    if price:
                        live_prices[market["ticker"]] = price

            for m in get_all_closing_soon():
                if m["ticker"] not in all_markets:
                    all_markets[m["ticker"]] = (m, None)

            # Status print every 2 min
            if now_epoch - last_status > 120:
                print(f"[{ts}] Watching {len(all_markets)} markets in scalp window")
                for ticker, (m, _) in list(all_markets.items())[:4]:
                    secs = seconds_to_close(m.get("close_time",""))
                    print(f"  {ticker[-25:]} | yes={m.get('yes_ask')}c no={m.get('no_ask')}c | {secs:.0f}s left")
                last_status = now_epoch

            # Check each market
            for ticker, (market, coin_id) in all_markets.items():
                secs = seconds_to_close(market.get("close_time", ""))
                if secs is None or secs <= 0:
                    continue

                ya = market.get("yes_ask", 0)
                na = market.get("no_ask", 0)

                # Always track price history for reversal detection
                if ya and na and secs <= SCALP_WINDOW * 2:
                    if ticker not in price_history:
                        price_history[ticker] = []
                    price_history[ticker].append((now_epoch, ya, na))
                    # Keep only last 2 minutes of history
                    price_history[ticker] = [(t, y, n) for t, y, n in price_history[ticker] if now_epoch - t <= 120]

                if ticker in traded_tickers:
                    continue

                # Check for reversal signal (rapid collapse of leading side)
                if secs <= SCALP_WINDOW:
                    reversal = check_reversal(ticker, price_history)
                    if reversal:
                        rev_side, drop, from_price, to_price = reversal
                        rev_entry = market.get("yes_ask" if rev_side == "yes" else "no_ask", 50)
                        if rev_entry < 97:
                            balance = get_balance() or 1
                            risk_amt = balance * RISK_PCT  # always 25% on reversals
                            contracts = min(MAX_CONTRACTS, max(1, int(risk_amt / (rev_entry / 100))))
                            profit_if_wins = (100 - rev_entry) / 100 * contracts
                            print(f"\n[{ts}] 🔄 REVERSAL: {ticker[-20:]} | {rev_side.upper()} @ {rev_entry}c")
                            print(f"       Opposite side dropped {drop}c ({from_price}→{to_price}) in {REVERSAL_WINDOW}s")
                            print(f"       {contracts} contracts | profit if wins: ${profit_if_wins:.2f}")
                            msg = (f"🔄 *REVERSAL DETECTED*\n`{ticker}`\n"
                                   f"Opposite dropped {drop}c ({from_price}→{to_price}c)\n"
                                   f"Buy {rev_side.upper()} @ {rev_entry}c | {contracts} contracts\n"
                                   f"Profit if wins: ${profit_if_wins:.2f}")
                            if AUTO_TRADE:
                                ok, result = place_order(ticker, rev_side, rev_entry, count=contracts)
                                tg(msg + ("\n✅ Placed!" if ok else f"\n❌ {result}"))
                            traded_tickers.add(ticker)
                            continue

                if not (0 < secs <= SCALP_WINDOW):
                    continue

                live_price = live_prices.get(ticker)
                print(f"\n[{ts}] 🎯 SCALP WINDOW: {ticker[-25:]} | {secs:.0f}s left")

                try_scalp(market, traded_tickers, ts, live_price)

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
