#!/usr/bin/env python3
"""
GoobClaw Flipper v3 INVERSE — Fade the Rip
Strategy: Buy rips, sell dips, hold ABOVE 67, quick exits BELOW 67.
Opposite of v3: enters high, exits on drops, holds high prices to settlement.
Target: -10c per swing captured (buy high, sell higher OR hold to zero if wrong).
"""

import os
import time
import uuid
import requests
import numpy as np
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

# === FLIPPER V3 INVERSE PARAMETERS ===
# Original bought LOW (20-80), we buy HIGH (20-80 on the NO side = 20-80 YES reversed)
SWING_TARGET = 10       # Capture 10c per swing
MIN_ENTRY_PRICE = 20    # Enter on rips above 80 YES = buy NO at 20
MAX_ENTRY_PRICE = 80    # Enter on rips — buy NO when YES is high (NO is cheap)
RISK_THRESHOLD = 33     # INVERTED: Below this on YES (=above 67 on NO): hold to settlement
                        # Above this on YES (=below 67 on NO): trade actively / exit quick
MIN_SECS_LEFT = 300     # Never enter with <5 min left
MAX_SECS_LEFT = 840     # Up to 14 min before close
MAX_SPREAD = 4          # Skip illiquid markets
FIXED_CONTRACTS = 1     # Fixed size (set to 0 to enable auto-scale)
AUTO_TRADE = os.getenv("AUTO_TRADE", "true").lower() == "true"
TELEGRAM_TOKEN = "8327315190:AAGBDny1KAk9m27YOCGmxD2ElQofliyGdLI"
JASON_CHAT_ID = "7478453115"

COIN_MAP = {"KXBTC15M": "bitcoin", "KXETH15M": "ethereum"}


def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": JASON_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=8
        )
    except:
        pass


def secs_left(close_time_str):
    try:
        ct = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        return (ct - datetime.now(timezone.utc)).total_seconds()
    except:
        return None


def get_balance():
    path = "/trade-api/v2/portfolio/balance"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        print(f"  🌐 GET {path} → {res.status_code} {'✅' if res.status_code == 200 else '❌'}")
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except Exception as e:
        print(f"  🌐 GET {path} → ⚠️ {e}")
    return None


def get_pnl_summary():
    """Fetch realized P&L from settlements."""
    sig_path = "/trade-api/v2/portfolio/settlements"
    try:
        res = requests.get(BASE_URL + sig_path, headers=get_kalshi_headers("GET", sig_path), timeout=10)
        settlements = res.json().get("settlements", []) if res.status_code == 200 else []
    except:
        settlements = []

    total_revenue = sum(s.get("revenue", 0) for s in settlements)
    total_cost = sum(s.get("yes_total_cost", 0) + s.get("no_total_cost", 0) for s in settlements)
    total_fees = sum(float(s.get("fee_cost", 0)) for s in settlements)
    realized_pnl = (total_revenue - total_cost) / 100

    wins = sum(1 for s in settlements if s.get("revenue", 0) > (s.get("yes_total_cost", 0) + s.get("no_total_cost", 0)))
    losses = len(settlements) - wins
    win_rate = (wins / len(settlements) * 100) if settlements else 0

    balance = get_balance()

    print("\n" + "=" * 50)
    print(" 📊 P&L SUMMARY")
    print("=" * 50)
    print(f" Balance: ${balance:.2f}" if balance else " Balance: N/A")
    print(f" Settled trades: {len(settlements)}")
    print(f" Wins/Losses: {wins}W / {losses}L ({win_rate:.1f}% win rate)")
    print(f" Realized P&L: ${realized_pnl:.2f}")
    print(f" Fees paid: ${total_fees:.2f}")
    print(f" Net after fees: ${realized_pnl - total_fees:.2f}")
    print("=" * 50 + "\n")

    return realized_pnl, win_rate


