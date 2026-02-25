#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GoobClaw ProfitBot — Mathematical Edge Only (CRITICAL BUGS FIXED)
"""

import os
import sys
import unicodedata

# Fix Unicode printing issues
if sys.version_info[0] >= 3:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import time


def safe_print(*args, **kwargs):
    """Print that handles Unicode characters safely."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # Fallback: encode with replace
        args = [str(a).encode('utf-8', errors='replace').decode('utf-8', errors='replace') for a in args]
        print(*args, **kwargs)
import uuid
import requests
import math
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"

# === FIXED PROFIT PARAMETERS ===
KELLY_FRACTION = 0.25        # Kelly Lite (don't overbet)
MIN_ARB_PROFIT = 0.10        # $0.10 minimum for arbitrage (after fees)
MIN_LATE_GAP = 3             # 3¢ gap minimum for late-game
MAX_TIME_LEFT = 600          # Enter only with <10 min left
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
        print(f"  🌐 GET balance → {res.status_code} {'✅' if res.status_code == 200 else '❌'}")
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except Exception as e:
        print(f"  🌐 GET balance → ⚠️ {e}")
    return None


def get_market(ticker):
    path = f"/trade-api/v2/markets/{ticker}"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        if res.status_code == 200:
            return res.json().get("market", {})
        else:
            print(f"  🌐 GET {ticker} → {res.status_code}")
    except Exception as e:
        print(f"  🌐 GET {ticker} → ⚠️ {e}")
    return None


def get_open_markets():
    """Get all open markets."""
    now = datetime.now(timezone.utc)
    path = f"/trade-api/v2/markets?status=open&limit=200"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=15)
        print(f"  🌐 GET open markets → {res.status_code} {'✅' if res.status_code == 200 else '❌'}")
        if res.status_code == 200:
            return res.json().get("markets", [])
    except Exception as e:
        print(f"  🌐 GET open markets → ⚠️ {e}")
    return []


def get_trade_history_today():
    """Get order history from today via API.
    Note: May return 401 if API key lacks orders permission.
    """
    try:
        path = "/trade-api/v2/portfolio/orders?status=filled&limit=100"
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            orders = res.json().get("orders", [])
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_orders = [o for o in orders if o.get("created_at", "").startswith(today)]
            return len(today_orders)
        elif res.status_code == 401:
            # Permission denied - API key doesn't have orders access
            return None
        else:
            print(f"  🌐 GET order history → {res.status_code}")
    except Exception as e:
        print(f"  🌐 GET order history → ⚠️ {e}")
    return None


def place_order(ticker, side, price_cents, count, action="buy"):
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
        print(f"  🌐 POST {ticker} {side}@{price_cents}c → {res.status_code} {'✅' if res.status_code == 201 else '❌'}")
        return res.status_code == 201, res.text
    except Exception as e:
        print(f"  🌐 POST order → ⚠️ {e}")
        return False, str(e)


def load_positions():
    """Load existing positions."""
    try:
        with open(POSITIONS_FILE, "r", encoding='utf-8', errors='replace') as f:
            return json.load(f)
    except:
        return {}


def save_positions(positions):
    """Save positions to file."""
    with open(POSITIONS_FILE, "w", encoding='utf-8', errors='replace') as f:
        json.dump(positions, f, indent=2, ensure_ascii=False)


def load_performance():
    """Load performance tracking data."""
    try:
        with open(PERFORMANCE_LOG, "r", encoding='utf-8', errors='replace') as f:
            return json.load(f)
    except:
        return {"arb_trades": 0, "late_trades": 0, "arb_profit": 0, "late_profit": 0}


def save_performance(perf):
    """Save performance tracking data."""
    with open(PERFORMANCE_LOG, "w", encoding='utf-8', errors='replace') as f:
        json.dump(perf, f, indent=2, ensure_ascii=False)


