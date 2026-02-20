#!/usr/bin/env python3
"""
Minimal standalone test for bots table rendering
"""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable
from textual.containers import Horizontal, Vertical

class SimpleBotsApp(App):
    """Minimal app to test bots table rendering"""
    
    CSS = """
    Screen { background: #1a1b26; }
    .box { height: 100%; border: solid #7aa2f7; margin: 1; padding: 1; }
    #bots_table { height: 12; background: #24283b; border: solid #bb9af7; color: white; }
    DataTable { background: #24283b; border: solid #bb9af7; color: white; }
    Button { width: 100%; margin-bottom: 1; height: 3; }
    Label { text-style: bold; margin-bottom: 0; color: #f7768e; }
    Log { background: #1a1b26; border: solid #414868; height: 1fr; }
    """
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Test Balance: $100.00", id="balance-panel")
        
        with Horizontal():
            with Vertical(classes="box"):
                yield Label("🤖 TEST BOTS")
                yield DataTable(id="bots_table")
                yield Log(id="main_log")
        
        yield Footer()
    
    def on_mount(self) -> None:
        print("🔄 on_mount called!")
        
        # Initialize bots table
        try:
            bots_table = self.query_one("#bots_table", DataTable)
            print(f"✅ bots_table object: {type(bots_table)}")
            print(f"✅ bots_table id: {getattr(bots_table, 'id', 'No ID')}")
            
            bots_table.add_columns("Bot", "Status", "PID")
            print("✅ Columns added: Bot, Status, PID")
            
            # Add test data
            test_bots = [
                ("TestBot1", "TestBot1.py", "stopped", "-"),
                ("TestBot2", "TestBot2.py", "stopped", "-"),
                ("TestBot3", "TestBot3.py", "stopped", "-"),
            ]
            
            for bot_name, script, status, pid in test_bots:
                bots_table.add_row(bot_name, status, pid)
                print(f"✅ Added row: {bot_name}, {status}, {pid}")
            
            self.query_one("#main_log", Log).write_line("Test table initialized with 3 bots")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    print("🚀 Starting Simple Bots Table Test...")
    app = SimpleBotsApp()
    app.run()
