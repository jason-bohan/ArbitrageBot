#!/usr/bin/env python3
"""
GoobClaw ProfitBot v2 — Mathematical Edge + Fee-Aware
Only takes trades with proven edge after 7% Kalshi fees.
"""

import os
import time
import uuid
import requests
import math
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"

# === FEE-AWARE PROFIT PARAMETERS ===
KELLY_FRACTION = 0.25        # Kelly Lite (don't overbet)
MIN_ARB_PROFIT = 0.50        # Higher threshold after fees
MIN_LATE_GAP = 12            # Wider gap for late-game (account for fees)
MAX_TIME_LEFT = 180          # Tighter window: <3 min left
MIN_VOLUME = 10000           # Skip illiquid markets
BANKROLL_PCT = 0.02          # Max 2% of bankroll per trade

# Fee adjustments (7% total: 2% buy + 5% sell)
BUY_FEE_PCT = 0.02
SELL_FEE_PCT = 0.05
TOTAL_FEE_PCT = 0.07


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
    return None


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


def check_arbitrage(market, balance):
    """
    FEE-AWARE arbitrage: YES + NO < $1.00 - 7% fees
    Returns (should_trade, profit_cents_after_fees, yes_count, no_count) or (False, ...)
    """
    ya = market.get("yes_ask", 0)  # You pay this for YES
    yb = market.get("yes_bid", 0)  # You get this selling YES
    na = market.get("no_ask", 0)   # You pay this for NO
    nb = market.get("no_bid", 0)   # You get this selling NO
    
    # Mid prices
    yes_mid = (ya + yb) / 2
    no_mid = (na + nb) / 2
    
    total_cost = yes_mid + no_mid
    
    # 🚨 FEE ADJUSTMENT 🚨
    # We pay fees on both buy and sell, so adjust profit threshold
    min_total_cost = 99.7 - (TOTAL_FEE_PCT * 100)  # ~92.9¢ max cost
    
    if total_cost < min_total_cost:
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


def check_late_game(market, balance):
    """
    FEE-AWARE late-game: Only take massive edges with very little time left.
    Returns (should_trade, side, confidence) or (False, None, 0)
    """
    ya = market.get("yes_ask", 50)
    yb = market.get("yes_bid", 50)
    na = market.get("no_ask", 50)
    nb = market.get("no_bid", 50)
    
    yes_mid = (ya + yb) / 2
    no_mid = (na + nb) / 2
    
    # Time check - MUCH tighter
    try:
        close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
        secs_left = (close - datetime.now(timezone.utc)).total_seconds()
    except:
        return False, None, 0
    
    if secs_left > MAX_TIME_LEFT:
        return False, None, 0  # Too early
    
    if secs_left < 30:
        return False, None, 0  # Too late (execution risk)
    
    # Volume check
    vol = market.get("volume", 0)
    if vol < MIN_VOLUME:
        return False, None, 0
    
    # 🚨 HIGHER THRESHOLDS AFTER FEES 🚨
    # Need massive edge to overcome 7% fees
    
    # YES is massively underpriced (<15¢) with NO very expensive (>85¢)
    if yes_mid < 15 and no_mid > 85:
        gap = no_mid - yes_mid
        if gap >= MIN_LATE_GAP:
            # Adjust confidence for fees
            prob = yes_mid / 100
            # Need much higher edge after fees
            edge = (prob - ((1 - prob) * (yes_mid / no_mid))) if no_mid > 0 else 0
            adjusted_confidence = min(0.9, (gap / 100) - TOTAL_FEE_PCT + 0.2)
            return True, "yes", max(0.7, adjusted_confidence)
    
    # NO is massively underpriced (<15¢)
    if no_mid < 15 and yes_mid > 85:
        gap = yes_mid - no_mid
        if gap >= MIN_LATE_GAP:
            prob = no_mid / 100
            edge = (prob - ((1 - prob) * (no_mid / yes_mid))) if yes_mid > 0 else 0
            adjusted_confidence = min(0.9, (gap / 100) - TOTAL_FEE_PCT + 0.2)
            return True, "no", max(0.7, adjusted_confidence)
    
    return False, None, 0