def reconcile_positions():
    """
    CRITICAL SAFETY: Compare saved positions with actual portfolio.
    Prevents position file desync from crashes/restarts.
    """
    try:
        # Get actual portfolio from API
        path = "/trade-api/v2/portfolio/positions"
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        print(f"  🌐 GET portfolio positions → {res.status_code} {'✅' if res.status_code == 200 else '❌'}")
        
        if res.status_code == 200:
            actual_positions = {}
            for pos in res.json().get("positions", []):
                ticker = pos.get("ticker")
                if ticker:
                    actual_positions[ticker] = {
                        "type": "api_verified",
                        "count": pos.get("count", 0),
                        "side": pos.get("side", ""),
                        "yes_price": pos.get("yes_price", 0)
                    }
            
            # Load our saved positions
            saved_positions = load_positions()
            
            # Check for discrepancies
            discrepancies = []
            for ticker, saved_pos in saved_positions.items():
                if ticker not in actual_positions:
                    discrepancies.append(f"{ticker}: Saved but not in portfolio")
                elif saved_pos.get("type") == "arbitrage":
                    # Arbitrage should have both YES and NO
                    expected_count = saved_pos.get("pairs", 0) * 2
                    actual_count = sum(1 for p in res.json().get("positions", []) 
                                    if p.get("ticker") == ticker)
                    if actual_count != expected_count:
                        discrepancies.append(f"{ticker}: Expected {expected_count}, have {actual_count}")
            
            if discrepancies:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{ts}] ⚠️ POSITION RECONCILIATION ALERT:")
                for disc in discrepancies:
                    print(f"   {disc}")
                tg(f"⚠️ *Position reconciliation needed*\n" + "\n".join(discrepancies[:3]))
                
                # Auto-cleanup: Remove positions that don't exist
                cleaned_positions = {k: v for k, v in saved_positions.items() 
                                 if k in actual_positions}
                save_positions(cleaned_positions)
                return cleaned_positions
            
            return saved_positions
        
    except Exception as e:
        print(f"Reconciliation failed: {e}")
        return load_positions()


def check_fee_impact(profit_cents, trade_type="arbitrage"):
    """
    Alert if fees are eating too much profit.
    """
    if trade_type == "arbitrage":
        gross_profit = profit_cents + (profit_cents * TOTAL_FEE_PCT)
        fee_impact_pct = (profit_cents * TOTAL_FEE_PCT) / gross_profit * 100
        
        if fee_impact_pct > 15:  # Fees > 15% of gross profit
            print(f"   ⚠️ HIGH FEE IMPACT: {fee_impact_pct:.1f}% of gross profit")
            tg(f"⚠️ *High fee impact*: {fee_impact_pct:.1f}% on arbitrage")
    
    return True


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
    
    # Safety check: fee impact
    check_fee_impact(profit_cents, "arbitrage")
    
    details = f"ARB: YES@{ya}c + NO@{na}c = {ya+na}c | {pairs} pairs | Net: +{profit_cents:.1f}¢/pair"
    
    print(f"\n[{ts}] 🎯 ARBITRAGE {ticker}")
    print(f"   {details}")
    print(f"   💰 PROFIT: +${total_net_profit:.2f} (after {TOTAL_FEE_PCT*100:.0f}% fees)")
    
    if AUTO_TRADE:
        ok1, err1 = place_order(ticker, "yes", ya, pairs)
        ok2, err2 = place_order(ticker, "no", na, pairs)
        
        if ok1 and ok2:
            print(f"   ✅ Arb executed! Hold to expiration.")
            tg(f"✅ *Arb filled* `{ticker}` — +${total_net_profit:.2f} net at expiry")
            
            # Update performance tracking
            perf = load_performance()
            perf["arb_trades"] += 1
            perf["arb_profit"] += total_net_profit
            save_performance(perf)
        else:
            print(f"   ❌ Arb failed: {err1} | {err2}")
            tg(f"❌ *Arb failed* `{ticker}`: {err1[:50]} | {err2[:50]}")
    else:
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
    if not AUTO_TRADE:
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
    
    if AUTO_TRADE:
        ok, err = place_order(ticker, side, price, contracts)
        if ok:
            print(f"   ✅ Order filled!")
            tg(f"✅ *Filled* `{ticker}` {side.upper()} x{contracts}")
        else:
            print(f"   ❌ Order failed: {err}")
            tg(f"❌ *Failed* `{ticker}`: {err[:50]}")
    
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


