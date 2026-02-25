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
            headers=get_kalshi_headers("GET", sig_path),  # ← clean path, no query
            timeout=10
        )
        if res.status_code != 200:
            print(f"  ⚠️ Fills API returned {res.status_code}")
            return []
        fills = res.json().get("fills", [])
        
        # Filter by date
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = []
        for f in fills:
            try:
                created = datetime.fromisoformat(f.get("created_at", "").replace("Z", "+00:00"))
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
            headers=get_kalshi_headers("GET", sig_path),  # ← clean path, no query
            timeout=10
        )
        if res.status_code != 200:
            print(f"  ⚠️ Settlements API returned {res.status_code}")
            return []
        settlements = res.json().get("settlements", [])
        
        # Filter by date
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filtered = []
        for s in settlements:
            try:
                created = datetime.fromisoformat(s.get("created_at", "").replace("Z", "+00:00"))
                if created >= cutoff:
                    filtered.append(s)
            except:
                pass
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
    
    # Get balance
    balance = get_balance()
    if not silent:
        print(f" 💰 Current Balance: ${balance:.2f}" if balance else " 💰 Balance: N/A")
    
    # Get data
    fills = get_fills(days)
    settlements = get_settlements(days)
    
    # Build settlement lookup
    settled = {s["ticker"]: s for s in settlements}
    
    # Categorize
    open_trades = []
    closed_trades = []
    
    for f in fills:
        ticker = f.get("ticker", "?")
        if ticker in settled:
            closed_trades.append((f, settled[ticker]))
        else:
            open_trades.append(f)
    
    # Sort by time
    closed_trades.sort(key=lambda x: x[0].get("created_at", ""), reverse=True)
    open_trades.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    print(f"\n 📈 CLOSED TRADES: {len(closed_trades)}")
    print("-" * 70)
    
    total_pnl = 0
    total_fees = 0
    wins = 0
    losses = 0
    
    for fill, settlement in closed_trades:
        ticker = fill.get("ticker", "?")
        side = fill.get("side", "?")
        action = fill.get("action", "?")
        price = fill.get("yes_price", 0)
        count = fill.get("count", 0)
        
        revenue = settlement.get("revenue", 0)
        cost = price * count
        fees = float(settlement.get("fee_cost", 0))
        
        pnl = revenue - cost - fees
        total_pnl += pnl / 100
        total_fees += fees / 100
        
        if pnl >= 0:
            wins += 1
            result = f"✅ +{pnl/100:.2f}"
        else:
            losses += 1
            result = f"❌ {pnl/100:.2f}"
        
        # Try to get timestamp
        try:
            ts = datetime.fromisoformat(fill.get("created_at", "").replace("Z", "+00:00"))
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
    
    open_value = 0
    for fill in open_trades[:10]:  # Show last 10
        ticker = fill.get("ticker", "?")
        side = fill.get("side", "?")
        action = fill.get("action", "?")
        price = fill.get("yes_price", 0)
        count = fill.get("count", 0)
        
        try:
            ts = datetime.fromisoformat(fill.get("created_at", "").replace("Z", "+00:00"))
            ts_str = ts.strftime("%m/%d %H:%M")
        except:
            ts_str = "??/?? ??"
        
        # Estimate current value
        if side == "yes":
            # Would sell at current bid... don't have that here
            value = "?"
        else:
            value = "?"
        
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
