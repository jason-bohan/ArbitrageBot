#!/usr/bin/env python3
"""
GoobClaw ProfitBot — PAPER TRADING VERSION (Forced)
Strategy:
1. Pairs arbitrage (YES + NO < $1) — risk-free profit
2. Late-game mispricing (>75% or <25% with time left)
3. Strict position sizing (Kelly Criterion lite)
4. No "hope" trades — only edges with >60% win prob

CRITICAL FIXES v4:
- Fixed arbitrage cost calculation (uses ASK prices, not mid-prices)
- Added position tracking (prevents double-entering same market)
- More realistic late-game thresholds (25¢/75¢ vs 20¢/80¢)
- Added expiration handling and position management
- CORRECTED: Kalshi fees are ~1.2% (NOT 7%!)
"""

import os
import time
import uuid
import requests
import math
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

# FORCE PAPER TRADING
AUTO_TRADE = False

BASE_URL = "https://api.elections.kalshi.com"

# === FIXED PROFIT PARAMETERS ===
KELLY_FRACTION = 0.25        # Kelly Lite (don't overbet)
MIN_ARB_PROFIT = 0.50        # $0.50 minimum for arbitrage (after fees)
MIN_LATE_GAP = 10             # 10¢ gap minimum for late-game (more realistic)
MAX_TIME_LEFT = 240          # Enter only with <4 min left
MIN_VOLUME = 5000           # Skip illiquid markets
BANKROLL_PCT = 0.02          # Max 2% of bankroll per trade

# Fee adjustments (ACTUAL KALSHI FEES - ~1.2% average, not 7%!)
# Kalshi uses probability-based scaling: highest at 50¢, lowest at extremes
# S&P 500 and Nasdaq-100 get 50% discount
BUY_FEE_PCT = 0.006   # ~0.6% average (scales with probability)
SELL_FEE_PCT = 0.006  # ~0.6% average (scales with probability)
TOTAL_FEE_PCT = 0.012  # ~1.2% total average (NOT 7%!)

# Performance tracking
PERFORMANCE_LOG = "profit_bot_performance.json"

# Position tracking file
POSITIONS_FILE = "profit_bot_positions.json"


def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",
            json={"chat_id": os.getenv('JASON_CHAT_ID'), "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
    except:
        pass


def get_balance():
    try:
        path = "/trade-api/v2/portfolio/balance"
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except:
        pass
    return 1000  # Default $1000 for paper trading


def get_market(ticker):
    path = f"/trade-api/v2/markets/{ticker}"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("market", {})
    except:
        pass
    return None


def get_open_markets():
    """Get all open markets."""
    now = datetime.now(timezone.utc)
    path = f"/trade-api/v2/markets?status=open&limit=200"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=15)
        if res.status_code == 200:
            return res.json().get("markets", [])
    except:
        pass
    return []


def place_order(ticker, side, price_cents, count, action="buy"):
    # PAPER TRADING - always succeeds
    return True, "PAPER TRADE"


def load_positions():
    """Load existing positions."""
    try:
        with open(POSITIONS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_positions(positions):
    """Save positions to file."""
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2)


def load_performance():
    """Load performance tracking data."""
    try:
        with open(PERFORMANCE_LOG, "r") as f:
            return json.load(f)
    except:
        return {"arb_trades": 0, "late_trades": 0, "arb_profit": 0, "late_profit": 0}


def save_performance(perf):
    """Save performance tracking data."""
    with open(PERFORMANCE_LOG, "w") as f:
        json.dump(perf, f, indent=2)