def get_trade_outcomes(limit=20):
    """Show individual trade outcomes by cross-referencing fills with settlements."""
    sig_path_fills = "/trade-api/v2/portfolio/fills"
    sig_path_sett = "/trade-api/v2/portfolio/settlements"

    try:
        fills_res = requests.get(BASE_URL + sig_path_fills + f"?limit={limit}", headers=get_kalshi_headers("GET", sig_path_fills), timeout=10)
        fills = fills_res.json().get("fills", []) if fills_res.status_code == 200 else []
    except:
        fills = []

    try:
        sett_res = requests.get(BASE_URL + sig_path_sett + "?limit=100", headers=get_kalshi_headers("GET", sig_path_sett), timeout=10)
        settlements = sett_res.json().get("settlements", []) if sett_res.status_code == 200 else []
    except:
        settlements = []

    settled = {s["ticker"]: s.get("revenue", 0) for s in settlements}

    print("\n" + "=" * 60)
    print(f" 📋 RECENT TRADES (last {limit})")
    print("=" * 60)

    wins = 0
    losses = 0

    for f in fills:
        ticker = f.get("ticker", "?")
        price = f.get("yes_price", 0)
        action = f.get("action", "?")
        count = f.get("count", 0)

        if ticker in settled:
            payout = settled[ticker]
            cost = price * count
            pnl = payout - cost
            if pnl >= 0:
                outcome = f"✅ +{pnl/100:.2f}"
                wins += 1
            else:
                outcome = f"❌ {pnl/100:.2f}"
                losses += 1
        else:
            outcome = "⏳ open"

        print(f" {ticker:<28} {action} @{price}c x{count} {outcome}")

    print("-" * 60)
    if wins + losses > 0:
        print(f" Record: {wins}W / {losses}L ({(wins/(wins+losses))*100:.0f}% win rate)")
    else:
        print(" No settled trades yet")
    print("=" * 60 + "\n")


def get_contracts(balance, entry_price):
    """Auto-scale contracts based on bankroll. Returns 1 if FIXED_CONTRACTS > 0."""
    if FIXED_CONTRACTS > 0:
        return FIXED_CONTRACTS

    if balance and entry_price > 0:
        contracts = int(balance / 0.50)
        contracts = max(1, min(contracts, 10))
        return contracts
    return 1


def get_markets_closing_soon(within_secs=780):
    """Get all open markets closing within N seconds."""
    now = datetime.now(timezone.utc)
    path = f"/trade-api/v2/markets?status=open&min_close_ts={int(now.timestamp()+10)}&max_close_ts={int((now + timedelta(seconds=within_secs)).timestamp())}&limit=50"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=10)
        print(f"  🌐 GET markets → {res.status_code} {'✅' if res.status_code == 200 else '❌'}")
        if res.status_code == 200:
            return res.json().get("markets", [])
    except Exception as e:
        print(f"  🌐 GET markets → ⚠️ {e}")
    return []


def get_orderbook(ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=8)
        if res.status_code == 200:
            return res.json().get("orderbook", {})
        else:
            print(f"  🌐 GET {ticker} orderbook → {res.status_code}")
    except Exception as e:
        print(f"  🌐 GET {ticker} orderbook → ⚠️ {e}")
    return {}


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


def calculate_obi(orderbook, depth=5):
    """Order Book Imbalance. Positive = YES-heavy, Negative = NO-heavy."""
    yes_bids = orderbook.get("yes") or []
    no_bids = orderbook.get("no") or []

    def get_vol(bids):
        if not bids:
            return 0
        best = bids[-1][0]
        return sum(vol for price, vol in bids if price >= best - depth)

    v_yes = get_vol(yes_bids)
    v_no = get_vol(no_bids)
    if v_yes + v_no == 0:
        return 0
    return (v_yes - v_no) / (v_yes + v_no)