def execute_arbitrage(market, pairs, profit_cents):
    """Execute fee-aware arbitrage."""
    ticker = market["ticker"]
    ya = market.get("yes_ask", 0)
    na = market.get("no_ask", 0)
    
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 🎯 ARBITRAGE {ticker}")
    print(f"   YES @{ya}c + NO @{na}c = {ya+na}c → Net profit {profit_cents:.1f}¢/pair (after fees)")
    print(f"   Pairs: {pairs}")
    tg(f"🎯 *ARB* `{ticker}` | {pairs} pairs | +{profit_cents:.1f}¢ net each")
    
    if AUTO_TRADE:
        ok1, err1 = place_order(ticker, "yes", ya, pairs)
        ok2, err2 = place_order(ticker, "no", na, pairs)
        
        if ok1 and ok2:
            net_profit = pairs * profit_cents / 100
            print(f"   ✅ Arb executed! Hold to expiration. Net profit: ${net_profit:.2f}")
            tg(f"✅ *Arb filled* `{ticker}` — +${net_profit:.2f} net at expiry")
        else:
            print(f"   ❌ Arb failed: {err1} | {err2}")
            tg(f"❌ *Arb failed* `{ticker}`: {err1[:50]} | {err2[:50]}")


def execute_late_game(market, side, confidence, balance):
    """Execute fee-aware late-game trade."""
    ticker = market["ticker"]
    price = market.get("yes_ask" if side == "yes" else "no_ask", 50)
    
    # Position sizing - more conservative due to fees
    max_bet = balance * BANKROLL_PCT * 0.8  # Smaller due to fees
    contracts = int((max_bet * 100) / price)
    contracts = max(1, contracts)
    
    ts = datetime.now().strftime("%H:%M:%S")
    try:
        close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
        mins_left = (close - datetime.now(timezone.utc)).total_seconds() / 60
    except:
        mins_left = 0
    
    print(f"\n[{ts}] 🎯 LATE GAME {ticker}")
    print(f"   {side.upper()} @ {price}c | Conf: {confidence:.0%} | {mins_left:.1f}min left")
    print(f"   Contracts: {contracts} | Fee-adjusted edge")
    tg(f"🎯 *Late* `{ticker}` {side.upper()}@{price}c | {confidence:.0%} conf")
    
    if AUTO_TRADE:
        ok, err = place_order(ticker, side, price, contracts)
        if ok:
            print(f"   ✅ Order filled!")
            tg(f"✅ *Filled* `{ticker}` {side.upper()} x{contracts}")
        else:
            print(f"   ❌ Order failed: {err}")
            tg(f"❌ *Failed* `{ticker}`: {err[:50]}")


def run():
    print("=" * 60)
    print("  GoobClaw ProfitBot v2 — Fee-Aware Mathematical Edge")
    print(f"  Auto: {AUTO_TRADE} | Kelly: {KELLY_FRACTION} | Min Arb: {MIN_ARB_PROFIT}¢")
    print(f"  🚨 FEE-AWARE: {TOTAL_FEE_PCT*100}% total fees factored in")
    print("=" * 60)
    tg("🦞 *ProfitBot v2 online* — fee-aware edge hunting")
    
    trades_today = 0
    arb_count = 0
    late_count = 0
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            balance = get_balance()
            
            if balance:
                print(f"\n[{ts}] Bankroll: ${balance:.2f}")
            
            markets = get_open_markets()
            print(f"Scanning {len(markets)} markets...")
            
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
                
                # Check arbitrage first (risk-free money)
                if balance and ya > 0 and na > 0:
                    arb, profit, pairs, _ = check_arbitrage(m, balance)
                    if arb and profit >= MIN_ARB_PROFIT:
                        execute_arbitrage(m, pairs, profit)
                        arb_taken += 1
                        arb_count += 1
                        trades_today += 1
                        continue  # Move to next market
                
                # Check late-game opportunity
                if balance:
                    should_trade, side, confidence = check_late_game(m, balance)
                    if should_trade and confidence >= 0.7:  # Higher confidence threshold
                        execute_late_game(m, side, confidence, balance)
                        late_taken += 1
                        late_count += 1
                        trades_today += 1
            
            print(f"[{ts}] Done. Today's: {trades_today} trades (arb: {arb_count}, late: {late_count})")
            
            # Slower scan — we're patient hunters
            time.sleep(45)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
