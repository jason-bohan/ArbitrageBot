#!/usr/bin/env python3
"""
GoobClaw Flipper — Ratchet Scalper
Enters a position, stops out at -2c and flips to the other side.
Max loss per cycle: 4c. Upside when you catch the right side near expiry: 30-40c+.
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

STOP_LOSS_CENTS  = 2     # flip when down this many cents from entry
TAKE_PROFIT_CENTS = 3    # take profit at +3c
CONTRACTS        = 1     # start with 1 contract, scale up as confidence grows
MIN_ENTRY_SECS   = 600   # only enter if at least 10 min left (avoid entering at expiry)
MAX_ENTRY_SECS   = 780   # don't enter more than 13 min before close (skip new markets)
MAX_ENTRY_PRICE  = 75    # don't buy a side if it's already >75c (too late, bad risk/reward)
AUTO_TRADE       = os.getenv("AUTO_TRADE", "true").lower() == "true"

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
    try:
        res = requests.get(
            COINGECKO_URL,
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=8
        )
        if res.status_code == 200:
            return res.json()[coin_id]["usd"]
    except:
        pass
    return None


def get_market(series_ticker):
    path = f"/trade-api/v2/markets?series_ticker={series_ticker}&status=open&limit=1"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            markets = res.json().get("markets", [])
            if markets:
                return markets[0]
    except:
        pass
    return None


def seconds_to_close(close_time_str):
    try:
        ct = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        return (ct - datetime.now(timezone.utc)).total_seconds()
    except:
        return None


def get_balance():
    path = "/trade-api/v2/portfolio/balance"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except:
        pass
    return None


def get_position(ticker):
    """Get our current position size for a ticker."""
    path = f"/trade-api/v2/portfolio/positions?ticker={ticker}"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        if res.status_code == 200:
            positions = res.json().get("market_positions", [])
            for p in positions:
                if p.get("ticker") == ticker:
                    return p.get("position", 0)  # positive = YES, negative = NO
    except:
        pass
    return 0


def place_order(ticker, side, price_cents, count=1):
    """Place a limit order. Returns (success, fill_price_or_error)."""
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
            return True, price_cents
        else:
            return False, res.text
    except Exception as e:
        return False, str(e)


def sell_position(ticker, side, price_cents, count=1):
    """Sell (exit) an existing position."""
    path = "/trade-api/v2/portfolio/orders"
    payload = {
        "action": "sell",
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
            return True, price_cents
        else:
            return False, res.text
    except Exception as e:
        return False, str(e)


def pick_side(market, live_price):
    """Choose YES or NO based on current price vs floor_strike."""
    floor = market.get("floor_strike", 0)
    if not floor or not live_price:
        return None, None, None
    if live_price >= floor:
        return "yes", market.get("yes_ask", 50), live_price - floor
    else:
        return "no", market.get("no_ask", 50), floor - live_price


def opposite(side):
    return "no" if side == "yes" else "yes"


def get_current_price(market, side):
    """Get current ask price for a side."""
    if side == "yes":
        return market.get("yes_ask", 0)
    return market.get("no_ask", 0)


def get_sell_price(market, side):
    """Get current bid price for a side (what we'd receive when selling)."""
    if side == "yes":
        return market.get("yes_bid", 0)
    return market.get("no_bid", 0)


class Position:
    def __init__(self, ticker, side, entry_price, contracts):
        self.ticker = ticker
        self.side = side
        self.entry_price = entry_price
        self.contracts = contracts
        self.flips = 0
        self.total_loss = 0
        self.entered_at = time.time()

    def __str__(self):
        return (f"{self.side.upper()} @ {self.entry_price}¢ "
                f"({self.contracts} contracts, {self.flips} flips, "
                f"total loss so far: {self.total_loss}¢)")


def run_market(series, coin_id):
    """
    Run the flipper for one market cycle.
    Returns when the market expires or we exit.
    """
    market = get_market(series)
    if not market:
        return

    ticker = market["ticker"]
    secs = seconds_to_close(market["close_time"])

    if secs is None or not (MIN_ENTRY_SECS < secs < MAX_ENTRY_SECS):
        return  # Not in our entry window

    live_price = get_live_price(coin_id)
    if not live_price:
        return

    side, entry_ask, edge = pick_side(market, live_price)
    if not side or not entry_ask:
        return

    if entry_ask > MAX_ENTRY_PRICE:
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] ⏭️  {series} skip — {side.upper()} @ {entry_ask}¢ too expensive (>{MAX_ENTRY_PRICE}¢)")
        return

    floor = market.get("floor_strike", 0)
    ts = datetime.now().strftime("%H:%M:%S")

    print(f"\n[{ts}] 🎯 {series} | Entering {side.upper()} @ {entry_ask}¢")
    print(f"       Live: ${live_price:,.2f} | Strike: ${floor:,.2f} | {secs:.0f}s left")

    if AUTO_TRADE:
        ok, result = place_order(ticker, side, entry_ask, CONTRACTS)
        if not ok:
            print(f"       ❌ Entry failed: {result}")
            return

    pos = Position(ticker, side, entry_ask, CONTRACTS)
    tg(f"🎯 *Flipper entered* `{ticker}`\n{side.upper()} @ {entry_ask}¢ | {secs:.0f}s left")

    # --- Monitor loop ---
    while True:
        time.sleep(3)

        market = get_market(series)
        if not market or market["ticker"] != ticker:
            # Market expired or changed
            print(f"  ✅ Market closed. Final P&L: {-pos.total_loss}¢ base + exit")
            tg(f"✅ `{ticker}` closed.\nFlips: {pos.flips} | Base loss: {pos.total_loss}¢")
            return

        secs = seconds_to_close(market["close_time"])
        if secs is not None and secs <= 0:
            print("  ⏰ Expired.")
            return

        sell_px = get_sell_price(market, pos.side)
        ask_px  = get_current_price(market, pos.side)
        current_pnl = sell_px - pos.entry_price  # what we'd net right now

        ts = datetime.now().strftime("%H:%M:%S")

        # Take profit
        if current_pnl >= TAKE_PROFIT_CENTS:
            print(f"  [{ts}] 💰 Take profit! +{current_pnl}¢ | sell {pos.side.upper()} @ {sell_px}¢")
            if AUTO_TRADE:
                sell_position(ticker, pos.side, sell_px, pos.contracts)
            net = current_pnl - pos.total_loss
            tg(f"💰 *Take profit!* `{ticker}`\n+{current_pnl}¢ this leg | Net after flips: {net:+}¢")
            return

        # Stop loss → flip
        if current_pnl <= -STOP_LOSS_CENTS:
            loss = pos.entry_price - sell_px
            pos.total_loss += loss
            pos.flips += 1

            new_side = opposite(pos.side)
            new_market = get_market(series)  # refresh
            if new_market:
                new_entry = get_current_price(new_market, new_side)
            else:
                new_entry = 100 - sell_px  # estimate

            print(f"  [{ts}] 🔄 Stop hit! -{loss}¢ | Flipping to {new_side.upper()} @ {new_entry}¢")
            print(f"         Total flips: {pos.flips} | Cumulative loss: {pos.total_loss}¢")

            if AUTO_TRADE:
                # Sell current side
                sell_position(ticker, pos.side, sell_px, pos.contracts)
                time.sleep(1)
                # Buy opposite
                ok, result = place_order(ticker, new_side, new_entry, pos.contracts)
                if not ok:
                    print(f"         ❌ Flip entry failed: {result}")
                    tg(f"❌ Flip failed on `{ticker}`: {result}")
                    return

            tg(
                f"🔄 *Flip!* `{ticker}`\n"
                f"Stopped {pos.side.upper()} at -{loss}¢\n"
                f"→ {new_side.upper()} @ {new_entry}¢\n"
                f"Flip #{pos.flips} | Total lost so far: {pos.total_loss}¢"
            )

            pos.side = new_side
            pos.entry_price = new_entry

        else:
            # Just watching
            if int(time.time()) % 30 == 0:  # print every 30s
                print(f"  [{ts}] {pos.side.upper()} @ {pos.entry_price}¢ → now {sell_px}¢ ({current_pnl:+}¢) | {secs:.0f}s left")


def run():
    print("=" * 60)
    print("  GoobClaw Flipper — Ratchet Scalper")
    print(f"  Stop: -{STOP_LOSS_CENTS}¢ | Target: +{TAKE_PROFIT_CENTS}¢ | Max loss/cycle: ~4¢")
    print(f"  Entry window: {MIN_ENTRY_SECS//60}-{MAX_ENTRY_SECS//60} min before close")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)

    tg("🦞 *Flipper starting* — stop -2¢, target +3¢, max loss ~4¢/cycle")

    active = {}  # series → ticker being traded

    while True:
        try:
            for series, coin_id in SERIES.items():
                if series in active:
                    continue  # already in a trade for this series
                run_market(series, coin_id)

            time.sleep(15)

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] Error: {e}")
            time.sleep(15)


if __name__ == "__main__":
    run()