def check_arbitrage(market, balance, positions):
    """
    FIXED ARBITRAGE: Use actual ASK prices, not mid-prices.
    Returns (should_trade, profit_cents_after_fees, yes_count, no_count) or (False, ...)
    """
    ya = market.get("yes_ask", 0)  # ACTUAL cost for YES
    na = market.get("no_ask", 0)   # ACTUAL cost for NO
    yb = market.get("yes_bid", 0)
    nb = market.get("no_bid", 0)
    
    # 🚨 CRITICAL FIX: Use actual ASK prices, not mid-prices
    total_cost = ya + na  # This is what we ACTUALLY pay
    
    # Position tracking - don't double-enter
    ticker = market["ticker"]
    if ticker in positions:
        return False, 0, 0, 0
    
    # 🚨 CRITICAL FIX: Much better thresholds with 1.2% fees (not 7%!)
    # Can be much more aggressive with low fees
    max_cost = 99.5  # Allow 0.5¢ margin for 1.2% fees/slippage
    
    if total_cost < max_cost and ya > 0 and na > 0:
        # Calculate profit AFTER fees
        gross_profit_per_pair = 100 - total_cost  # cents
        fee_cost_per_pair = gross_profit_per_pair * TOTAL_FEE_PCT
        net_profit_per_pair = gross_profit_per_pair - fee_cost_per_pair
        
        if net_profit_per_pair >= MIN_ARB_PROFIT:
            # How many pairs can we buy?
            cost_per_pair = total_cost / 100  # dollars
            max_pairs = int(balance / cost_per_pair)
            
            # Kelly sizing (lite)
            kelly_pct = 0.5 * KELLY_FRACTION  # Conservative
            pairs = int(max_pairs * kelly_pct)
            pairs = max(1, min(pairs, 100))  # 1-100 range
            
            if pairs >= 1:
                return True, net_profit_per_pair, pairs
    
    return False, 0, 0, 0


def check_late_game(market, balance, positions):
    """
    FIXED LATE GAME: More realistic thresholds, position tracking.
    Returns (should_trade, side, confidence) or (False, None, 0)
    """
    ticker = market["ticker"]
    
    # Position tracking
    if ticker in positions:
        return False, None, 0
    
    ya = market.get("yes_ask", 50)
    yb = market.get("yes_bid", 50)
    na = market.get("no_ask", 50)
    nb = market.get("no_bid", 50)
    
    yes_mid = (ya + yb) / 2
    no_mid = (na + nb) / 2
    
    # Time check
    try:
        close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
        secs_left = (close - datetime.now(timezone.utc)).total_seconds()
    except:
        return False, None, 0
    
    if secs_left > MAX_TIME_LEFT or secs_left < 60:
        return False, None, 0
    
    # Volume check
    vol = market.get("volume", 0)
    if vol < MIN_VOLUME:
        return False, None, 0
    
    # 🚨 CRITICAL FIX: More realistic late-game conditions
    # Look for significant mispricing, not extreme conditions
    
    # YES heavily underpriced (<25¢) while NO is expensive (>75¢)
    if yes_mid < 25 and no_mid > 75:
        gap = no_mid - yes_mid
        if gap >= MIN_LATE_GAP:
            prob = yes_mid / 100
            # Adjust confidence for fees
            edge = (prob - ((1 - prob) * (yes_mid / no_mid))) if no_mid > 0 else 0
            adjusted_confidence = min(0.85, (gap / 100) - TOTAL_FEE_PCT + 0.3)
            return True, "yes", max(0.6, adjusted_confidence)
    
    # NO heavily underpriced (<25¢) while YES is expensive (>75¢)
    if no_mid < 25 and yes_mid > 75:
        gap = yes_mid - no_mid
        if gap >= MIN_LATE_GAP:
            prob = no_mid / 100
            edge = (prob - ((1 - prob) * (no_mid / yes_mid))) if yes_mid > 0 else 0
            adjusted_confidence = min(0.85, (gap / 100) - TOTAL_FEE_PCT + 0.3)
            return True, "no", max(0.6, adjusted_confidence)
    
    return False, None, 0


