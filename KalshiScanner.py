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
    """Command Center V3.7: Arbitrage & Spread Scanner."""
    
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
                yield Label("🚀 ACTIONS")
                yield Button("Refresh All", id="btn_check", variant="primary")
                yield Button("Start ETH Arb Bot", id="btn_snipe", variant="success")
                yield Button("Stop All Bots", id="btn_stop", variant="error")
            
            with Vertical(classes="box"):
                yield Label("📊 ARBITRAGE MONITOR (ETH/XRP)")
                yield DataTable(id="trades_table")
                yield Label("📜 LIVE PRICE FEED")
                yield Log(id="main_log")
        yield Footer()

    def on_mount(self) -> None:
        self.python_exe = sys.executable
        table = self.query_one("#trades_table", DataTable)
        table.add_columns("Ticker", "Target", "Yes/No Cost", "Arb Gap", "Status")
        
        self.log_message("Arbitrage Scanner Online. Monitoring ETH/XRP spreads...")
        self.full_sync()
        self.set_interval(10, self.full_sync) # Faster sync for 15m markets

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

    def get_market_data(self, ticker):
        """Calculates the gap between 'Yes' and 'No' costs."""
        try:
            url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
            res = requests.get(url, headers=self.get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
            if res.status_code == 200:
                m = res.json().get('market', {})
                yes_cost = m.get('yes_bid', 0)
                no_cost = m.get('no_bid', 0)
                # Total cost should be 100. Anything less is a 'Spread Gap'
                gap = 100 - (yes_cost + no_cost)
                target = m.get('cap', 'N/A')
                return f"{yes_cost}¢ / {no_cost}¢", f"{gap}¢", m.get('status').upper()
        except:
            return "??¢", "0¢", "OFFLINE"
        return "0¢", "0¢", "N/A"

    def full_sync(self):
        base_url = "https://api.elections.kalshi.com"
        table = self.query_one("#trades_table", DataTable)
        table.clear()

        try:
            # 1. Update Balance
            b_path = "/trade-api/v2/portfolio/balance"
            b_res = requests.get(base_url + b_path, headers=self.get_kalshi_headers("GET", b_path))
            if b_res.status_code == 200:
                bal = b_res.json().get('balance', 0) / 100
                self.query_one("#balance-panel", Static).update(f"💳 Wallet: ${bal:.2f} | Arb Potential: HIGH")

            # 2. Monitor specific 15m ETH ticker (based on your screenshot)
            eth_ticker = "KXETH15M-26FEB191215" 
            costs, gap, status = self.get_market_data(eth_ticker)
            table.add_row("ETH-15m", "$1,922.26", costs, gap, status)
            
            self.log_message(f"ETH Spread: {costs} (Gap: {gap})")
            
        except Exception as e:
            self.log_message(f"Sync Error: {str(e)[:50]}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn_check":
            self.full_sync()
        elif btn_id == "btn_snipe":
            self.log_message("Starting Arbitrage Engine...")
            subprocess.Popen([self.python_exe, "KalshiScanner.py"])
        elif btn_id == "btn_stop":
            os.system("pkill -f python")
            self.log_message("🛑 All Arb bots paused.")

if __name__ == "__main__":
    KalshiDashboard().run()