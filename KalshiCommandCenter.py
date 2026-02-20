import os
import sys
import time
import base64
import requests
import subprocess
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable
from textual.containers import Horizontal, Vertical
from datetime import datetime
from textual.worker import Worker
from kalshi_connection import get_kalshi_headers as conn_get_kalshi_headers, test_connection
from bot_state import load_state, save_state

# 1. Load Environment Variables
load_dotenv()

# Map of bot keys to script filenames (expected in project root)
BOT_SCRIPTS = {
    "credit_spread": "KalshiCreditSpread.py",
    "iron_condor": "KalshiIronCondor.py",
    "pairs": "KalshiPairs.py",
    "scanner": "KalshiScanner.py",
    "profit_maximizer": "ProfitMaximizer.py",
}

class KalshiDashboard(App):
    """Command Center V5.0: Integrated Wallet & Sniper."""
    
    CSS = """
    Screen { background: #1a1b26; }
    .box { height: 100%; border: solid #7aa2f7; margin: 1; padding: 1; }
    #balance-panel {
        height: 3; background: #24283b; color: #9ece6a;
        content-align: center middle; text-style: bold;
        border: double #9ece6a; margin: 1;
    }
    #status-strip {
        height: 1; background: #0f1720; color: #c0caf5;
        content-align: left middle; padding-left: 1; border: solid #414868;
    }
    DataTable { height: 12; background: #24283b; border: solid #bb9af7; color: white; }
    Button { width: 100%; margin-bottom: 1; height: 3; }
    Label { text-style: bold; margin-bottom: 0; color: #f7768e; }
    Log { background: #1a1b26; border: solid #414868; height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("🔄 Connecting to Kalshi API...", id="balance-panel")
        with Horizontal():
            with Vertical(classes="box"):
                yield Label("🚀 ACTIONS")
                yield Button("Refresh All", id="btn_refresh", variant="primary")
                yield Button("Start Trend Sniper", id="btn_snipe", variant="success")
                yield Button("Stop All Bots", id="btn_stop", variant="error")
            with Vertical(classes="box"):
                yield Label("🤖 BOTS CONTROL")
                # buttons for each bot
                for key, script in BOT_SCRIPTS.items():
                    pretty = script.replace('.py', '').replace('Kalshi', '').replace('_', ' ').strip()
                    yield Button(f"Start {pretty}", id=f"start_{key}", variant="primary")
                    yield Button(f"Stop {pretty}", id=f"stop_{key}", variant="error")
            
            with Vertical(classes="box"):
                yield Label("📊 POSITION MONITOR")
                yield DataTable(id="trades_table")
                # Sorting controls for bots table
                with Horizontal(id="bots_controls"):
                    yield Button("Sort: Bot", id="sort_bot", variant="primary")
                    yield Button("Sort: Status", id="sort_status", variant="primary")
                    yield Button("Sort: PID", id="sort_pid", variant="primary")
                yield DataTable(id="bots_table")
                # Per-row action buttons (Start/Stop) will be rendered here
                yield Vertical(id="bots_actions")
                yield Log(id="main_log")
            yield Static("Ready", id="status-strip")
            yield Footer()

    def on_mount(self) -> None:
        self.python_exe = sys.executable
        table = self.query_one("#trades_table", DataTable)
        table.add_columns("Ticker", "Qty", "Target", "Side", "Outcome")
        
        self.log_message("System V5.0 Online. Initializing Sync...")
        # Run a quick connection test in a threaded worker for debug
        self.run_worker(test_connection, thread=True)
        # Run the sync worker in a threaded worker (non-async function)
        self.run_worker(self._sync_worker, thread=True)
        # Schedule background runs by passing the callable (do not call it here)
        self.set_interval(10, lambda: self.run_worker(self._sync_worker, thread=True))

        # Bot process management
        self.bots: dict[str, subprocess.Popen] = {}
        bots_table = self.query_one("#bots_table", DataTable)
        bots_table.add_columns("Bot", "Status", "PID")
        # sort state: (column_key, reverse)
        self._bots_sort = ("bot", False)
        # populate initial table
        self.update_bots_table()
        # restore saved bot state (start bots that were running)
        try:
            saved = load_state()
            for key, running in saved.items():
                if running and key in BOT_SCRIPTS:
                    self.log_message(f"🔁 Restoring bot: {key}")
                    self.start_bot(key)
        except Exception:
            pass
        # refresh bot status regularly
        self.set_interval(5, self.update_bots_table)
        # initialize status strip
        try:
            self.query_one("#status-strip", Static).update("Ready")
        except Exception:
            pass

    def _update_balance_panel(self, text: str):
        """Thread-safe way to update balance panel."""
        self.query_one("#balance-panel", Static).update(text)
    
    def _sync_worker(self):
        """Background worker for syncing balance."""
        try:
            # Sync Balance
            b_path = "/trade-api/v2/portfolio/balance"
            base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
            url = base_url + b_path
            
            res = requests.get(url, headers=self.get_kalshi_headers("GET", b_path), timeout=2)
            
            if res.status_code == 200:
                bal = res.json().get('balance', 0) / 100
                self.call_from_thread(self._update_balance_panel, f"💰 Kalshi Balance: ${bal:.2f}")
                self.call_from_thread(self.log_message, "✅ Synced OK")
            else:
                self.call_from_thread(self.log_message, f"❌ API {res.status_code} - Auth failed")
                self.call_from_thread(self._update_balance_panel, f"⚠️ Error {res.status_code}")
                
        except requests.exceptions.Timeout:
            self.call_from_thread(self.log_message, "⏱️ Sync timeout")
        except requests.exceptions.ConnectionError:
            self.call_from_thread(self.log_message, "🔌 Connection failed")
        except Exception as e:
            error_msg = f"❌ {type(e).__name__}: {str(e)[:40]}"
            self.call_from_thread(self.log_message, error_msg)

    # ---- Bot process control ----
    def start_bot(self, key: str) -> None:
        """Start a bot script if not already running."""
        if key not in BOT_SCRIPTS:
            self.log_message(f"❌ Unknown bot key: {key}")
            return

        if key in self.bots:
            proc = self.bots[key]
            if proc.poll() is None:
                self.log_message(f"⚠️ Bot {key} already running (PID {proc.pid})")
                return

        script = BOT_SCRIPTS[key]
        script_path = os.path.join(os.getcwd(), script)
        try:
            proc = subprocess.Popen([self.python_exe, script_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.bots[key] = proc
            self.log_message(f"🚀 Started {script} (PID {proc.pid})")
            self.update_bots_table()
            # persist state
            try:
                st = load_state()
                st[key] = True
                save_state(st)
            except Exception:
                pass
        except Exception as e:
            self.log_message(f"❌ Failed to start {script}: {e}")

    def stop_bot(self, key: str) -> None:
        """Stop a running bot by key."""
        proc = self.bots.get(key)
        if not proc:
            self.log_message(f"⚠️ Bot {key} not running")
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
            self.log_message(f"🛑 Stopped {key} (PID {proc.pid})")
        except Exception:
            try:
                proc.kill()
                self.log_message(f"💀 Killed {key} (PID {proc.pid})")
            except Exception as e:
                self.log_message(f"❌ Failed to stop {key}: {e}")
        finally:
            self.bots.pop(key, None)
            self.update_bots_table()
            # persist state
            try:
                st = load_state()
                st[key] = False
                save_state(st)
            except Exception:
                pass

    def stop_all_bots(self) -> None:
        # show confirmation dialog (non-blocking) — user must confirm
        self.show_stop_confirmation()

    def show_stop_confirmation(self) -> None:
        """Mount a simple confirmation box with Confirm/Cancel buttons."""
        if getattr(self, "_stop_confirm_visible", False):
            return
        self._stop_confirm_visible = True
        confirm = Static("Are you sure you want to stop ALL bots?", id="stop_confirm")
        # small action buttons
        confirm_button = Button("Confirm Stop All", id="confirm_stop", variant="error")
        cancel_button = Button("Cancel", id="cancel_stop", variant="primary")
        # mount container
        wrapper = Vertical(confirm, confirm_button, cancel_button, id="stop_confirm_wrapper")
        self.mount(wrapper)

    def hide_stop_confirmation(self) -> None:
        try:
            node = self.query_one("#stop_confirm_wrapper")
            node.remove()
        except Exception:
            pass
        self._stop_confirm_visible = False

    def stop_all_bots_confirmed(self) -> None:
        keys = list(self.bots.keys())
        for k in keys:
            self.stop_bot(k)
        self.hide_stop_confirmation()

    def update_bots_table(self) -> None:
        bots_table = self.query_one("#bots_table", DataTable)
        bots_table.clear(columns=False)
        # Build rows and sort according to current sort state
        rows = []
        for key, script in BOT_SCRIPTS.items():
            proc = self.bots.get(key)
            if proc and proc.poll() is None:
                status = "running"
                pid = str(proc.pid)
            else:
                status = "stopped"
                pid = "-"
            rows.append((key, script, status, pid))

        col_key, reverse = self._bots_sort
        if col_key == "bot":
            rows.sort(key=lambda r: r[1].lower(), reverse=reverse)
        elif col_key == "status":
            rows.sort(key=lambda r: r[2], reverse=reverse)
        elif col_key == "pid":
            # sort by pid numeric where possible
            def pid_key(r):
                try:
                    return int(r[3]) if r[3].isdigit() else (-1 if r[3] == "-" else 0)
                except Exception:
                    return -1
            rows.sort(key=pid_key, reverse=reverse)

        for key, script, status, pid in rows:
            bots_table.add_row(script, status, pid)

        # Update per-row action buttons container
        try:
            actions = self.query_one("#bots_actions", Vertical)
            # clear existing
            for child in list(actions.children):
                child.remove()
            for key, script, status, pid in rows:
                pretty = script.replace('.py', '').replace('Kalshi', '').replace('_', ' ').strip()
                if status == "running":
                    b = Button(f"Stop {pretty}", id=f"row_stop_{key}", variant="error")
                else:
                    b = Button(f"Start {pretty}", id=f"row_start_{key}", variant="primary")
                actions.mount(b)
        except Exception:
            pass

    def log_message(self, message: str):
        self.query_one("#main_log", Log).write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        # update status strip with a concise last-action message
        try:
            short = message if len(message) <= 80 else message[:77] + "..."
            self.query_one("#status-strip", Static).update(f"{datetime.now().strftime('%H:%M:%S')} {short}")
        except Exception:
            pass

    def get_kalshi_headers(self, method, path):
        """Wrapper that delegates header construction to `kalshi_connection.get_kalshi_headers`.

        This centralizes auth logic so you can run `kalshi_connection.test_connection()`
        independently for debugging.
        """
        try:
            return conn_get_kalshi_headers(method, path)
        except Exception as e:
            # Surface header-building errors in the UI log for easier debugging
            self.log_message(f"❌ Header build error: {e}")
            raise



    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        # Sorting control handlers
        if bid in ("sort_bot", "sort_status", "sort_pid"):
            # toggle sort direction if same column
            mapping = {"sort_bot": "bot", "sort_status": "status", "sort_pid": "pid"}
            key = mapping[bid]
            if self._bots_sort[0] == key:
                self._bots_sort = (key, not self._bots_sort[1])
            else:
                self._bots_sort = (key, False)
            self.log_message(f"🔀 Sorting bots by {key} (reverse={self._bots_sort[1]})")
            self.update_bots_table()
            return
        if bid == "btn_refresh":
            self.log_message("🔄 Manual sync triggered...")
            # Run the sync worker in a separate thread (do not call the function)
            self.run_worker(self._sync_worker, thread=True)
        elif bid == "btn_snipe":
            # start scanner bot via managed start
            self.start_bot("scanner")
        elif bid == "btn_stop":
            # graceful stop all managed bots — show confirmation
            self.log_message("🛑 Stop All requested — showing confirmation...")
            self.stop_all_bots()
        elif bid and bid.startswith("start_"):
            key = bid.split("start_", 1)[1]
            self.start_bot(key)
        elif bid and bid.startswith("stop_"):
            key = bid.split("stop_", 1)[1]
            self.stop_bot(key)
        elif bid == "confirm_stop":
            self.log_message("🛑 Confirmed stop all — stopping now")
            self.stop_all_bots_confirmed()
        elif bid == "cancel_stop":
            self.log_message("✖️ Cancelled Stop All")
            self.hide_stop_confirmation()

if __name__ == "__main__":
    KalshiDashboard().run()
