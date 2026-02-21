#!/usr/bin/env python3
"""
Kalshi Guaranteed Win Scanner
Scans ETH/BTC 15-min and other fast-expiry markets for credit spread opportunities.
A "guaranteed win" exists when yes_ask + no_ask < 100¢.
"""

import os
import time
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"

# Series to scan — add more as needed
SCAN_SERIES = [
    "KXETH15M",   # ETH 15-minute
    "KXBTC15M",   # BTC 15-minute
    "KXETHD",     # ETH daily brackets
    "KXBTCD",     # BTC daily brackets
]

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10"))  # seconds
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"
MAX_SPEND = float(os.getenv("MAX_SPEND_PER_TRADE", "1.00"))


def get_markets(series_ticker):
    path = f"/trade-api/v2/markets?series_ticker={series_ticker}&status=open&limit=20"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except Exception as e:
        print(f"  [error] {series_ticker}: {e}")
    return []


def get_balance():
    path = "/trade-api/v2/portfolio/balance"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except Exception as e:
        print(f"  [error] balance: {e}")
    return None


def place_order(ticker, side, price_cents, count=1):
    """Place a limit order. side = 'yes' or 'no'."""
    path = "/trade-api/v2/portfolio/orders"
    import uuid
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
            print(f"  ✅ ORDER PLACED: {count}x {side.upper()} on {ticker} @ {price_cents}¢")
            return True
        else:
            print(f"  ❌ Order failed: {res.text}")
    except Exception as e:
        print(f"  ❌ Order error: {e}")
    return False


def minutes_to_close(close_time_str):
    try:
        ct = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        delta = (ct - datetime.now(timezone.utc)).total_seconds() / 60
        return max(delta, 0)
    except:
        return None


def scan_once():
    ts = datetime.now().strftime("%H:%M:%S")
    opportunities = []

    for series in SCAN_SERIES:
        markets = get_markets(series)
        for m in markets:
            ticker = m.get("ticker", "")
            ya = m.get("yes_ask", 0)
            na = m.get("no_ask", 0)

            # Skip markets with no liquidity
            if ya == 0 or na == 0:
                continue

            total = ya + na
            close_time = m.get("close_time", "")
            mins_left = minutes_to_close(close_time)

            if total < 100:
                profit = (100 - total) / 100
                opportunities.append({
                    "ticker": ticker,
                    "yes_ask": ya,
                    "no_ask": na,
                    "total": total,
                    "profit": profit,
                    "mins_left": mins_left,
                    "series": series,
                })

    return opportunities


def run():
    print("=" * 60)
    print("  Kalshi Guaranteed Win Scanner")
    print(f"  Scanning: {', '.join(SCAN_SERIES)}")
    print(f"  Interval: {SCAN_INTERVAL}s | Auto-trade: {AUTO_TRADE}")
    print("=" * 60)

    scan_count = 0
    last_balance_check = 0

    while True:
        try:
            now = time.time()
            ts = datetime.now().strftime("%H:%M:%S")

            # Check balance every 60 seconds
            if now - last_balance_check > 60:
                balance = get_balance()
                if balance is not None:
                    print(f"\n[{ts}] 💰 Balance: ${balance:.2f}")
                last_balance_check = now

            # Scan markets
            opportunities = scan_once()
            scan_count += 1

            if opportunities:
                print(f"\n[{ts}] 🚀 GUARANTEED WIN FOUND! ({len(opportunities)} opportunity/ies)")
                for opp in opportunities:
                    mins = f"{opp['mins_left']:.1f}min" if opp['mins_left'] else "?"
                    print(f"  {opp['ticker']}")
                    print(f"    YES={opp['yes_ask']}¢  NO={opp['no_ask']}¢  TOTAL={opp['total']}¢  PROFIT=${opp['profit']:.2f}  EXP={mins}")

                    if AUTO_TRADE:
                        print(f"  → Auto-trading...")
                        place_order(opp["ticker"], "yes", opp["yes_ask"])
                        place_order(opp["ticker"], "no", opp["no_ask"])
            else:
                # Show current best spread every 5 scans
                if scan_count % 5 == 1:
                    print(f"\n[{ts}] Scanning... (no arb yet)")
                    # Show closest opportunities
                    closest = []
                    for series in SCAN_SERIES[:2]:  # Just ETH/BTC 15-min for summary
                        markets = get_markets(series)
                        for m in markets:
                            ya = m.get("yes_ask", 0)
                            na = m.get("no_ask", 0)
                            if ya and na:
                                closest.append((ya + na, m["ticker"], ya, na))
                    for total, ticker, ya, na in sorted(closest)[:3]:
                        gap = total - 100
                        print(f"  {ticker[-28:]} | {ya}¢+{na}¢={total}¢ | {gap:+d}¢ from arb")

            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\n\nStopped.")
            break
        except Exception as e:
            print(f"[{ts}] Error: {e}")
            time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    run()