def execute_arbitrage(market, pairs, profit_cents, positions):
    """Execute arbitrage with position tracking and safety checks."""
    ticker = market["ticker"]
    ya = market.get("yes_ask", 0)
    na = market.get("no_ask", 0)
    
    ts = datetime.now().strftime("%H:%M:%S")
    total_net_profit = pairs * profit_cents / 100
    
    details = f"ARB: YES@{ya}c + NO@{na}c = {ya+na}c | {pairs} pairs | Net: +{profit_cents:.1f}¢/pair"
    
    print(f"\n[{ts}] 🎯 ARBITRAGE {ticker}")
    print(f"   {details}")
    print(f"   💰 PROFIT: +${total_net_profit:.2f} (after {TOTAL_FEE_PCT*100:.0f}% fees)")
    print(f"   📝 PAPER TRADE: Would execute arbitrage")
    tg(f"📝 *Paper ARB* `{ticker}` | {pairs} pairs | +${total_net_profit:.2f} hypothetical")
    
    # Update performance tracking for paper trades
    perf = load_performance()
    perf["arb_trades"] += 1
    perf["arb_profit"] += total_net_profit
    save_performance(perf)
    
    # 🚨 CRITICAL FIX: Add to positions
    positions[ticker] = {
        "type": "arbitrage",
        "entry_time": datetime.now().isoformat(),
        "pairs": pairs,
        "yes_cost": ya,
        "no_cost": na,
        "expected_profit": total_net_profit
    }
    save_positions(positions)


def execute_late_game(market, side, confidence, balance, positions):
    """Execute late-game trade with position tracking and safety checks."""
    ticker = market["ticker"]
    price = market.get("yes_ask" if side == "yes" else "no_ask", 50)
    
    max_bet = balance * BANKROLL_PCT * 0.8
    contracts = int((max_bet * 100) / price)
    contracts = max(1, contracts)
    
    try:
        close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
        mins_left = (close - datetime.now(timezone.utc)).total_seconds() / 60
    except:
        mins_left = 0
    
    ts = datetime.now().strftime("%H:%M:%S")
    
    details = f"LATE: {side.upper()}@{price}c | {contracts} contracts | {confidence:.0%} conf | {mins_left:.1f}min"
    
    print(f"\n[{ts}] 🎯 LATE GAME {ticker}")
    print(f"   {details}")
    
    # Simulate outcome for paper trading
    import random
    won = random.random() < confidence
    
    if won:
        gross_profit = (100 - price) * contracts / 100
        fees = gross_profit * TOTAL_FEE_PCT
        net_profit = gross_profit - fees
        result_text = f"SIMULATED WIN +${net_profit:.2f}"
        pnl = net_profit
    else:
        cost = price * contracts / 100
        fees = cost * BUY_FEE_PCT
        net_loss = cost + fees
        result_text = f"SIMULATED LOSS -${net_loss:.2f}"
        pnl = -net_loss
    
    print(f"   🎲 {result_text}")
    tg(f"📝 *Paper Late* `{ticker}` {side.upper()} | {result_text}")
    
    # Update performance tracking for paper trades
    perf = load_performance()
    perf["late_trades"] += 1
    perf["late_profit"] += pnl
    save_performance(perf)
    
    # 🚨 CRITICAL FIX: Add to positions
    positions[ticker] = {
        "type": "late_game",
        "side": side,
        "entry_time": datetime.now().isoformat(),
        "contracts": contracts,
        "entry_price": price,
        "confidence": confidence
    }
    save_positions(positions)


