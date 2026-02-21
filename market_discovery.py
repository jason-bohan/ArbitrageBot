"""
market_discovery.py - Dynamic Kalshi market discovery.
Finds live KXETH15M, KXBTC15M, and hourly crypto range markets.
"""
import os
import requests
from datetime import datetime, timezone
from kalshi_connection import get_kalshi_headers

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")

# Series we care about
SERIES_15M = ["KXETH15M", "KXBTC15M"]
SERIES_HOURLY = ["KXETH", "KXBTC"]


def get_live_15m_markets() -> list[dict]:
    """Return all currently active 15-minute crypto markets."""
    markets = []
    for series in SERIES_15M:
        path = f"/trade-api/v2/markets?status=open&series_ticker={series}&limit=20"
        try:
            res = requests.get(
                BASE_URL + path,
                headers=get_kalshi_headers("GET", path),
                timeout=5,
            )
            if res.status_code == 200:
                batch = res.json().get("markets", [])
                for m in batch:
                    m["_series"] = series
                markets.extend(batch)
        except Exception as e:
            print(f"[discovery] Error fetching {series}: {e}")
    return markets


def get_live_hourly_markets(min_volume: int = 10) -> list[dict]:
    """Return active hourly crypto range markets with some volume."""
    markets = []
    for series in SERIES_HOURLY:
        path = f"/trade-api/v2/markets?status=open&series_ticker={series}&limit=200"
        try:
            res = requests.get(
                BASE_URL + path,
                headers=get_kalshi_headers("GET", path),
                timeout=5,
            )
            if res.status_code == 200:
                batch = res.json().get("markets", [])
                for m in batch:
                    m["_series"] = series
                # Filter for markets with some liquidity
                batch = [m for m in batch if m.get("volume", 0) >= min_volume]
                markets.extend(batch)
        except Exception as e:
            print(f"[discovery] Error fetching {series}: {e}")
    return markets


def score_opportunity(market: dict) -> dict:
    """
    Calculate the gap and opportunity score for a market.
    Gap = 100 - (yes_bid + no_bid)  → how many cents are 'free'
    Returns enriched market dict with gap/score fields.
    """
    yes_bid = market.get("yes_bid", 0)
    no_bid = market.get("no_bid", 0)
    yes_ask = market.get("yes_ask", 0)
    no_ask = market.get("no_ask", 0)
    gap = 100 - (yes_bid + no_bid)

    # Best entry: buy whichever side has the lower ask
    # We want to pay less than 50¢ for a $1 payout
    best_side = "yes" if yes_ask <= no_ask else "no"
    best_ask = yes_ask if best_side == "yes" else no_ask

    close_time = market.get("close_time", "")
    mins_left = None
    if close_time:
        try:
            ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            mins_left = max(0, int((ct - datetime.now(timezone.utc)).total_seconds() / 60))
        except Exception:
            pass

    market["_gap"] = gap
    market["_best_side"] = best_side
    market["_best_ask"] = best_ask
    market["_mins_left"] = mins_left
    return market


def find_opportunities(min_gap: int = 2, max_ask: int = 50) -> list[dict]:
    """
    Scan all live markets and return ones with a gap >= min_gap
    and best_ask <= max_ask (so we're buying the cheap side).
    Sorted by gap descending.
    """
    all_markets = get_live_15m_markets() + get_live_hourly_markets()
    scored = [score_opportunity(m) for m in all_markets]
    opps = [
        m for m in scored
        if m["_gap"] >= min_gap and m["_best_ask"] <= max_ask
    ]
    opps.sort(key=lambda m: m["_gap"], reverse=True)
    return opps


if __name__ == "__main__":
    print("=== Live Market Opportunities ===")
    opps = find_opportunities(min_gap=2)
    if not opps:
        print("No opportunities found right now.")
    for o in opps[:20]:
        print(
            f"  {o['ticker']:45s} gap={o['_gap']:3}¢  "
            f"best={o['_best_side']}@{o['_best_ask']}¢  "
            f"mins_left={o['_mins_left']}  vol={o.get('volume',0)}"
        )
