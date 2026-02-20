#!/usr/bin/env python3
"""
Kalshi Command Center V6.0: Clean & Focused Trading Interface
"""

import sys
import os
import time
import requests
import subprocess
import threading
from datetime import datetime
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable, Tabs, TabPane
from textual.containers import Horizontal, Vertical, ScrollableContainer
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers, test_connection
from bot_state import load_state, save_state

# Load Environment Variables
load_dotenv()

# Bot scripts mapping
BOT_SCRIPTS = {
    "scanner": {"file": "KalshiScanner.py", "name": "Trend Scanner", "type": "scan", "trades": False},
    "profit_maximizer": {"file": "ProfitMaximizer.py", "name": "Profit Maximizer", "type": "scan", "trades": False},
    "man_target_snipe": {"file": "KalshiManTargetSnipe.py", "name": "Target Sniper", "type": "trade", "trades": True},
    "credit_spread": {"file": "KalshiCreditSpread.py", "name": "Credit Spread", "type": "trade", "trades": True},
}

class KalshiDashboardV2(App):
    """Clean Command Center V6.0"""
    
    CSS = """
    Screen { background: #1a1b26; }
    .main-container { padding: 1; }
    
    /* Header Section */
    #balance-panel {
        height: 3; background: #24283b; color: #9ece6a;
        content-align: center middle; text-style: bold;
        border: double #9ece6a; margin: 0 1 1 1;
    }
    
    /* Tab Content */
    TabPane { padding: 1; }
    Tabs { height: 1fr; }
    
    /* Tables */
    DataTable { 
        background: #24283b; 
        border: solid #bb9af7; 
        color: white; 
        height: 15;
    }
    DataTable > .datatable--cursor { background: #7aa2f7; }
    
    /* Buttons */
    Button { 
        width: 100%; 
        height: 2; 
        margin-bottom: 1;
        color: white;
        text-style: bold;
        background: #7aa2f7;
    }
    Button.success { background: #9ece6a; color: black; }
    Button.warning { background: #e0af68; color: black; }
    Button.error { background: #f7768e; color: black; }
    Button.primary { background: #565f89; color: white; }
    
    /* Labels */
    Label { 
        text-style: bold; 
        margin-bottom: 1; 
        color: #f7768e;
    }
    
    /* Log */
    Log { 
        background: #1a1b26; 
        border: solid #414868; 
        height: 1fr;
        max-height: 20;
    }
    
    /* Status */
    .status-good { color: #9ece6a; }
    .status-warning { color: #e0af68; }
    .status-error { color: #f7768e; }
    """
    
    def compose(self) -> ComposeResult:
        yield Header()
        
        with Vertical(classes="main-container"):
            # Balance Panel
            yield Static("Balance: Connecting...", id="balance-panel")
            
            # Main Tabs
            with Tabs():
                with TabPane("Bots", id="bots-tab"):
                    with Horizontal():
                        with Vertical():
                            yield Label("TRADING BOTS")
                            for key, info in BOT_SCRIPTS.items():
                                if info["trades"]:
                                    yield Button(f"Start {info['name']}", id=f"start_{key}", variant="success")
                                    yield Button(f"Stop {info['name']}", id=f"stop_{key}", variant="error")
                        
                        with Vertical():
                            yield Label("SCANNING BOTS")
                            for key, info in BOT_SCRIPTS.items():
                                if not info["trades"]:
                                    yield Button(f"Start {info['name']}", id=f"start_{key}", variant="primary")
                                    yield Button(f"Stop {info['name']}", id=f"stop_{key}", variant="error")
                    
                    with Horizontal():
                        with Vertical():
                            yield Label("BOT STATUS")
                            yield DataTable(id="bots_table")
                        
                        with Vertical():
                            yield Label("POSITIONS")
                            yield DataTable(id="positions_table")
                
                with TabPane("Trading", id="trading-tab"):
                    with Vertical():
                        yield Label("MANUAL TRADING")
                        yield Button("Refresh Market Data", id="btn_refresh_markets", variant="primary")
                        yield Button("Show Opportunities", id="btn_show_opportunities", variant="success")
                        yield DataTable(id="market_table")
                
                with TabPane("Logs", id="logs-tab"):
                    with Vertical():
                        yield Label("FILTERED LOGS")
                        with Horizontal():
                            yield Button("Bot Logs", id="btn_bot_logs", variant="primary")
                            yield Button("Trade Logs", id="btn_trade_logs", variant="success")
                            yield Button("Errors Only", id="btn_error_logs", variant="warning")
                            yield Button("Clear Logs", id="btn_clear_logs", variant="error")
                        yield Log(id="filtered_log")
            
            yield Footer()
    
    def on_mount(self) -> None:
        self.python_exe = sys.executable
        self.bots: dict[str, subprocess.Popen] = {}
        self.log_filter = "all"  # all, bot, trade, error
        
        # Initialize tables
        self._setup_tables()
        
        # Start background tasks
        self.set_interval(5, self.update_bots_table)
        self.set_interval(10, self.update_positions_table)
        self.run_worker(self._sync_worker, thread=True)
        self.set_interval(30, lambda: self.run_worker(self._sync_worker, thread=True))
        
        # Restore bot state
        self._restore_bot_state()
        
        self.log_message("Kalshi Command Center V6.0 Ready", "success")
    
    def _setup_tables(self):
        """Initialize all data tables."""
        try:
            # Bots table
            bots_table = self.query_one("#bots_table", DataTable)
            bots_table.add_columns("Bot", "Status", "Type", "PID")
            
            # Positions table
            positions_table = self.query_one("#positions_table", DataTable)
            positions_table.add_columns("Ticker", "Side", "Qty", "Avg Cost", "P/L")
            
            # Market table
            market_table = self.query_one("#market_table", DataTable)
            market_table.add_columns("Ticker", "Yes", "No", "Gap", "Signal")
            
        except Exception as e:
            self.log_message(f"Table setup error: {e}", "error")
    
    def _sync_worker(self):
        """Background worker for balance and positions."""
        try:
            # Get balance
            b_path = "/trade-api/v2/portfolio/balance"
            base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
            url = base_url + b_path
            res = requests.get(url, headers=get_kalshi_headers("GET", b_path), timeout=2)
            
            if res.status_code == 200:
                bal = res.json().get('balance', 0) / 100
                self.call_from_thread(self._update_balance, f"Balance: ${bal:.2f}")
            else:
                self.call_from_thread(self._update_balance, f"API Error: {res.status_code}")
                
        except Exception as e:
            self.call_from_thread(self._update_balance, f"Sync Error: {str(e)[:30]}")
    
    def _update_balance(self, text: str):
        """Update balance display."""
        try:
            self.query_one("#balance-panel", Static).update(text)
        except Exception:
            pass
    
    def update_bots_table(self):
        """Update bots status table."""
        try:
            bots_table = self.query_one("#bots_table", DataTable)
            bots_table.clear()
            
            for key, info in BOT_SCRIPTS.items():
                proc = self.bots.get(key)
                if proc and proc.poll() is None:
                    status = "Running"
                    pid = str(proc.pid)
                else:
                    status = "Stopped"
                    pid = "-"
                
                bot_type = "Trading" if info["trades"] else "Scanning"
                bots_table.add_row(info["name"], status, bot_type, pid)
                
        except Exception as e:
            self.log_message(f"Bots table error: {e}", "error")
    
    def update_positions_table(self):
        """Update positions from Kalshi API."""
        try:
            positions_table = self.query_one("#positions_table", DataTable)
            positions_table.clear()
            
            # Get positions from Kalshi API
            path = "/trade-api/v2/portfolio/positions"
            base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
            url = base_url + path
            res = requests.get(url, headers=get_kalshi_headers("GET", path), timeout=2)
            
            if res.status_code == 200:
                positions = res.json().get('positions', [])
                for pos in positions:
                    ticker = pos.get('ticker', 'N/A')
                    side = pos.get('side', 'N/A')
                    count = pos.get('count', 0)
                    cost = pos.get('average_price', 0) / 100
                    pnl = pos.get('total_return', 0) / 100
                    
                    # Color code P/L
                    pnl_text = f"${pnl:+.2f}"
                    if pnl > 0:
                        pnl_text = f"+{pnl_text}"
                    elif pnl < 0:
                        pnl_text = f"{pnl_text}"
                    
                    positions_table.add_row(ticker, side, str(count), f"${cost:.2f}", pnl_text)
                
                if not positions:
                    positions_table.add_row("No positions", "", "", "", "")
            else:
                positions_table.add_row(f"API Error: {res.status_code}", "", "", "", "")
                
        except Exception as e:
            # Don't log every error - just update table
            positions_table = self.query_one("#positions_table", DataTable)
            positions_table.clear()
            positions_table.add_row("Sync Error", "", "", "", "")
    
    def start_bot(self, key: str):
        """Start a bot with clean logging."""
        if key not in BOT_SCRIPTS:
            self.log_message(f"Unknown bot: {key}", "error")
            return
        
        info = BOT_SCRIPTS[key]
        if key in self.bots and self.bots[key].poll() is None:
            self.log_message(f"{info['name']} already running", "warning")
            return
        
        try:
            script_path = os.path.join(os.getcwd(), info["file"])
            log_file = info["file"].replace('.py', '.log')
            
            # Start bot
            with open(log_file, 'a') as log_f:
                proc = subprocess.Popen([self.python_exe, script_path], 
                                      stdout=log_f, stderr=log_f)
            self.bots[key] = proc
            
            action = "Trading" if info["trades"] else "Scanning"
            self.log_message(f"Started {info['name']} - {action}", "success")
            
            # Start log monitoring
            self._monitor_bot_log(key, info)
            
            # Save state
            try:
                st = load_state()
                st[key] = True
                save_state(st)
            except Exception:
                pass
                
        except Exception as e:
            self.log_message(f"Failed to start {info['name']}: {e}", "error")
    
    def stop_bot(self, key: str):
        """Stop a bot."""
        info = BOT_SCRIPTS[key]
        proc = self.bots.get(key)
        
        if not proc:
            self.log_message(f"{info['name']} not running", "warning")
            return
        
        try:
            proc.terminate()
            proc.wait(timeout=5)
            self.log_message(f"Stopped {info['name']}", "success")
        except Exception:
            try:
                proc.kill()
                self.log_message(f"Force stopped {info['name']}", "warning")
            except Exception as e:
                self.log_message(f"Failed to stop {info['name']}: {e}", "error")
        finally:
            self.bots.pop(key, None)
            
            # Save state
            try:
                st = load_state()
                st[key] = False
                save_state(st)
            except Exception:
                pass
    
    def _monitor_bot_log(self, key: str, info: dict):
        """Monitor bot logs with filtering."""
        log_file = info["file"].replace('.py', '.log')
        
        def monitor():
            while key in self.bots and self.bots[key].poll() is None:
                try:
                    if os.path.exists(log_file):
                        with open(log_file, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            if lines:
                                # Only show important lines
                                for line in lines[-2:]:  # Last 2 lines only
                                    text = line.strip()
                                    if any(keyword in text.upper() for keyword in 
                                          ['OPPORTUNITY', 'TRADE', 'ORDER', 'ERROR', 'BALANCE', 'BOUGHT', 'SOLD']):
                                        self.call_from_thread(self.log_message, 
                                            f"{info['name']}: {text}", "bot")
                    time.sleep(3)  # Check every3 seconds
                except Exception:
                    break
        
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    
    def log_message(self, message: str, msg_type: str = "all"):
        """Filtered logging system."""
        if self.log_filter == "all" or msg_type == self.log_filter:
            try:
                log_widget = self.query_one("#filtered_log", Log)
                timestamp = datetime.now().strftime('%H:%M:%S')
                
                # Add color coding
                if msg_type == "success":
                    message = f"[green]{message}[/green]"
                elif msg_type == "warning":
                    message = f"[yellow]{message}[/yellow]"
                elif msg_type == "error":
                    message = f"[red]{message}[/red]"
                elif msg_type == "bot":
                    message = f"[cyan]{message}[/cyan]"
                
                log_widget.write_line(f"[{timestamp}] {message}")
            except Exception:
                pass
    
    def _restore_bot_state(self):
        """Restore running bots on startup."""
        try:
            saved = load_state()
            for key, running in saved.items():
                if running and key in BOT_SCRIPTS:
                    info = BOT_SCRIPTS[key]
                    self.log_message(f"Restoring {info['name']}", "warning")
                    self.start_bot(key)
        except Exception as e:
            self.log_message(f"State restore error: {e}", "error")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        bid = event.button.id
        
        # Bot controls
        if bid.startswith("start_"):
            key = bid.split("start_", 1)[1]
            self.start_bot(key)
        elif bid.startswith("stop_"):
            key = bid.split("stop_", 1)[1]
            self.stop_bot(key)
        
        # Tab controls
        elif bid == "btn_refresh_markets":
            self._update_market_data()
        elif bid == "btn_show_opportunities":
            self._show_opportunities()
        elif bid == "btn_bot_logs":
            self.log_filter = "bot"
            self.log_message("Showing bot logs only", "success")
        elif bid == "btn_trade_logs":
            self.log_filter = "trade"
            self.log_message("Showing trade logs only", "success")
        elif bid == "btn_error_logs":
            self.log_filter = "error"
            self.log_message("Showing errors only", "warning")
        elif bid == "btn_clear_logs":
            try:
                self.query_one("#filtered_log", Log).clear()
                self.log_message("Logs cleared", "success")
            except Exception:
                pass
    
    def _update_market_data(self):
        """Update market data table."""
        try:
            market_table = self.query_one("#market_table", DataTable)
            market_table.clear()
            
            tickers = ["KXETH15M-26FEB191215"]
            
            for ticker in tickers:
                url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
                res = requests.get(url, headers=get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
                
                if res.status_code == 200:
                    market = res.json().get('market', {})
                    yes_ask = market.get('yes_ask', 0)
                    no_ask = market.get('no_ask', 0)
                    gap = 100 - (yes_ask + no_ask)
                    
                    # Simple signal
                    if gap > 2:
                        signal = "Opportunity"
                    elif yes_ask <= 20 or no_ask <= 20:
                        signal = "Low Cost"
                    else:
                        signal = "Wait"
                    
                    market_table.add_row(ticker, f"{yes_ask}c", f"{no_ask}c", f"{gap}c", signal)
                else:
                    market_table.add_row(ticker, "API Error", "", "", "")
                    
        except Exception as e:
            self.log_message(f"Market data error: {e}", "error")
    
    def _show_opportunities(self):
        """Show current opportunities."""
        self.log_message("=== OPPORTUNITY SCAN ===", "success")
        
        # Check scanner log for opportunities
        scanner_log = "scanner_bot.log"
        try:
            if os.path.exists(scanner_log):
                with open(scanner_log, 'r') as f:
                    lines = f.readlines()
                    for line in lines:
                        if "OPPORTUNITY" in line:
                            self.log_message(f"{line.strip()}", "success")
        except Exception:
            pass
        
        self.log_message("=== END SCAN ===", "success")

if __name__ == "__main__":
    app = KalshiDashboardV2()
    app.run()