def should_enter(market, orderbook):
    """
    INVERTED: Enter on RIPS — buy NO when YES is expensive (NO is cheap).
    Original v3 bought YES dips at 20-80c.
    We buy NO dips at 20-80c (= YES is at 20-80c, meaning NO = 100 - YES = 20-80c).
    Specifically we want YES to be HIGH (70-95) so NO is CHEAP (5-30c) — fade the rip.
    """
    ya = market.get("yes_ask", 0)
    yb = market.get("yes_bid", 0)
    na = market.get("no_ask", 0)
    nb = market.get("no_bid", 0)

    # Skip decided markets
    if ya >= 95 or na >= 95 or ya == 0 or na == 0:
        return None, None, "decided"

    # Check spread
    yes_spread = ya - yb if ya and yb else 999
    no_spread = na - nb if na and nb else 999
    if yes_spread > MAX_SPREAD or no_spread > MAX_SPREAD:
        return None, None, "wide_spread"

    # INVERTED entry: Buy NO when YES is ripping high (NO is cheap dip)
    # Original: buy YES when ya <= MAX_ENTRY_PRICE
    # Inverse:  buy NO  when na <= MAX_ENTRY_PRICE (YES must be high = NO is cheap)
    if na <= MAX_ENTRY_PRICE and na >= MIN_ENTRY_PRICE:
        return "no", na, f"fade_rip@{na}c_no"

    # Secondary: buy YES when it has dropped (YES is now cheap — fading the NO rip)
    if ya <= MAX_ENTRY_PRICE and ya >= MIN_ENTRY_PRICE:
        return "yes", ya, f"fade_rip@{ya}c_yes"

    return None, None, "no_entry"


def place_order(ticker, side, price_cents, count=1, action="buy"):
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
        res = requests.post(BASE_URL + path, json=payload, headers=headers, timeout=10)
        print(f"  🌐 POST {ticker} {side}@{price_cents}c → {res.status_code} {'✅' if res.status_code == 201 else '❌'}")
        return res.status_code == 201, res.text if res.status_code != 201 else "ok"
    except Exception as e:
        print(f"  🌐 POST order → ⚠️ {e}")
        return False, str(e)


def refresh_market(ticker):
    path = f"/trade-api/v2/markets/{ticker}"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=8)
        if res.status_code == 200:
            return res.json().get("market", {})
        else:
            print(f"  🌐 GET {ticker} → {res.status_code}")
    except Exception as e:
        print(f"  🌐 GET {ticker} → ⚠️ {e}")
    return {}


