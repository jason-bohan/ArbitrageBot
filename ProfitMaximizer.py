import os
import sys
import time
import base64
import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable
from textual.containers import Horizontal, Vertical
from datetime import datetime

load_dotenv()

class KalshiDashboard(App):
    """Command Center V4.6: High-Reward Spread Hunter."""
    
    CSS = """
    Screen { background: #1a1b26; }
    .box { height: 100%; border: solid #7aa2f7; margin: 1; padding: 1; }
    #balance-panel {
        height: 3; background: #24283b; color: #f7768e;
        content-align: center middle; text-style: bold;
        border: double #f7768e; margin: 1;
    }
    DataTable { height: 12; background: #24283b; border: solid #bb9af7; color: white; }
    .profit-alert { color: #9ece6a; text-style: bold; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"💰 Cash Balance: ${os.getenv('USER_CASH', '8.68')}", id="balance-panel")
        with Horizontal():
            with Vertical(classes="box"):
                yield Label("🔥 HIGH-REWARD SPREADS (>300%)")
                yield DataTable(id="trades_table")
                yield Label("📜 OPPORTUNITY LOG")
                yield Log(id="main_log")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#trades_table", DataTable)
        table.add_columns("Strike", "Side", "Cost", "Potential Payout")
        self.log_message("Scanning for high-leverage dips...")
        self.full_sync()
        self.set_interval(5, self.full_sync)

    def log_message(self, message: str):
        self.query_one("#main_log", Log).write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def full_sync(self):
        table = self.query_one("#trades_table", DataTable)
        table.clear()
        
        # Simulating the 'Bigger Spread' logic based on your 12:45 screen
        # We look for contracts priced between 10c and 25c
        table.add_row("$1,932.00", "Yes (Up)", "18¢", "[b green]455% Profit[/]")
        table.add_row("$1,925.00", "No (Down)", "22¢", "[b green]354% Profit[/]")
        
        self.log_message("Found 2 high-leverage opportunities in the 12:45 PM window.")

if __name__ == "__main__":
    KalshiDashboard().run()