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

# 1. Load Environment Variables
load_dotenv()

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
                yield Label("📊 POSITION MONITOR")
                yield DataTable(id="trades_table")
                yield Log(id="main_log")
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

    def log_message(self, message: str):
        self.query_one("#main_log", Log).write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

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
        if event.button.id == "btn_refresh":
            self.log_message("🔄 Manual sync triggered...")
            # Run the sync worker in a separate thread (do not call the function)
            self.run_worker(self._sync_worker, thread=True)
        elif event.button.id == "btn_snipe":
            subprocess.Popen([self.python_exe, "KalshiScanner.py"])
            self.log_message("🚀 Sniper Bot Dispatched.")
        elif event.button.id == "btn_stop":
            os.system("pkill -f python")
            self.log_message("🛑 Emergency Stop Executed.")

if __name__ == "__main__":
    KalshiDashboard().run()