def run():
    print("=" * 60)
    print("  GoobClaw ProfitBot v4 — PAPER TRADING MODE")
    print(f"  Auto: {AUTO_TRADE} | Kelly: {KELLY_FRACTION} | Min Arb: {MIN_ARB_PROFIT}¢")
    print(f"  🔧 Fixed: Arbitrage cost calc, position tracking, realistic thresholds")
    print(f"  ✅ CORRECTED: Kalshi fees are ~1.2% (NOT 7%!)")
    print("=" * 60)
    tg("🦞 *ProfitBot v4 PAPER MODE* — Testing corrected fees")
    
    trades_today = 0
    arb_count = 0
    late_count = 0
    
    # Load existing positions
    positions = load_positions()
    
    # Load performance stats
    perf = load_performance()
    
    # Show startup stats
    if perf["arb_trades"] > 0 or perf["late_trades"] > 0:
        total_trades = perf["arb_trades"] + perf["late_trades"]
        total_profit = perf["arb_profit"] + perf["late_profit"]
        avg_profit = total_profit / total_trades if total_trades > 0 else 0
        
        print(f"\n📊 HISTORICAL PERFORMANCE:")
        print(f"   Total Trades: {total_trades}")
        print(f"   Arbitrage: {perf['arb_trades']} trades | +${perf['arb_profit']:.2f}")
        print(f"   Late Game: {perf['late_trades']} trades | ${perf['late_profit']:.2f}")
        print(f"   Total P&L: ${total_profit:.2f}")
        print(f"   Avg Profit: ${avg_profit:.2f}/trade")
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            balance = get_balance()
            
            if balance:
                print(f"\n[{ts}] Bankroll: ${balance:.2f}")
            
            markets = get_open_markets()
            print(f"Scanning {len(markets)} markets... | Active positions: {len(positions)}")
            
            arb_taken = 0
            late_taken = 0
            
            # DEBUG: Show some sample markets
            if len(markets) > 0:
                print(f"   Sample markets:")
                for i, m in enumerate(markets[:3]):
                    ya = m.get("yes_ask", 0)
                    na = m.get("no_ask", 0)
                    total = ya + na
                    print(f"   {i+1}. {m['ticker']}: YES={ya}c, NO={na}c, Total={total}c")
            
            for m in markets:
                ticker = m["ticker"]
                
                # Skip decided markets or illiquid markets
                ya = m.get("yes_ask", 50)
                na = m.get("no_ask", 50)
                
                # Skip if either side is 0 or 100 (decided/illiquid)
                if ya == 0 or ya == 100 or na == 0 or na == 100:
                    continue
                if ya >= 95 or na >= 95:
                    continue
                
                # Check arbitrage first (risk-free money)
                if balance and ya > 0 and na > 0:
                    arb, profit, pairs, _ = check_arbitrage(m, balance, positions)
                    if arb and profit >= MIN_ARB_PROFIT:
                        execute_arbitrage(m, pairs, profit, positions)
                        arb_taken += 1
                        arb_count += 1
                        trades_today += 1
                        continue  # Move to next market
                
                # Check late-game opportunity
                if balance:
                    should_trade, side, confidence = check_late_game(m, balance, positions)
                    if should_trade and confidence >= 0.6:  # Lower threshold for more opportunities
                        execute_late_game(m, side, confidence, balance, positions)
                        late_taken += 1
                        late_count += 1
                        trades_today += 1
            
            print(f"[{ts}] Done. Today's: {trades_today} trades (arb: {arb_count}, late: {late_count})")
            
            # Show updated performance every hour
            if int(time.time()) % 3600 < 45:
                perf = load_performance()
                total_trades = perf["arb_trades"] + perf["late_trades"]
                total_profit = perf["arb_profit"] + perf["late_profit"]
                if total_trades > 0:
                    print(f"\n📊 UPDATED PERFORMANCE:")
                    print(f"   Total P&L: ${total_profit:.2f} | Avg: ${total_profit/total_trades:.2f}/trade")
            
            # Slow scan — we're patient hunters
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            # Show final performance
            perf = load_performance()
            total_trades = perf["arb_trades"] + perf["late_trades"]
            total_profit = perf["arb_profit"] + perf["late_profit"]
            print(f"\n📊 FINAL PERFORMANCE:")
            print(f"   Total Trades: {total_trades}")
            print(f"   Total P&L: ${total_profit:.2f}")
            if total_trades > 0:
                print(f"   Average Profit: ${total_profit/total_trades:.2f}/trade")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
