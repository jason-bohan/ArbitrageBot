"""
KalshiScanner.py - Live arbitrage & spread scanner for KXETH15M / KXBTC15M
and hourly crypto range markets.

Scan interval: 10 seconds
Opportunity threshold: gap >= 2 cents, ask <= 50 cents
"""
import os
import sys
import time
import json
import signal
import requests
import uuid
from datetime import datetime
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers
from market_discovery import find_opportunities

load_dotenv()

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")

# --- Config ---
MAX_SPEND_PER_TRADE = float(os.getenv("MAX_SPEND_PER_TRADE", "1.00"))  # $ per trade
MIN_GAP = int(os.getenv("MIN_GAP", "3"))                               # cents
MAX_ASK = int(os.getenv("MAX_ASK", "50"))                              # cents
AUTO_TRADE = os.getenv("AUTO_TRADE", "false").lower() == "true"        # off by default
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "10"))                  # seconds


class KalshiScannerBot:
    def __init__(self):
        self.running = True
        self.log_file = "KalshiScanner.log"
        self.state_file = "scanner_state.json"
        self.trades_today = 0
        self.pnl_today = 0.0

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self.log(f"Signal {signum} received — shutting down cleanly.")
        self.running = False

    def log(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def save_state(self, data: dict):
        try:
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.log(f"State save error: {e}")

    def get_balance(self) -> float | None:
        try:
            path = "/trade-api/v2/portfolio/balance"
            res = requests.get(
                BASE_URL + path,
                headers=get_kalshi_headers("GET", path),
                timeout=5,
            )
            if res.status_code == 200:
                return res.json().get("balance", 0) / 100
        except Exception as e:
            self.log(f"Balance check error: {e}")
        return None

    def place_order(self, ticker: str, side: str, ask_cents: int) -> bool:
        """
        Place a limit order. Buys as many contracts as MAX_SPEND_PER_TRADE allows.
        side: 'yes' or 'no'
        ask_cents: current ask price in cents (1-99)
        """
        if ask_cents <= 0:
            self.log(f"Skipping {ticker} — invalid ask price {ask_cents}¢")
            return False

        count = max(1, int((MAX_SPEND_PER_TRADE * 100) / ask_cents))
        path = "/trade-api/v2/portfolio/orders"
        url = BASE_URL + path

        payload = {
            "action": "buy",
            "count": count,
            "side": side,
            "ticker": ticker,
            "type": "limit",
            "yes_price": ask_cents if side == "yes" else (100 - ask_cents),
            "client_order_id": str(uuid.uuid4()),
        }

        try:
            headers = get_kalshi_headers("POST", path)
            headers["Content-Type"] = "application/json"
            res = requests.post(url, json=payload, headers=headers, timeout=5)
            if res.status_code == 201:
                cost = (ask_cents * count) / 100
                self.log(f"✅ ORDER PLACED | {ticker} | {side.upper()} x{count} @ {ask_cents}¢ | cost=${cost:.2f}")
                self.trades_today += 1
                return True
            else:
                self.log(f"❌ Order rejected ({res.status_code}): {res.text[:200]}")
                return False
        except Exception as e:
            self.log(f"❌ Order exception: {e}")
            return False

    def scan(self):
        balance = self.get_balance()
        if balance is not None:
            self.log(f"Balance: ${balance:.2f} | Trades today: {self.trades_today}")

        if balance is not None and balance < 0.05:
            self.log("⚠️  Balance too low to trade — scanning only.")

        opps = find_opportunities(min_gap=MIN_GAP, max_ask=MAX_ASK)

        if not opps:
            self.log("No opportunities found this scan.")
        else:
            self.log(f"Found {len(opps)} opportunity(s):")
            for o in opps[:10]:
                ticker = o["ticker"]
                gap = o["_gap"]
                side = o["_best_side"]
                ask = o["_best_ask"]
                mins = o["_mins_left"]
                vol = o.get("volume", 0)
                self.log(
                    f"  🎯 {ticker} | gap={gap}¢ | best={side}@{ask}¢ "
                    f"| mins_left={mins} | vol={vol}"
                )

                if AUTO_TRADE and balance is not None and balance >= (ask / 100):
                    self.place_order(ticker, side, ask)
                elif AUTO_TRADE:
                    self.log(f"  💸 Skipping trade — insufficient balance (${balance:.2f})")

        # Save state
        self.save_state({
            "last_scan": datetime.now().isoformat(),
            "opportunities_found": len(opps),
            "balance": balance,
            "trades_today": self.trades_today,
            "auto_trade": AUTO_TRADE,
            "top_opps": [
                {
                    "ticker": o["ticker"],
                    "gap": o["_gap"],
                    "side": o["_best_side"],
                    "ask": o["_best_ask"],
                    "mins_left": o["_mins_left"],
                }
                for o in opps[:5]
            ],
        })

    def run(self):
        self.log("=" * 60)
        self.log("Kalshi Scanner Bot starting")
        self.log(f"  Auto-trade: {AUTO_TRADE}")
        self.log(f"  Max spend/trade: ${MAX_SPEND_PER_TRADE:.2f}")
        self.log(f"  Min gap: {MIN_GAP}¢  |  Max ask: {MAX_ASK}¢")
        self.log(f"  Scan interval: {SCAN_INTERVAL}s")
        self.log("=" * 60)

        while self.running:
            try:
                self.scan()
            except Exception as e:
                self.log(f"Scan error: {e}")
            for _ in range(SCAN_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)

        self.log("Scanner stopped.")


if __name__ == "__main__":
    bot = KalshiScannerBot()
    bot.run()
