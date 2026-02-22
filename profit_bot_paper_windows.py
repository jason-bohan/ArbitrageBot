#!/usr/bin/env python3
"""
GoobClaw ProfitBot v3 — Paper Trading Mode (Windows Friendly)
Forces paper trading mode regardless of .env file.
"""

import os
import sys
import time
import uuid
import requests
import math
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

# 🚨 FORCE PAPER TRADING MODE 🚨
AUTO_TRADE = False  # Hardcoded to false for paper trading

BASE_URL = "https://api.elections.kalshi.com"

# === PAPER TRADING PARAMETERS ===
KELLY_FRACTION = 0.25        
MIN_ARB_PROFIT = 0.50        
MIN_LATE_GAP = 12            
MAX_TIME_LEFT = 180          
MIN_VOLUME = 10000           
BANKROLL_PCT = 0.02          

# Fee adjustments
BUY_FEE_PCT = 0.02
SELL_FEE_PCT = 0.05
TOTAL_FEE_PCT = 0.07

# Paper trading log file
PAPER_LOG = "profit_bot_paper_trades.log"
PAPER_JSON = "profit_bot_paper_results.json"


def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",
            json={"chat_id": os.getenv('JASON_CHAT_ID'), "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
    except:
        pass


def log_paper_trade(trade_type, ticker, details, pnl_cents=0):
    """Log paper trade with timestamp and results."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_entry = {
        "timestamp": timestamp,
        "type": trade_type,
        "ticker": ticker,
        "details": details,
        "pnl_cents": pnl_cents,
        "status": "opportunity" if pnl_cents == 0 else ("profit" if pnl_cents > 0 else "loss")
    }
    
    # Write to log file
    with open(PAPER_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {trade_type.upper()}: {ticker} | {details} | P&L: {pnl_cents:+.1f}¢\n")
    
    # Save to JSON for analysis
    try:
        with open(PAPER_JSON, "r") as f:
            trades = json.load(f)
    except:
        trades = []
    
    trades.append(log_entry)
    
    with open(PAPER_JSON, "w") as f:
        json.dump(trades, f, indent=2)
    
    print(f"📝 Logged: {trade_type} {ticker} | P&L: {pnl_cents:+.1f}¢")


def get_balance():
    try:
        path = "/trade-api/v2/portfolio/balance"
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        res.raise_for_status()
        return res.json().get("balance", 0) / 100
    except:
        pass
    return None


def get_market(ticker):
    path = f"/trade-api/v2/markets/{ticker}"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=5)
        res.raise_for_status()
        return res.json().get("market", {})
    except:
        pass
    return None


def get_open_markets():
    now = datetime.now(timezone.utc)
    path = f"/trade-api/v2/markets?status=open&limit=200"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=15)
        res.raise_for_status()
        return res.json().get("markets", [])
    except:
        pass
    return []


def check_arbitrage(market, balance):
    ya = market.get("yes_ask", 0)
    yb = market.get("yes_bid", 0)
    na = market.get("no_ask", 0)
    nb = market.get("no_bid", 0)
    
    yes_mid = (ya + yb) / 2
    no_mid = (na + nb) / 2
    total_cost = yes_mid + no_mid
    
    min_total_cost = 99.7 - (TOTAL_FEE_PCT * 100)
    
    if total_cost < min_total_cost:
        gross_profit_per_pair = 100 - total_cost
        fee_cost_per_pair = gross_profit_per_pair * TOTAL_FEE_PCT
        net_profit_per_pair = gross_profit_per_pair - fee_cost_per_pair
        
        if net_profit_per_pair >= MIN_ARB_PROFIT:
            cost_per_pair = total_cost / 100
            max_pairs = int(balance / cost_per_pair)
            kelly_pct = 0.5 * KELLY_FRACTION
            pairs = int(max_pairs * kelly_pct)
            pairs = max(1, min(pairs, 100))
            
            if pairs >= 1:
                return True, net_profit_per_pair, pairs
    
    return False, 0, 0


def check_late_game(market, balance):
    ya = market.get("yes_ask", 50)
    yb = market.get("yes_bid", 50)
    na = market.get("no_ask", 50)
    nb = market.get("no_bid", 50)
    
    yes_mid = (ya + yb) / 2
    no_mid = (na + nb) / 2
    
    try:
        close = datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
        secs_left = (close - datetime.now(timezone.utc)).total_seconds()
    except:
        return False, None, 0
    
    if secs_left > MAX_TIME_LEFT or secs_left < 30:
        return False, None, 0
    
    vol = market.get("volume", 0)
    if vol < MIN_VOLUME:
        return False, None, 0
    
    if yes_mid < 15 and no_mid > 85:
        gap = no_mid - yes_mid
        if gap >= MIN_LATE_GAP:
            prob = yes_mid / 100
            edge = (prob - ((1 - prob) * (yes_mid / no_mid))) if no_mid > 0 else 0
            adjusted_confidence = min(0.9, (gap / 100) - TOTAL_FEE_PCT + 0.2)
            return True, "yes", max(0.7, adjusted_confidence)
    
    if no_mid < 15 and yes_mid > 85:
        gap = yes_mid - no_mid
        if gap >= MIN_LATE_GAP:
            prob = no_mid / 100
            edge = (prob - ((1 - prob) * (no_mid / yes_mid))) if yes_mid > 0 else 0
            adjusted_confidence = min(0.9, (gap / 100) - TOTAL_FEE_PCT + 0.2)
            return True, "no", max(0.7, adjusted_confidence)
    
    return False, None, 0


def simulate_arbitrage(market, pairs, profit_cents):
    """Simulate arbitrage and track result."""
    ticker = market["ticker"]
    ya = market.get("yes_ask", 0)
    na = market.get("no_ask", 0)
    
    ts = datetime.now().strftime("%H:%M:%S")
    total_net_profit = pairs * profit_cents / 100
    
    details = f"ARB: YES@{ya}c + NO@{na}c = {ya+na}c | {pairs} pairs | Net: +{profit_cents:.1f}¢/pair"
    
    print(f"\n[{ts}] 🎯 PAPER ARBITRAGE {ticker}")
    print(f"   {details}")
    print(f"   💰 PAPER PROFIT: +${total_net_profit:.2f} (would hold to expiry)")
    
    # Log the opportunity
    log_paper_trade("arbitrage", ticker, details, pairs * profit_cents)
    
    # Check if it actually would have been profitable (simulate expiry)
    # For paper trading, we assume it resolves correctly since it's arbitrage
    tg(f"📝 *Paper ARB* `{ticker}` | {pairs} pairs | +${total_net_profit:.2f} hypothetical")


def simulate_late_game(market, side, confidence, balance):
    """Simulate late-game trade and track result."""
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
    
    # Simulate outcome based on confidence
    import random
    won = random.random() < confidence  # Simulate based on confidence
    
    if won:
        # Win: get $1.00 per contract, minus cost and fees
        gross_profit = (100 - price) * contracts / 100
        fees = gross_profit * TOTAL_FEE_PCT
        net_profit = gross_profit - fees
        pnl_cents = net_profit * 100
        result_text = f"WON +${net_profit:.2f}"
    else:
        # Lose: lose the cost
        cost = price * contracts / 100
        fees = cost * BUY_FEE_PCT
        net_loss = cost + fees
        pnl_cents = -net_loss * 100
        result_text = f"LOST -${net_loss:.2f}"
    
    details = f"LATE: {side.upper()}@{price}c | {contracts} contracts | {confidence:.0%} conf | {mins_left:.1f}min"
    
    print(f"\n[{ts}] 🎯 PAPER LATE GAME {ticker}")
    print(f"   {details}")
    print(f"   🎲 SIMULATED: {result_text}")
    
    # Log the trade
    log_paper_trade("late_game", ticker, f"{details} | {result_text}", pnl_cents)
    
    tg(f"📝 *Paper Late* `{ticker}` {side.upper()} | {result_text}")


def show_paper_stats():
    """Show paper trading statistics."""
    try:
        with open(PAPER_JSON, "r") as f:
            trades = json.load(f)
    except:
        print("No paper trades yet.")
        return
    
    if not trades:
        print("No paper trades yet.")
        return
    
    # Calculate stats
    total_trades = len(trades)
    arb_trades = [t for t in trades if t["type"] == "arbitrage"]
    late_trades = [t for t in trades if t["type"] == "late_game"]
    
    arb_profits = sum(t["pnl_cents"] for t in arb_trades)
    late_profits = sum(t["pnl_cents"] for t in late_trades)
    total_profits = arb_profits + late_profits
    
    wins = len([t for t in trades if t["pnl_cents"] > 0])
    losses = len([t for t in trades if t["pnl_cents"] < 0])
    
    print(f"\n📊 PAPER TRADING STATS:")
    print(f"   Total Trades: {total_trades}")
    print(f"   Arbitrage: {len(arb_trades)} trades | +${arb_profits/100:.2f}")
    print(f"   Late Game: {len(late_trades)} trades | ${late_profits/100:.2f}")
    print(f"   Total P&L: ${total_profits/100:.2f}")
    print(f"   Win Rate: {wins}/{total_trades} = {wins/total_trades*100:.1f}%")
    
    if total_trades > 0:
        avg_profit = total_profits / total_trades
        print(f"   Avg Profit/Trade: {avg_profit:.1f}¢")


def run():
    print("=" * 60)
    print("  GoobClaw ProfitBot v3 — Paper Trading Mode (Windows)")
    print(f"  🚨 PAPER TRADING ONLY - No real money will be traded")
    print(f"  Kelly: {KELLY_FRACTION} | Min Arb: {MIN_ARB_PROFIT}¢")
    print(f"  📝 PAPER TRADING: No real money, detailed logging")
    print(f"  📊 Log: {PAPER_LOG}")
    print("=" * 60)
    tg("🦞 *ProfitBot v3 online* — Paper trading mode (Windows)")
    
    trades_today = 0
    arb_count = 0
    late_count = 0
    
    # Show existing stats
    show_paper_stats()
    
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
                
                ya = m.get("yes_ask", 50)
                na = m.get("no_ask", 50)
                if ya >= 95 or na >= 95 or ya == 0 or na == 0:
                    continue
                
                # Check arbitrage
                if balance and ya > 0 and na > 0:
                    arb, profit, pairs, _ = check_arbitrage(m, balance)
                    if arb and profit >= MIN_ARB_PROFIT:
                        simulate_arbitrage(m, pairs, profit)
                        arb_taken += 1
                        arb_count += 1
                        trades_today += 1
                        continue
                
                # Check late-game
                if balance:
                    should_trade, side, confidence = check_late_game(m, balance)
                    if should_trade and confidence >= 0.7:
                        simulate_late_game(m, side, confidence, balance)
                        late_taken += 1
                        late_count += 1
                        trades_today += 1
            
            print(f"[{ts}] Done. Today's: {trades_today} trades (arb: {arb_count}, late: {late_count})")
            
            # Show updated stats every hour
            if int(time.time()) % 3600 < 45:  # Roughly every hour
                show_paper_stats()
            
            time.sleep(45)
            
        except KeyboardInterrupt:
            print("\nStopped.")
            show_paper_stats()
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
