#!/usr/bin/env python3
"""
Trade Monitor - Shows P&L and trade outcomes
Usage: python3 trade_monitor.py [days]
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"


def get_balance():
    path = "/trade-api/v2/portfolio/balance"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    return None


def get_fills(days=1):
    """Get fills from the last N days."""
    sig_path = "/trade-api/v2/portfolio/fills"
    full_path = sig_path + "?limit=500"
    try:
        res = requests.get(
            BASE_URL + full_path,
            headers=get_kalshi_headers("GET", sig_path),
            timeout=10
        )
        if res.status_code != 200:
            print(f"  ⚠️ Fills API returned {res.status_code}")
            return []

        fills = res.json().get("fills", [])

        # Filter by date using correct field name: created_time
        # NOTE: If this breaks, field names may have changed. To rediscover them,
        # temporarily add after line 44:
        #   print(f"Fill keys: {list(fills[0].keys())}")
        #   print(f"First fill: {fills[0]}")
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = []
        for f in fills:
            try:
                created = datetime.fromisoformat(f.get("created_time", "").replace("Z", "+00:00"))
                if created >= cutoff:
                    filtered.append(f)
            except:
                pass
        return filtered
    except Exception as e:
        print(f"  ⚠️ Error getting fills: {e}")
    return []


def get_settlements(days=1):
    """Get settlements from the last N days."""
    sig_path = "/trade-api/v2/portfolio/settlements"
    full_path = sig_path + "?limit=500"
    try:
        res = requests.get(
            BASE_URL + full_path,
            headers=get_kalshi_headers("GET", sig_path),
            timeout=10
        )
        if res.status_code != 200:
            print(f"  ⚠️ Settlements API returned {res.status_code}: {res.text[:200]}")
            return []

        data = res.json()
        settlements_raw = data.get("settlements", [])

        if not settlements_raw:
            print(f"  DEBUG: Settlements endpoint returned empty. Full response keys: {list(data.keys())}")
            return []

        # NOTE: If settlement fields change, these two debug lines show the raw structure:
        #   print(f"Settlement keys: {list(settlements_raw[0].keys())}")
        #   print(f"First settlement: {settlements_raw[0]}")
        print(f"  DEBUG: Settlement keys:      {list(settlements_raw[0].keys())}")
        print(f"  DEBUG: First settlement raw: {settlements_raw[0]}")

        # Try both created_time and created_at
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = []
        for s in settlements_raw:
            ts_str = s.get("created_time") or s.get("created_at") or ""
            try:
                created = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if created >= cutoff:
                    filtered.append(s)
            except:
                filtered.append(s)  # include if date unparseable
        return filtered
    except Exception as e:
        print(f"  ⚠️ Error getting settlements: {e}")
    return []


def show_trade_history(days=1, silent=False):
    """Show complete trade history with outcomes."""

    if not silent:
        print("\n" + "=" * 70)
        print(f" 📊 TRADE MONITOR (Last {days} day(s))")
        print("=" * 70)

    balance = get_balance()
    if not silent:
        print(f" 💰 Current Balance: ${balance:.2f}" if balance else " 💰 Balance: N/A")

    fills = get_fills(days)
    settlements = get_settlements(days)

    print(f"  DEBUG: Fills count: {len(fills)}, Settlements count: {len(settlements)}")

    # Build settlement lookup by ticker
    settled = {s.get("ticker", s.get("market_ticker", "")): s for s in settlements}

    open_trades = []
    closed_trades = []

    for f in fills:
        ticker = f.get("ticker", "?")
        if ticker in settled:
            closed_trades.append((f, settled[ticker]))
        else:
            open_trades.append(f)

    closed_trades.sort(key=lambda x: x[0].get("created_time", ""), reverse=True)
    open_trades.sort(key=lambda x: x.get("created_time", ""), reverse=True)

    print(f"\n 📈 CLOSED TRADES: {len(closed_trades)}")
    print("-" * 70)

    total_pnl = 0
    total_fees = 0
    wins = 0
    losses = 0

    for fill, settlement in closed_trades:
        ticker = fill.get("ticker", "?")
        action = fill.get("action", "?")
        price = fill.get("yes_price", 0)
        count = fill.get("count", 0)

        revenue = settlement.get("revenue", 0)
        cost = price * count
        fees = float(fill.get("fee_cost", 0))

        pnl = revenue - cost - fees
        total_pnl += pnl / 100
        total_fees += fees / 100

        if pnl >= 0:
            wins += 1
            result = f"✅ +{pnl/100:.2f}"
        else:
            losses += 1
            result = f"❌ {pnl/100:.2f}"

        try:
            ts = datetime.fromisoformat(fill.get("created_time", "").replace("Z", "+00:00"))
            ts_str = ts.strftime("%m/%d %H:%M")
        except:
            ts_str = "??/?? ??"

        print(f" {ts_str} {ticker:<26} {action:>4} @{price:>2}c x{count:<2} {result}")

    print("-" * 70)
    if closed_trades:
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        print(f" Summary: {wins}W / {losses}L ({win_rate:.0f}% win rate)")
        print(f" Total P&L: ${total_pnl:.2f} | Fees: ${total_fees:.2f} | Net: ${total_pnl - total_fees:.2f}")

    print(f"\n 📋 OPEN TRADES: {len(open_trades)}")
    print("-" * 70)

    for fill in open_trades[:10]:
        ticker = fill.get("ticker", "?")
        action = fill.get("action", "?")
        price = fill.get("yes_price", 0)
        count = fill.get("count", 0)

        try:
            ts = datetime.fromisoformat(fill.get("created_time", "").replace("Z", "+00:00"))
            ts_str = ts.strftime("%m/%d %H:%M")
        except:
            ts_str = "??/?? ??"

        print(f" {ts_str} {ticker:<26} {action:>4} @{price:>2}c x{count:<2} ⏳ open")

    print("=" * 70)

    return total_pnl, wins, losses


if __name__ == "__main__":
    import time
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("days", type=int, nargs="?", default=1, help="Days to look back")
    parser.add_argument("--interval", "-i", type=int, default=30, help="Seconds between checks")
    parser.add_argument("--once", "-1", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    if args.once:
        show_trade_history(args.days)
    else:
        print(f"🔄 Trade Monitor running... checking every {args.interval}s (Ctrl+C to stop)")
        while True:
            try:
                show_trade_history(args.days, silent=False)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n👋 Stopped")
                break