def trade_market(market):
    """
    INVERTED swing trade — buy rips (NO cheap), sell on drops, hold above threshold.

    Original v3 logic:          Inverse logic:
    - Buy YES dips (low price)  - Buy NO dips (YES is high, NO is cheap)
    - Sell when YES rises +10c  - Sell when NO rises +10c (YES drops)
    - Hold below 67 to settle   - Hold ABOVE 67 on YES (= NO below 33) to settle
    - Exit quick above 67       - Exit quick BELOW 33 on YES (= NO above 67)
    """
    ticker = market["ticker"]
    ob = get_orderbook(ticker)
    side, entry_price, signal = should_enter(market, ob)

    if not side:
        return

    sl = secs_left(market["close_time"])
    if sl is None or sl < MIN_SECS_LEFT:
        print(f"  Skip {ticker}: {sl:.0f}s left — too close")
        return

    ts = datetime.now().strftime("%H:%M:%S")
    balance = get_balance()
    contracts = get_contracts(balance, entry_price)
    print(f"\n[{ts}] 🎯 {ticker} | {side.upper()} @ {entry_price}c | {signal} | {sl:.0f}s left | {contracts} contract(s)")

    if AUTO_TRADE:
        ok, err = place_order(ticker, side, entry_price, contracts)
        if not ok:
            print(f"  ❌ Entry failed: {err}")
            return

    tg(f"🔻 *Fade enter* `{ticker}` {side.upper()}@{entry_price}c ({contracts}x) | {signal}")

    entry = entry_price
    bought = False

    while True:
        time.sleep(4)
        ob = get_orderbook(ticker)
        m = refresh_market(ticker)

        if not m or not ob:
            break

        sl = secs_left(m.get("close_time", ""))
        if sl is not None and sl <= 0:
            print(f"  ⏰ {ticker} expired. Entry: {entry}c")
            tg(f"⏰ `{ticker}` expired | Entry: {entry}c")
            break

        # Get current bid for our side
        current_bid = m.get("yes_bid" if side == "yes" else "no_bid", 0)

        if current_bid < 5 or current_bid > 99:
            print(f"  ⚠️ Market bid {current_bid}c weird, trying orderbook...")
            if side == "yes":
                yes_data = ob.get("yes", [])
                current_bid = yes_data[0][0] if yes_data and yes_data[0][0] > 5 else 0
            else:
                no_data = ob.get("no", [])
                current_bid = no_data[0][0] if no_data and no_data[0][0] > 5 else 0
            print(f"  ↳ Orderbook bid: {current_bid}c")

        if current_bid <= 0:
            continue

        pnl = current_bid - entry
        ts = datetime.now().strftime("%H:%M:%S")

        if not bought and current_bid > 0:
            bought = True
            print(f"  ✅ Filled at {current_bid}c")

        # === INVERTED EXIT LOGIC ===

        # 1. Take profit: +10c or more (same as original — profit is profit)
        if pnl >= SWING_TARGET:
            print(f"  [{ts}] 💰 Target hit +{pnl}c | sell @ {current_bid}c")
            if AUTO_TRADE:
                place_order(ticker, side, current_bid, contracts, action="sell")
            tg(f"💰 *Fade win* `{ticker}` +{pnl}c")
            break

        # 2. Near expiry: take profit if any, otherwise hold to settle
        if sl is not None and sl < 60:
            if pnl > 0:
                print(f"  [{ts}] ⏰ Near expiry +{pnl}c | exit @ {current_bid}c")
                if AUTO_TRADE:
                    place_order(ticker, side, current_bid, contracts, action="sell")
                tg(f"⏰ *Near expiry* `{ticker}` +{pnl}c")
            else:
                print(f"  [{ts}] ⏰ Near expiry {pnl}c | holding to settle")
            break

        # 3. INVERTED threshold logic:
        #    Original: exit above 67 (YES ripped, take profit)
        #    Inverse:  exit BELOW 33 on YES (= our NO side ripped above 67, take profit)
        #    We track NO bid, so exit when NO bid > 67 (YES dropped below 33)
        if side == "no":
            yes_bid = m.get("yes_bid", 0)
            # YES has collapsed below threshold — our NO is now winning big, take it
            if yes_bid < RISK_THRESHOLD and pnl > 0:
                print(f"  [{ts}] 💹 YES collapsed to {yes_bid}c (below {RISK_THRESHOLD}c), taking +{pnl}c on NO")
                if AUTO_TRADE:
                    place_order(ticker, side, current_bid, contracts, action="sell")
                tg(f"💹 *YES collapsed* `{ticker}` NO +{pnl}c")
                break
        else:
            # Buying YES: exit when YES drops below threshold (stop momentum)
            if current_bid < RISK_THRESHOLD and pnl > 0:
                print(f"  [{ts}] 💹 YES dropped below {RISK_THRESHOLD}c, taking +{pnl}c")
                if AUTO_TRADE:
                    place_order(ticker, side, current_bid, contracts, action="sell")
                tg(f"💹 *Dropped threshold* `{ticker}` +{pnl}c")
                break

        # 4. INVERTED hold logic:
        #    Original: never sell at loss below 67 (settlement bails you out at 100)
        #    Inverse:  never sell at loss ABOVE 67 on YES (= NO below 33)
        #    If YES stays high and we're holding NO at a loss, we're fading wrong —
        #    but we hold because settlement at 0 (YES wins = NO loses) is the risk.
        #    So: hold NO if YES > 67 (we believe YES will drop back)
        #        cut quickly if YES < 67 with a loss (momentum confirmed against us)
        if side == "no":
            yes_bid = m.get("yes_bid", 0)
            if yes_bid < 67 and pnl < -5:
                print(f"  [{ts}] 🚨 YES below 67 and we're losing {pnl}c on NO — cutting loss")
                if AUTO_TRADE:
                    place_order(ticker, side, current_bid, contracts, action="sell")
                tg(f"🚨 *Cut loss* `{ticker}` NO {pnl}c")
                break

        # Status heartbeat
        if int(time.time()) % 20 == 0:
            status = "HOLD" if pnl <= 0 else f"+{pnl}c"
            print(f"  [{ts}] {side.upper()} {status} | {sl:.0f}s left | bid={current_bid}c")


