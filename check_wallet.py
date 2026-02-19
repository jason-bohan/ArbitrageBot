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
from textual.widgets import Header, Footer, Static, Button, Log, Label
from textual.containers import Horizontal, Vertical
from datetime import datetime

# Load .env for API Credentials
load_dotenv()

class KalshiDashboard(App):
    """A fully self-contained Kalshi TUI."""
    
    CSS = """
    Screen { background: #1a1b26; }
    .box { height: 100%; border: solid #7aa2f7; margin: 1; padding: 1; }
    #balance-panel {
        height: 3; background: #24283b; color: #9ece6a;
        content-align: center middle; text-style: bold;
        border: double #9ece6a; margin: 1;
    }
    Button { width: 100%; margin-bottom: 1; }
    #log-panel { border: solid #bb9af7; }
    Label { text-style: bold; margin-bottom: 1; color: #f7768e; }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("💰 Syncing with Kalshi...", id="balance-panel")
        with Horizontal():
            with Vertical(classes="box"):
                yield Label("🚀 ACTIONS")
                yield Button("Refresh Wallet", id="btn_check", variant="primary")
                yield Button("Start Trend Sniper", id="btn_snipe", variant="success")
                yield Button("Execute Test Buy", id="btn_force", variant="warning")
                yield Button("Stop All Bots", id="btn_stop", variant="error")
            with Vertical(classes="box", id="log-panel"):
                yield Label("📜 ACTIVITY")
                yield Log(id="main_log")
        yield Footer()

    def on_mount(self) -> None:
        self.python_exe = sys.executable
        self.log_message("GUI Online. Fetching live data...")
        self.update_balance()
        self.set_interval(30, self.update_balance)

    def log_message(self, message: str):
        log = self.query_one("#main_log", Log)
        log.write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def update_balance(self):
        """Internal logic to get balance directly from Kalshi API."""
        try:
            api_key = os.getenv("KALSHI_API_KEY_ID")
            key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
            
            if not api_key or not key_path:
                self.log_message("Error: Missing API Keys in .env")
                return

            with open(key_path, "rb") as f:
                p_key = serialization.load_pem_private_key(f.read(), password=None)
            
            ts = str(int(time.time() * 1000))
            method, path = "GET", "/trade-api/v2/portfolio/balance"
            msg = ts + method + path
            sig = base64.b64encode(p_key.sign(msg.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())).decode()
            
            headers = {
                "KALSHI-ACCESS-KEY": api_key,
                "KALSHI-ACCESS-SIGNATURE": sig,
                "KALSHI-ACCESS-TIMESTAMP": ts
            }
            
            res = requests.get(f"https://api.elections.kalshi.com{path}", headers=headers)
            if res.status_code == 200:
                bal = res.json().get('balance', 0) / 100
                self.query_one("#balance-panel", Static).update(f"💳 Total Balance: ${bal:.2f}")
                self.log_message(f"Balance updated: ${bal:.2f}")
            else:
                self.log_message(f"API Error: {res.status_code}")
        except Exception as e:
            self.log_message(f"Sync Failure: {str(e)[:50]}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_check":
            self.update_balance()
        elif btn_id == "btn_snipe":
            subprocess.Popen([self.python_exe, "KalshiScanner.py"])
            self.log_message("Sniper started in background.")
        elif btn_id == "btn_force":
            subprocess.Popen([self.python_exe, "test.py"])
            self.log_message("Test buy order sent.")
        elif btn_id == "btn_stop":
            os.system("pkill -f python")
            self.log_message("All background bots killed.")

if __name__ == "__main__":
    KalshiDashboard().run()