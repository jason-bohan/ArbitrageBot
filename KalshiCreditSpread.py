import os
import sys
import time
import base64
import requests
import uuid
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable
from textual.containers import Horizontal, Vertical
from datetime import datetime, timedelta

load_dotenv()

class KalshiDashboard(App):
    """Command Center V4.3: Fixed Order Routing."""
    
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("💰 Syncing Wallet...", id="balance-panel")
        with Horizontal():
            with Vertical(classes="box", id="actions-sidebar"):
                yield Label("🚀 EXECUTION")
                yield Button("Scan Next Market", id="btn_check", variant="primary")
                yield Button("BUY 5x CREDIT SPREAD", id="btn_buy", variant="success")
                yield Button("Stop All Bots", id="btn_stop", variant="error")
            
            with Vertical(classes="box"):
                yield Label("🛡️ BULL CREDIT SPREAD MONITOR")
                yield DataTable(id="trades_table")
                yield Label("📜 TRANSACTION LOG")
                yield Log(id="main_log")
        yield Footer()

    def on_mount(self) -> None:
        self.active_ticker = "KXETH15M-26FEB191230"
        table = self.query_one("#trades_table", DataTable)
        table.add_columns("Ticker", "Cushion", "Qty", "Cost", "Time Left")
        self.log_message("System V4.3 Online. Finding active ETH markets...")
        self.full_sync()
        self.set_interval(1, self.update_countdown)
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
        return {"KALSHI-ACCESS-KEY": api_key, "KALSHI-ACCESS-SIGNATURE": sig, "KALSHI-ACCESS-TIMESTAMP": ts, "Content-Type": "application/json"}

    def place_order(self):
        path = "/trade-api/v2/portfolio/orders"
        url = "https://api.elections.kalshi.com" + path
        
        # Using a Limit Order at 99 cents to ensure it fills but doesn't overpay
        payload = {
            "action": "buy",
            "count": 5,
            "side": "no",
            "ticker": self.active_ticker,
            "type": "limit",
            "yes_price": 99, 
            "client_order_id": str(uuid.uuid4())
        }
        
        try:
            res = requests.post(url, json=payload, headers=self.get_kalshi_headers("POST", path))
            if res.status_code == 201:
                self.log_message(f"✅ ORDER PLACED: 5 contracts on {self.active_ticker}")
            else:
                self.log_message(f"❌ API Error: {res.text}")
        except Exception as e:
            self.log_message(f"Order Error: {str(e)}")

    def update_countdown(self):
        now = datetime.now()
        target = now.replace(minute=30, second=0, microsecond=0)
        if now.minute >= 30: target += timedelta(hours=1)
        remaining = target - now
        time_str = f"{remaining.seconds // 60:02d}:{remaining.seconds % 60:02d}"
        table = self.query_one("#trades_table", DataTable)
        if table.row_count > 0:
            table.update_cell_at((0, 4), f"[b cyan]{time_str}[/]")

    def full_sync(self):
        table = self.query_one("#trades_table", DataTable)
        try:
            # Sync Balance
            b_path = "/trade-api/v2/portfolio/balance"
            b_res = requests.get("https://api.elections.kalshi.com" + b_path, headers=self.get_kalshi_headers("GET", b_path))
            if b_res.status_code == 200:
                bal = b_res.json().get('balance', 0) / 100
                self.query_one("#balance-panel", Static).update(f"💳 Wallet: ${bal:.2f}")

            # Update Table
            table.clear()
            table.add_row(self.active_ticker, "+$1.58", "0", "62¢", "--:--")
            
        except Exception as e:
            self.log_message(f"Sync Error: {str(e)[:40]}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_buy":
            self.log_message(f"Sending order for {self.active_ticker}...")
            self.place_order()
        elif event.button.id == "btn_stop":
            os.system("pkill -f python")

if __name__ == "__main__":
    KalshiDashboard().run()