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

load_dotenv()

class KalshiDashboard(App):
    """Command Center V3.8: Iron Condor & Volatility Monitor."""
    
    CSS = """
    Screen { background: #1a1b26; }
    .box { height: 100%; border: solid #7aa2f7; margin: 1; padding: 1; }
    #balance-panel {
        height: 3; background: #24283b; color: #9ece6a;
        content-align: center middle; text-style: bold;
        border: double #9ece6a; margin: 1;
    }
    DataTable { height: 12; background: #24283b; border: solid #bb9af7; color: white; }
    Button { width: 100%; margin-bottom: 1; }
    Label { text-style: bold; margin-bottom: 0; color: #f7768e; }
    Log { background: #1a1b26; border: solid #414868; height: 1fr; }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("💰 Syncing Wallet...", id="balance-panel")
        with Horizontal():
            with Vertical(classes="box", id="actions-sidebar"):
                yield Label("🚀 STRATEGY")
                yield Button("Refresh Data", id="btn_check", variant="primary")
                yield Button("Run Condor Bot", id="btn_snipe", variant="success")
                yield Button("Stop All Bots", id="btn_stop", variant="error")
            
            with Vertical(classes="box"):
                yield Label("🦅 IRON CONDOR WATCH (ETH)")
                yield DataTable(id="trades_table")
                yield Label("📜 STRATEGY LOG")
                yield Log(id="main_log")
        yield Footer()

    def on_mount(self) -> None:
        self.python_exe = sys.executable
        table = self.query_one("#trades_table", DataTable)
        table.add_columns("Level", "Strike", "No Cost", "Prob of Profit")
        
        self.log_message("Condor Scanner Active. Searching for 58/58 spreads...")
        self.full_sync()
        self.set_interval(10, self.full_sync)

    def log_message(self, message: str):
        self.query_one("#main_log", Log).write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def get_kalshi_headers(self, method, path):
        api_key = os.getenv("KALSHI_API_KEY_ID")
        key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        with open(key_path, "rb") as f:
            p_key = serialization.load_pem_private_key(f.read(), password=None)
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = base64.b64encode(p_key.sign(msg.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())).decode()
        return {"KALSHI-ACCESS-KEY": api_key, "KALSHI-ACCESS-SIGNATURE": sig, "KALSHI-ACCESS-TIMESTAMP": ts}

    def get_ticker_details(self, ticker):
        try:
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
            res = requests.get(url, headers=self.get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
            if res.status_code == 200:
                m = res.json().get('market', {})
                # No cost = 100 - Yes_Price
                no_cost = 100 - m.get('yes_ask', 0)
                return m.get('cap', 'N/A'), f"{no_cost}¢", f"{no_cost}%"
        except:
            pass
        return "N/A", "0¢", "0%"

    def full_sync(self):
        table = self.query_one("#trades_table", DataTable)
        table.clear()

        try:
            # Update Balance
            b_path = "/trade-api/v2/portfolio/balance"
            b_res = requests.get("https://api.elections.kalshi.com" + b_path, headers=self.get_kalshi_headers("GET", b_path))
            if b_res.status_code == 200:
                bal = b_res.json().get('balance', 0) / 100
                self.query_one("#balance-panel", Static).update(f"💳 Wallet: ${bal:.2f} | Strategy: Iron Condor")

            # Mocking the two sides of the range based on current ETH levels
            # In a real run, you'd pull multiple tickers to find the 58¢ sweet spot
            strike_up, cost_up, prob_up = self.get_ticker_details("KXETH15M-26FEB191215")
            
            table.add_row("[green]Upper Cap[/]", strike_up, cost_up, prob_up)
            table.add_row("[red]Lower Cap[/]", "$1,921.50", "58¢", "58%")
            
            self.log_message(f"Range: $1,921.50 - {strike_up} | Target Premium: 116¢")
            
        except Exception as e:
            self.log_message(f"Sync Error: {str(e)[:50]}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_check":
            self.full_sync()
        elif btn_id == "btn_snipe":
            self.log_message("Deploying Condor Strategy...")
            subprocess.Popen([self.python_exe, "KalshiScanner.py"])
        elif btn_id == "btn_stop":
            os.system("pkill -f python")
            self.log_message("🛑 Condor Bot Paused.")

if __name__ == "__main__":
    KalshiDashboard().run()