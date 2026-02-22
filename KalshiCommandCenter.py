#!/usr/bin/env python3
"""
Kalshi Command Center — Clean single-file TUI.
Manages bots, shows live balance, scanner opportunities, and logs.
"""
import os
import sys
import time
import subprocess
import requests
from datetime import datetime
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable
from textual.containers import Horizontal, Vertical, ScrollableContainer
from kalshi_connection import get_kalshi_headers
from bot_state import load_state, save_state
from market_discovery import find_opportunities

load_dotenv()

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")

BOT_SCRIPTS = {
    "scanner":         "KalshiScanner.py",
    "credit_spread":   "KalshiCreditSpread.py",
    "iron_condor":     "KalshiIronCondor.py",
    "pairs":           "KalshiPairs.py",
    "profit_max":      "ProfitMaximizer.py",
    "snipe":           "KalshiManTargetSnipe.py",
    "scalper":         "scalper.py",
    "flipper":         "flipper.py",
}

BOT_LABELS = {
    "scanner":       "📡 Scanner",
    "credit_spread": "📈 Credit Spread",
    "iron_condor":   "🦅 Iron Condor",
    "pairs":         "🔗 Pairs",
    "profit_max":    "💰 Profit Max",
    "snipe":         "🎯 Target Snipe",
    "scalper":       "⚡ Scalper",
    "flipper":       "🔄 Flipper",
}


