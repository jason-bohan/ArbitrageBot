#!/usr/bin/env python3
"""
Minimal test to check if basic Textual app works
"""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Button, Log, Label, DataTable
from textual.containers import Horizontal, Vertical

class MinimalDashboard(App):
    """Minimal test dashboard"""
    
    CSS = """
    Screen { background: #1a1b26; }
    .box { height: 100%; border: solid #7aa2f7; margin: 1; padding: 1; }
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
                yield Label("🚀 ACTIONS")
                yield Button("Test Button", id="test_btn", variant="primary")
            
            with Vertical(classes="box"):
                yield Label("🤖 TEST BOTS")
                yield DataTable(id="test_table")
                yield Log(id="test_log")
        
        yield Footer()
    
    def on_mount(self) -> None:
        # Initialize test table
        table = self.query_one("#test_table", DataTable)
        table.add_columns("Bot", "Status", "PID")
        
        # Add some test data
        table.add_row("TestBot1", "stopped", "-")
        table.add_row("TestBot2", "stopped", "-")
        table.add_row("TestBot3", "stopped", "-")
        
        # Log initialization
        self.query_one("#test_log", Log).write_line("Test table initialized with 3 bots")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "test_btn":
            self.query_one("#test_log", Log).write_line("Test button pressed!")

if __name__ == "__main__":
    app = MinimalDashboard()
    app.run()
