#!/usr/bin/env python3
"""
Kalshi Command Center V5.0: Fixed Version - Integrated Wallet & Bot Management
"""

import sys
import os
import time
import requests
import subprocess
from datetime import datetime
from textual.app import App, ComposeResult
from textual.worker import Worker
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable
from textual.containers import Horizontal, Vertical
from dotenv import load_dotenv
from kalshi_connection import get_kalshi_headers, test_connection
from bot_state import load_state, save_state

# Load Environment Variables
load_dotenv()

# Bot scripts mapping
BOT_SCRIPTS = {
    "credit_spread": "KalshiCreditSpread.py",
    "iron_condor": "KalshiIronCondor.py",
    "pairs": "KalshiPairs.py",
    "scanner": "KalshiScanner.py",
    "profit_maximizer": "ProfitMaximizer.py",
    "man_target_snipe": "KalshiManTargetSnipe.py",
}

class KalshiDashboard(App):
    """Command Center V5.0: Integrated Wallet & Bot Management."""
    
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
    #bots_table { height: 12; background: #24283b; border: solid #bb9af7; color: white; }
    DataTable { background: #24283b; border: solid #bb9af7; color: white; }
    DataTable > .datatable--cursor { background: #7aa2f7; }
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
                yield Button("📋 View Bot Logs", id="btn_logs", variant="primary")
                yield Button("🔍 Real-time Monitor", id="btn_monitor", variant="success")
                yield Button("💰 Manual Trade", id="btn_manual_trade", variant="warning")
            
            with Vertical(classes="box"):
                yield Label("🤖 BOTS CONTROL")
                # buttons for each bot
                for key, script in BOT_SCRIPTS.items():
                    pretty = script.replace('.py', '').replace('Kalshi', '').replace('_', ' ').strip()
                    # Add trading indicator for bots that can trade
                    if key in ["man_target_snipe", "credit_spread"]:
                        pretty += " 💰"
                    yield Button(f"Start {pretty}", id=f"start_{key}", variant="primary")
                    yield Button(f"Stop {pretty}", id=f"stop_{key}", variant="error")
            
            with Vertical(classes="box"):
                yield Label("📊 POSITION MONITOR")
                yield DataTable(id="trades_table")
                yield DataTable(id="bots_table")
                yield Log(id="main_log")
        
        yield Static("Ready", id="status-strip")
        yield Footer()
    
    def on_mount(self) -> None:
        self.python_exe = sys.executable
        
        # Initialize trades table
        try:
            trades_table = self.query_one("#trades_table", DataTable)
            trades_table.add_columns("Ticker", "Qty", "Target", "Side", "Outcome")
            self.log_message("Trades table initialized successfully")
        except Exception as e:
            self.log_message(f"Error initializing trades table: {e}")
        
        # Initialize bots table
        try:
            bots_table = self.query_one("#bots_table", DataTable)
            bots_table.add_columns("Bot", "Status", "PID", "Type")
            self.log_message("Bots table initialized successfully")
        except Exception as e:
            self.log_message(f"Error initializing bots table: {e}")
        
        # Bot process management
        self.bots: dict[str, subprocess.Popen] = {}
        
        # populate initial table
        self.log_message("About to call update_bots_table for first time...")
        self.update_bots_table()
        
        # restore saved bot state (start bots that were running)
        try:
            saved = load_state()
            self.log_message(f"Loaded saved state: {saved}")
            for key, running in saved.items():
                if running and key in BOT_SCRIPTS:
                    self.log_message(f"🔁 Restoring bot: {key}")
                    self.start_bot(key)
        except Exception as e:
            self.log_message(f"Error restoring bot state: {e}")
        
        # refresh bot status regularly
        self.set_interval(5, self.update_bots_table)
        
        # start balance sync
        self.run_worker(test_connection, thread=True)
        self.run_worker(self._sync_worker, thread=True)
        self.set_interval(10, lambda: self.run_worker(self._sync_worker, thread=True))
        
        # initialize status strip
        try:
            self.query_one("#status-strip", Static).update("Ready")
            self.log_message("Status strip initialized")
        except Exception as e:
            self.log_message(f"Error initializing status strip: {e}")
        
        self.log_message("System V5.0 Online. Initializing Sync...")
        self.log_message("💰 Trading Bots: Manual Target Sniper, Credit Spread")
        self.log_message("🔍 Scanning Bots: Trend Sniper, Profit Maximizer")
    
    def _sync_worker(self):
        """Background worker for syncing balance."""
        try:
            # Sync Balance
            b_path = "/trade-api/v2/portfolio/balance"
            base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
            url = base_url + b_path
            
            res = requests.get(url, headers=get_kalshi_headers("GET", b_path), timeout=2)
            
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
    
    def _update_balance_panel(self, text: str):
        """Thread-safe way to update balance panel."""
        try:
            self.query_one("#balance-panel", Static).update(text)
        except Exception as e:
            self.log_message(f"Error updating balance: {e}")
    
    def update_bots_table(self) -> None:
        """Update bots table with current status"""
        try:
            bots_table = self.query_one("#bots_table", DataTable)
            
            # Build rows
            rows = []
            for key, script in BOT_SCRIPTS.items():
                proc = self.bots.get(key)
                if proc and proc.poll() is None:
                    status = "running"
                    pid = str(proc.pid)
                else:
                    status = "stopped"
                    pid = "-"
                
                # Add bot type
                if key in ["man_target_snipe", "credit_spread"]:
                    bot_type = "💰 Trading"
                elif key in ["scanner", "profit_maximizer"]:
                    bot_type = "🔍 Scanning"
                else:
                    bot_type = "📊 Analysis"
                
                rows.append((key, script, status, pid, bot_type))
                self.log_message(f"Bot: {key} ({script}) - Status: {status}")

            # Clear and repopulate table
            bots_table.clear()
            bots_table.add_columns("Bot", "Status", "PID", "Type")
            for key, script, status, pid, bot_type in rows:
                bots_table.add_row(script, status, pid, bot_type)
            
        except Exception as e:
            self.log_message(f"Error updating bots table: {e}")
    
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
            # Create log file for this bot if it doesn't exist
            log_file = script.replace('.py', '.log')
            
            # Start bot with output redirected to log file
            with open(log_file, 'a') as log_f:
                proc = subprocess.Popen([self.python_exe, script_path], 
                                      stdout=log_f, stderr=log_f)
            self.bots[key] = proc
            
            # Add trading indicator
            if key in ["man_target_snipe", "credit_spread"]:
                trading_msg = " 💰 [TRADING ENABLED]"
            else:
                trading_msg = " 🔍 [SCANNING ONLY]"
            
            self.log_message(f"🚀 Started {script} (PID {proc.pid}) - Log: {log_file}{trading_msg}")
            self.update_bots_table()
            
            # Start log monitoring for this bot
            self._monitor_bot_log(key)
            
            # persist state
            try:
                st = load_state()
                st[key] = True
                save_state(st)
            except Exception:
                pass
        except Exception as e:
            self.log_message(f"❌ Failed to start {script}: {e}")

    def _monitor_bot_log(self, key: str):
        """Simple log monitoring - just read latest lines periodically."""
        script = BOT_SCRIPTS[key]
        log_file = script.replace('.py', '.log')
        
        def monitor():
            while key in self.bots and self.bots[key].poll() is None:
                try:
                    if os.path.exists(log_file):
                        with open(log_file, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            if lines:
                                # Show last 3 lines
                                for line in lines[-3:]:
                                    if line.strip():
                                        self.call_from_thread(self.log_message, f"🤖 {script}: {line.strip()}")
                    time.sleep(5)  # Check every 5 seconds
                except Exception as e:
                    self.call_from_thread(self.log_message, f"❌ Error monitoring {script} log: {e}")
                    break
        
        # Start monitoring in background
        import threading
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()

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
    
    def log_message(self, message: str):
        """Log message to main log"""
        try:
            self.query_one("#main_log", Log).write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
            # update status strip with a concise last-action message
            try:
                short = message if len(message) <= 80 else message[:77] + "..."
                status_strip = self.query_one("#status-strip", Static)
                status_strip.update(f"{datetime.now().strftime('%H:%M:%S')} {short}")
            except Exception:
                pass
        except Exception as e:
            print(f"Error logging message: {e}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events"""
        bid = event.button.id
        
        # Handle action buttons
        if bid == "btn_refresh":
            self.log_message("🔄 Manual refresh triggered...")
            self.run_worker(self._sync_worker, thread=True)
        elif bid == "btn_snipe":
            self.start_bot("scanner")
        elif bid == "btn_stop":
            self.log_message("🛑 Stop all bots requested...")
        elif bid == "btn_logs":
            self.show_bot_logs()
        elif bid == "btn_manual_trade":
            self.show_manual_trade_dialog()
        elif bid == "btn_monitor":
            self.start_real_time_monitor()
        
        # Handle bot start/stop buttons
        elif bid and bid.startswith("start_"):
            key = bid.split("start_", 1)[1]
            self.start_bot(key)
        elif bid and bid.startswith("stop_"):
            key = bid.split("stop_", 1)[1]
            self.stop_bot(key)
    
    def show_bot_logs(self) -> None:
        """Show bot logs in the main log"""
        self.log_message("📋 === BOT LOGS ===")
        
        for key, script in BOT_SCRIPTS.items():
            log_file = script.replace('.py', '.log')
            try:
                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()[-5:]  # Last 5 lines
                        if lines:
                            self.log_message(f"📄 {script} (last 5 lines):")
                            for line in lines:
                                self.log_message(f"   {line.strip()}")
                        else:
                            self.log_message(f"📄 {script}: Empty log")
                else:
                    self.log_message(f"📄 {script}: No log file")
            except Exception as e:
                self.log_message(f"❌ Error reading {script} log: {e}")
        
        self.log_message("📋 === END LOGS ===")
    
    def start_real_time_monitor(self) -> None:
        """Start real-time monitoring of all running bots."""
        self.log_message("🔍 === REAL-TIME BOT MONITOR ===")
        
        running_bots = []
        for key, proc in self.bots.items():
            if proc.poll() is None:
                running_bots.append(key)
                bot_type = "💰 Trading" if key in ["man_target_snipe", "credit_spread"] else "🔍 Scanning"
                self.log_message(f"🤖 {BOT_SCRIPTS[key]} is {bot_type} (PID: {proc.pid})")
        
        if not running_bots:
            self.log_message("⚠️ No bots are currently running")
        else:
            self.log_message(f"📊 Monitoring {len(running_bots)} running bots...")
        
        self.log_message("🔍 === END MONITOR SETUP ===")
    
    def show_manual_trade_dialog(self) -> None:
        """Show manual trading interface."""
        self.log_message("💰 === MANUAL TRADING ===")
        
        # Get current opportunities from scanner log
        scanner_log = "scanner_bot.log"
        opportunities = []
        
        try:
            if os.path.exists(scanner_log):
                with open(scanner_log, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines:
                        if "OPPORTUNITY" in line or "GAP" in line:
                            opportunities.append(line.strip())
        except Exception as e:
            self.log_message(f"❌ Error reading scanner log: {e}")
        
        if opportunities:
            self.log_message("🎯 Recent Opportunities (from scanner):")
            for opp in opportunities[-5:]:  # Show last 5
                self.log_message(f"   {opp}")
        else:
            self.log_message("📊 No recent opportunities found")
        
        # Show available tickers for manual trading
        self.log_message("📋 Available for Manual Trade:")
        tickers = [
            "KXETH15M-26FEB191215",  # ETH 15m
            # Add more tickers as needed
        ]
        
        for ticker in tickers:
            try:
                # Get current market data
                url = f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}"
                res = requests.get(url, headers=get_kalshi_headers("GET", f"/trade-api/v2/markets/{ticker}"))
                if res.status_code == 200:
                    market = res.json().get('market', {})
                    yes_ask = market.get('yes_ask', 0)
                    no_ask = market.get('no_ask', 0)
                    cap = market.get('cap', 'N/A')
                    
                    self.log_message(f"📊 {ticker}: Yes={yes_ask}¢, No={no_ask}¢, Target={cap}")
                    
                    # Simple trade recommendation
                    if yes_ask <= 25:
                        self.log_message(f"💡 CONSIDER BUYING YES: {ticker} at {yes_ask}¢ (low cost)")
                    if no_ask <= 25:
                        self.log_message(f"💡 CONSIDER BUYING NO: {ticker} at {no_ask}¢ (low cost)")
                        
            except Exception as e:
                self.log_message(f"❌ Error getting data for {ticker}: {e}")
        
        self.log_message("💰 === END MANUAL TRADING ===")
        self.log_message("📝 To trade manually: Use Kalshi web interface with the tickers above")
    
    def place_manual_order(self, ticker: str, side: str, count: int = 5):
        """Place a manual order (for future implementation)."""
        self.log_message(f"💰 Manual order: {side} {count} contracts of {ticker}")
        self.log_message("📝 Feature coming soon - use Kalshi web interface for now")
        
        # TODO: Implement actual order placement
        # path = "/trade-api/v2/portfolio/orders"
        # payload = {
        #     "ticker": ticker,
        #     "action": side,
        #     "count": count,
        #     "type": "market",
        #     "side": side
        # }
        # ... actual API call ...

if __name__ == "__main__":
    app = KalshiDashboard()
    app.run()
