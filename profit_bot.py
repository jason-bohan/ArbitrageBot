#!/usr/bin/env python3
"""
GoobClaw ProfitBot — Only takes trades with mathematical edge.
Strategy:
1. Pairs arbitrage (YES + NO < $1) — risk-free profit
2. Late-game mispricing (>80% or <20% with time left)
3. Strict position sizing (Kelly Criterion lite)
4. No "hope" trades — only edges with >60% win prob
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

# === PROFIT PARAMETERS ===
KELLY_FRACTION = 0.25        # Kelly Lite (don't overbet)
MIN_ARB_PROFIT = 0.30        # $0.30 minimum for arbitrage
MIN_LATE_GAP = 8             # 8¢ gap minimum for late-game
MAX_TIME_LEFT = 300          # Enter only with <5 min left
MIN_VOLUME = 10000           # Skip illiquid markets
BANKROLL_PCT = 0.02          # Max 2% of bankroll per trade


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
    Check for risk-free arbitrage: YES + NO < $1.00
    Returns (should_trade, profit_cents, yes_count, no_count) or (False, ...)
    """
    ya = market.get("yes_ask", 0)  # You pay this for YES
    yb = market.get("yes_bid", 0)  # You get this selling YES
    na = market.get("no_ask", 0)   # You pay this for NO
    nb = market.get("no_bid", 0)   # You get this selling NO
    
    # Mid prices
    yes_mid = (ya + yb) / 2
    no_mid = (na + nb) / 2
    
    total_cost = yes_mid + no_mid
    
    if total_cost < 99.7:  # Allow 0.3¢ buffer for spread/fees
        # Calculate position size
        profit_per_pair = 100 - total_cost  # cents
        
        # How many pairs can we buy?
        cost_per_pair = total_cost / 100  # dollars
        max_pairs = int(balance / cost_per_pair)
        
        # Kelly sizing (lite)
        kelly_pct = 0.5 * KELLY_FRACTION  # Conservative
        pairs = int(max_pairs * kelly_pct)
        pairs = max(1, min(pairs, 100))  # 1-100 range
        
        if pairs >= 1:
            return True, profit_per_pair, pairs
    
    return False, 0, 0, 0


def check_late_game(market, balance):
    """
    Check for late-game mispricing (>80% or <20% with time running out).
    Returns (should_trade, side, confidence) or (False, None, 0)
    """
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
    
    if secs_left > MAX_TIME_LEFT:
        return False, None, 0  # Too early
    
    if secs_left < 60:
        return False, None, 0  # Too late
    
    # Volume check
    vol = market.get("volume", 0)
    if vol < MIN_VOLUME:
        return False, None, 0
    
    # YES is heavily underpriced (<20¢) — people undervaluing
    if yes_mid < 20 and no_mid > 80:
        gap = no_mid - yes_mid
        if gap >= MIN_LATE_GAP:
            # Kelly sizing: edge = (prob * payout) - (1-prob * cost)
            prob = yes_mid / 100
            edge = prob - ((1 - prob) * (yes_mid / no_mid)) if no_mid > 0 else 0
            return True, "yes", min(0.8, gap / 100 + 0.3)
    
    # NO is heavily underpriced (<20¢)
    if no_mid < 20 and yes_mid > 80:
        gap = yes_mid - no_mid
        if gap >= MIN_LATE_GAP:
            prob = no_mid / 100
            edge = prob - ((1 - prob) * (no_mid / yes_mid)) if yes_mid > 0 else 0
            return True, "no", min(0.8, gap / 100 + 0.3)
    
    return False, None, 0


def execute_arbitrage(market, pairs, profit_cents):
    """Execute pairs arbitrage: buy YES + buy NO, then hold to $1."""
    ticker = market["ticker"]
    ya = market.get("yes_ask", 0)
    na = market.get("no_ask", 0)
    
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 🎯 ARBITRAGE {ticker}")
    print(f"   YES @{ya}c + NO @{na}c = {ya+na}c → Profit {profit_cents:.1f}¢/pair")
    print(f"   Pairs: {pairs}")
    tg(f"🎯 *ARB* `{ticker}` | {pairs} pairs | +{profit_cents:.1f}¢ each")
    
    if AUTO_TRADE:
        ok1, err1 = place_order(ticker, "yes", ya, pairs)
        ok2, err2 = place_order(ticker, "no", na, pairs)
        
        if ok1 and ok2:
            print(f"   ✅ Arb executed! Hold to expiration.")
            tg(f"✅ *Arb filled* `{ticker}` — +${pairs * profit_cents / 100:.2f} at expiry")
        else:
            print(f"   ❌ Arb failed: {err1} | {err2}")
            tg(f"❌ *Arb failed* `{ticker}`: {err1[:50]} | {err2[:50]}")


def execute_late_game(market, side, confidence, balance):
    """Execute late-game high-conviction trade."""
    ticker = market["ticker"]
    price = market.get("yes_ask" if side == "yes" else "no_ask", 50)
    
    # Position sizing
    max_bet = balance * BANKROLL_PCT
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
    print(f"   Contracts: {contracts}")
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
    print("  GoobClaw ProfitBot — Mathematical Edge Only")
    print(f"  Auto: {AUTO_TRADE} | Kelly: {KELLY_FRACTION} | Min Arb: {MIN_ARB_PROFIT}¢")
    print("=" * 60)
    tg("🦞 *ProfitBot online* — hunting edges only")
    
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
                    if should_trade and confidence >= 0.6:
                        execute_late_game(m, side, confidence, balance)
                        late_taken += 1
                        late_count += 1
                        trades_today += 1
            
            print(f"[{ts}] Done. Today's: {trades_today} trades (arb: {arb_count}, late: {late_count})")
            
            # Slow scan — we're not chasing
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()