class KalshiCommandCenter(App):
    """Kalshi Command Center — bot management + live scanner."""

    CSS = """
    Screen { background: #1a1b26; }

    #header-bar {
        height: 3; background: #24283b; color: #9ece6a;
        content-align: center middle; text-style: bold;
        border: double #9ece6a; margin: 0 1 1 1;
    }
    #status-bar {
        height: 1; background: #0f1720; color: #c0caf5;
        content-align: left middle; padding-left: 1;
    }

    .panel { border: solid #414868; margin: 0 1; padding: 0 1; }
    .panel-title { color: #f7768e; text-style: bold; margin-bottom: 1; }

    #left-panel { width: 28; }
    #center-panel { width: 1fr; }
    #right-panel { width: 50; }

    DataTable { 
        background: #24283b; 
        height: 12; 
        overflow: auto;
    }
    DataTable > .datatable--cursor { background: #7aa2f7; color: #1a1b26; }
    DataTable > .datatable--header { background: #1f2335; color: #7aa2f7; text-style: bold; }

    Button { width: 100%; margin-bottom: 1; height: 3; }
    Button.start { background: #1a472a; color: #9ece6a; }
    Button.stop  { background: #4a0000; color: #f7768e; }
    Button.action { background: #24283b; color: #7aa2f7; }

    Log { background: #1a1b26; border: solid #414868; height: 1fr; color: #c0caf5; }

    #opp-table { height: 10; }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("💰 Connecting…", id="header-bar")
        yield Static("j/k: ↑↓ | h/l: ←→ | g/G: top/bottom | Enter: Select | q: Quit", id="help-bar")

        with Horizontal():
            # LEFT: Bot controls
            with Vertical(id="left-panel", classes="panel"):
                yield Label("🤖 BOT CONTROLS", classes="panel-title")
                for key in BOT_SCRIPTS:
                    yield Button(BOT_LABELS[key], id=f"start_{key}", classes="start")
                    yield Button(f"Stop {key}", id=f"stop_{key}", classes="stop")
                yield Label(" ", classes="panel-title")
                yield Button("⛔ Stop All", id="btn_stop_all", classes="stop")
                yield Button("🔄 Refresh", id="btn_refresh", classes="action")

            # CENTER: Bots table + Opportunities + Log
            with Vertical(id="center-panel", classes="panel"):
                yield Label("📊 BOT STATUS", classes="panel-title")
                yield DataTable(id="bots_table")
                yield Label("🎯 LIVE OPPORTUNITIES", classes="panel-title")
                yield DataTable(id="opp_table")
                yield Label("📋 LOG", classes="panel-title")
                yield Log(id="main_log")

            # RIGHT: Scanner state
            with Vertical(id="right-panel", classes="panel"):
                yield Label("📡 SCANNER FEED", classes="panel-title")
                yield Log(id="scanner_log")

        yield Static("Initializing…", id="init-status")
        yield Footer()

    def on_mount(self) -> None:
        self.python_exe = sys.executable
        self.bots: dict[str, subprocess.Popen] = {}
        
        # Set up Vim key bindings
        self.bind("j", "cursor_down")
        self.bind("k", "cursor_up") 
        self.bind("h", "cursor_left")
        self.bind("l", "cursor_right")
        self.bind("g", "home")
        self.bind("G", "end")
        self.bind("q", "quit")
        self.bind("ctrl+c", "quit")

        # Init bots table
        bt = self.query_one("#bots_table", DataTable)
        bt.add_columns("Bot", "Status", "PID")
        
        # Add initial data
        for key, script in BOT_SCRIPTS.items():
            bt.add_row(BOT_LABELS[key], "Stopped", "-")

        # Init opportunities table
        ot = self.query_one("#opp_table", DataTable)
        ot.add_columns("Ticker", "Gap", "Best Side", "Ask", "Mins Left")
        
        # Add sample data
        ot.add_row("KXETH15M-26FEB191215", "3¢", "YES", "48¢", "15")

        self.log_msg("Command Center online.")
        self.update_bots_table()
        
        # Update the init status to show we're ready
        self.query_one("#init-status", Static).update("Ready - Use j/k/h/l to navigate")

        # Restore previously running bots
        for key, running in load_state().items():
            if running and key in BOT_SCRIPTS:
                self.log_msg(f"🔁 Restoring: {key}")
                self.start_bot(key)

        # Timers
        self.set_interval(5,  self.update_bots_table)
        self.set_interval(10, self._refresh_balance)
        self.set_interval(15, self._refresh_opportunities)
        self._refresh_balance()
        self._refresh_opportunities()

    # ── Balance ──────────────────────────────────────────────────────────

    def _refresh_balance(self):
        self.run_worker(self._fetch_balance, thread=True)

    def _fetch_balance(self):
        try:
            path = "/trade-api/v2/portfolio/balance"
            res = requests.get(
                BASE_URL + path,
                headers=get_kalshi_headers("GET", path),
                timeout=5,
            )
            if res.status_code == 200:
                bal = res.json().get("balance", 0) / 100
                self.call_from_thread(
                    self.query_one("#header-bar", Static).update,
                    f"💰 Kalshi Balance: ${bal:.2f}",
                )
                self.call_from_thread(self.log_msg, f"Balance synced: ${bal:.2f}")
            else:
                self.call_from_thread(self.log_msg, f"⚠️ Balance API {res.status_code}")
        except Exception as e:
            self.call_from_thread(self.log_msg, f"Balance error: {e}")

    # ── Opportunities ─────────────────────────────────────────────────────

    def _refresh_opportunities(self):
        self.run_worker(self._fetch_opportunities, thread=True)

    def _fetch_opportunities(self):
        try:
            opps = find_opportunities(min_gap=2, max_ask=50)
            self.call_from_thread(self._update_opp_table, opps)
            if opps:
                top = opps[0]
                self.call_from_thread(
                    self.log_msg,
                    f"🎯 Best opp: {top['ticker']} gap={top['_gap']}¢ {top['_best_side']}@{top['_best_ask']}¢",
                )
        except Exception as e:
            self.call_from_thread(self.log_msg, f"Opp scan error: {e}")

    def _update_opp_table(self, opps: list):
        ot = self.query_one("#opp_table", DataTable)
        ot.clear()
        for o in opps[:8]:
            ot.add_row(
                o["ticker"][-25:],
                f"{o['_gap']}¢",
                o["_best_side"].upper(),
                f"{o['_best_ask']}¢",
                str(o["_mins_left"]) if o["_mins_left"] is not None else "?",
            )

    # ── Bots table ────────────────────────────────────────────────────────

    def update_bots_table(self):
        bt = self.query_one("#bots_table", DataTable)
        bt.clear()
        for key, script in BOT_SCRIPTS.items():
            proc = self.bots.get(key)
            if proc and proc.poll() is None:
                status = "🟢 running"
                pid = str(proc.pid)
            else:
                status = "⚫ stopped"
                pid = "—"
            bt.add_row(BOT_LABELS[key], status, pid)

    # ── Bot lifecycle ─────────────────────────────────────────────────────

    def start_bot(self, key: str):
        if key not in BOT_SCRIPTS:
            return
        proc = self.bots.get(key)
        if proc and proc.poll() is None:
            self.log_msg(f"⚠️ {key} already running (PID {proc.pid})")
            return

        script = BOT_SCRIPTS[key]
        script_path = os.path.join(os.path.dirname(__file__), script)
        log_path = script.replace(".py", ".log")
        try:
            with open(log_path, "a") as lf:
                proc = subprocess.Popen(
                    [self.python_exe, script_path],
                    stdout=lf, stderr=lf,
                    cwd=os.path.dirname(__file__),
                )
            self.bots[key] = proc
            self.log_msg(f"🚀 Started {script} (PID {proc.pid})")
            self.update_bots_table()
            self.run_worker(lambda k=key: self._tail_bot_log(k), thread=True)
            st = load_state(); st[key] = True; save_state(st)
        except Exception as e:
            self.log_msg(f"❌ Failed to start {key}: {e}")

    def stop_bot(self, key: str):
        proc = self.bots.pop(key, None)
        if not proc:
            self.log_msg(f"⚠️ {key} not running")
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
            self.log_msg(f"🛑 Stopped {key} (PID {proc.pid})")
        except Exception:
            try:
                proc.kill()
                self.log_msg(f"💀 Killed {key}")
            except Exception as e:
                self.log_msg(f"❌ Kill failed: {e}")
        self.update_bots_table()
        st = load_state(); st[key] = False; save_state(st)

    def stop_all_bots(self):
        self.log_msg("⛔ Stopping all bots…")
        for key in list(self.bots.keys()):
            self.stop_bot(key)

    def _tail_bot_log(self, key: str):
        """Tail a bot's log file into the scanner feed."""
        script = BOT_SCRIPTS[key]
        log_path = os.path.join(os.path.dirname(__file__), script.replace(".py", ".log"))
        time.sleep(1)
        try:
            last_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
            while key in self.bots and self.bots[key].poll() is None:
                current_size = os.path.getsize(log_path) if os.path.exists(log_path) else 0
                if current_size > last_size:
                    with open(log_path, "r", encoding="utf-8") as f:
                        f.seek(last_size)
                        for line in f.readlines():
                            line = line.strip()
                            if line:
                                self.call_from_thread(self._append_scanner_log, f"[{key}] {line}")
                    last_size = current_size
                time.sleep(2)
        except Exception as e:
            self.call_from_thread(self.log_msg, f"Log tail error ({key}): {e}")

    def _append_scanner_log(self, text: str):
        self.query_one("#scanner_log", Log).write_line(text)

    # ── Logging ───────────────────────────────────────────────────────────

    def log_msg(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"[{ts}] {msg}"
        try:
            self.query_one("#main_log", Log).write_line(full)
            short = msg[:90] if len(msg) > 90 else msg
            self.query_one("#status-bar", Static).update(f"{ts} {short}")
        except Exception:
            pass

    # ── Button handler ────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("start_"):
            self.start_bot(bid[6:])
        elif bid.startswith("stop_") and bid != "btn_stop_all":
            self.stop_bot(bid[5:])
        elif bid == "btn_stop_all":
            self.stop_all_bots()
        elif bid == "btn_refresh":
            self._refresh_balance()
            self._refresh_opportunities()
            self.update_bots_table()
            self.log_msg("Manual refresh triggered.")


if __name__ == "__main__":
    KalshiCommandCenter().run()