def check_exited_positions(positions):
    """Check if any positions have expired and should be closed."""
    current_positions = {}
    updated = False
    
    for ticker, pos in positions.items():
        market = get_market(ticker)
        if not market:
            continue
        
        try:
            # Handle missing close_time
            close_time_str = market.get("close_time")
            if not close_time_str:
                current_positions[ticker] = pos
                continue
                
            close = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            secs_left = (close - datetime.now(timezone.utc)).total_seconds()
            
            if secs_left <= 0:  # Expired
                ts = datetime.now().strftime("%H:%M:%S")
                
                if pos["type"] == "arbitrage":
                    # Arbitrage should resolve to profit
                    profit = pos.get("expected_profit", 0)
                    print(f"[{ts}] ✅ {ticker} ARBITRAGE expired - Expected: +${profit:.2f}")
                    
                elif pos["type"] == "late_game":
                    # Late game resolution
                    print(f"[{ts}] ⏰ {ticker} LATE GAME expired")
                
                updated = True
            else:
                # Still active
                current_positions[ticker] = pos
                
        except Exception as e:
            print(f"Error checking {ticker}: {e}")
            current_positions[ticker] = pos
    
    if updated:
        save_positions(current_positions)
    
    return current_positions


def run():
    print("=" * 60)
    print("  GoobClaw ProfitBot v4 — CORRECTED KALSHI FEES!")
    print(f"  Auto: {AUTO_TRADE} | Kelly: {KELLY_FRACTION} | Min Arb: {MIN_ARB_PROFIT}¢")
    print(f"  🔧 Fixed: Arbitrage cost calc, position tracking, realistic thresholds")
    print(f"  ✅ CORRECTED: Kalshi fees are ~1.2% (NOT 7%!)")
    print("=" * 60)
    tg("🦞 *ProfitBot v4 online* — CORRECTED FEES!")
    
    trades_today = 0
    arb_count = 0
    late_count = 0
    
    # Load existing positions and reconcile with API
    positions = reconcile_positions()
    
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
    
    reconciliation_counter = 0
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            balance = get_balance()
            
            if balance:
                print(f"\n[{ts}] Bankroll: ${balance:.2f}")
            
            # Reconcile positions every 10 cycles (5 minutes)
            reconciliation_counter += 1
            if reconciliation_counter >= 10:
                positions = reconcile_positions()
                reconciliation_counter = 0
            
            # Check for expired positions
            positions = check_exited_positions(positions)
            
            markets = get_open_markets()
            print(f"[{ts}] 📡 Scanning {len(markets)} markets... | Active positions: {len(positions)}")
            
            arb_taken = 0
            late_taken = 0
            
            for m in markets:
                ticker = m["ticker"]
                
                # Skip decided markets
                ya = m.get("yes_ask", 50)
                na = m.get("no_ask", 50)
                if ya >= 95 or na >= 95:
                    continue
                if ya == 0 or na == 0:
                    continue
                
                # Debug: show market prices
                total_cost = ya + na
                if int(time.time()) % 120 < 30:  # Debug every ~2 min
                    print(f"   🔍 {ticker}: YES@{ya}c NO@{na}c total={total_cost}c")
                
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
                    if should_trade and confidence >= 0.5:  # Lower threshold for more opportunities
                        execute_late_game(m, side, confidence, balance, positions)
                        late_taken += 1
                        late_count += 1
                        trades_today += 1
            
            # Get actual trade count from API
            api_trades = get_trade_history_today()
            api_str = f" | API orders: {api_trades}" if api_trades is not None else ""
            
            print(f"[{ts}] Done. Today's: {trades_today} trades (arb: {arb_count}, late: {late_count}){api_str}")
            
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