def run():
    print("=" * 60)
    print("  GoobClaw Flipper v3 INVERSE — Fade the Rip")
    print(f"  Target: +{SWING_TARGET}c | Entry: NO at {MIN_ENTRY_PRICE}-{MAX_ENTRY_PRICE}c")
    print(f"  Threshold: {RISK_THRESHOLD}c YES (hold NO above, exit below)")
    print(f"  Auto-trade: {AUTO_TRADE}")
    print("=" * 60)
    tg("🔻 *Flipper v3 INVERSE online* — fading rips")

    get_pnl_summary()
    get_trade_outcomes()

    traded = set()
    cycle = 0

    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")

            priority_markets = []
            for series in ["KXBTC15M", "KXETH15M", "KXXRP15M", "KXSOL15M", "KXADA15M", "KXAVAX15M", "KXDOGE15M", "KXLTC15M"]:
                path = f"/trade-api/v2/markets?series_ticker={series}&status=open&limit=5"
                try:
                    res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=8)
                    print(f"  🌐 GET {series} → {res.status_code} {'✅' if res.status_code == 200 else '❌'}")
                    if res.status_code == 200:
                        ms = res.json().get("markets", [])
                        if ms:
                            priority_markets.append(ms[0])
                except Exception as e:
                    print(f"  🌐 GET {series} → ⚠️ {e}")

            sweep = get_markets_closing_soon(MAX_SECS_LEFT)
            all_markets = {m["ticker"]: m for m in priority_markets + sweep}.values()

            print(f"[{ts}] 📡 Scanning {len(list(all_markets))} markets (priority: {len(priority_markets)}, sweep: {len(sweep)})...")
            all_markets = {m["ticker"]: m for m in priority_markets + sweep}.values()

            cycle += 1
            if cycle % 10 == 0:
                print(f"\n[{ts}] 🔄 Cycle {cycle} — P&L check:")
                get_pnl_summary()
                get_trade_outcomes()

            for m in all_markets:
                ticker = m["ticker"]
                sl = secs_left(m.get("close_time", ""))
                if sl is None or sl <= 0:
                    continue
                if ticker in traded:
                    continue

                ya = m.get("yes_ask", 0)
                na = m.get("no_ask", 0)
                yb = m.get("yes_bid", 0)
                nb = m.get("no_bid", 0)

                # Skip decided
                if ya >= 95 or na >= 95 or ya == 0 or na == 0:
                    continue

                # Skip wide spreads
                yes_spread = ya - yb if ya and yb else 999
                no_spread = na - nb if na and nb else 999
                if yes_spread > MAX_SPREAD or no_spread > MAX_SPREAD:
                    continue

                # INVERTED: skip if no entry opportunity on the NO side
                # Original skipped if ya > MAX and na > MAX (both expensive)
                # We skip if na > MAX and ya > MAX (no cheap NO or cheap YES to fade)
                if na > MAX_ENTRY_PRICE and ya > MAX_ENTRY_PRICE:
                    continue
                if na < MIN_ENTRY_PRICE and ya < MIN_ENTRY_PRICE:
                    continue

                traded.add(ticker)
                trade_market(m)

            if len(traded) > 200:
                traded.clear()

            time.sleep(15)

        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(15)


if __name__ == "__main__":
    run()
