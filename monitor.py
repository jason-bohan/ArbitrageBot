#!/usr/bin/env python3
"""
GoobClaw Monitor — Windows-compatible version
"""
import os
import time
import subprocess
import requests
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# Cross-platform paths
SCANNER_DIR    = os.path.dirname(os.path.abspath(__file__))
SCANNER_SCRIPT = "profit_bot.py"
SCANNER_LOG    = os.path.join(SCANNER_DIR, "profit_bot.log")
PID_FILE       = os.path.join(SCANNER_DIR, "profit_bot.pid")

CHECK_INTERVAL  = 15 * 60   # 15 minutes in seconds
UPDATE_INTERVAL = 30 * 60   # 30 minutes in seconds

def tg(msg):
    """Send a Telegram message to Jason."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",
            json={"chat_id": os.getenv('JASON_CHAT_ID'), "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"[tg error] {e}")

def get_scanner_pid():
    """Find running profit_bot.py PID using PID file."""
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
                
            # Check if process is actually running
            if sys.platform == "win32":
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                    capture_output=True, text=True
                )
                return pid if result.returncode == 0 else None
            else:
                # Linux/Mac
                result = subprocess.run(
                    ["ps", "-p", str(pid)],
                    capture_output=True, text=True
                )
                return pid if result.returncode == 0 else None
        return None
    except:
        return None

def restart_scanner():
    """Start the scanner in background."""
    # Create log directory if needed
    os.makedirs(SCANNER_DIR, exist_ok=True)
    
    # Cross-platform Python command
    python_cmd = "python" if sys.platform == "win32" else "python3"
    
    # Start process
    proc = subprocess.Popen(
        [python_cmd, SCANNER_SCRIPT],
        cwd=SCANNER_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    )
    
    # Save PID
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    
    return proc.pid

def get_balance():
    """Get current balance."""
    try:
        from kalshi_connection import get_kalshi_headers
        path = "/trade-api/v2/portfolio/balance"
        res = requests.get(
            "https://api.elections.kalshi.com" + path,
            headers=get_kalshi_headers("GET", path),
            timeout=10
        )
        if res.status_code == 200:
            data = res.json()
            balance = data.get("balance", 0) / 100
            portfolio = data.get("portfolio_value", 0) / 100
            return balance, portfolio
    except Exception as e:
        print(f"[balance error] {e}")
    return None, None

def send_update():
    """30-min update to Jason."""
    balance, portfolio = get_balance()
    pid = get_scanner_pid()
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    status = "🟢 Running" if pid else "🔴 DOWN"
    bal_str = f"${balance:.2f}" if balance is not None else "unknown"
    port_str = f"${portfolio:.2f}" if portfolio is not None else "unknown"

    msg = (
        f"🦞 *GoobClaw Update* — {ts}\n\n"
        f"*Scanner:* {status} (PID {pid})\n"
        f"*Balance:* {bal_str} | *Portfolio:* {port_str}\n"
        f"*Note:* No active markets currently - monitoring for opportunities"
    )
    tg(msg)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 Update sent")

def check_and_fix():
    """15-min health check — restart scanner if dead."""
    pid = get_scanner_pid()
    ts = datetime.now().strftime("%H:%M:%S")

    if pid:
        print(f"[{ts}] ✅ Scanner alive (PID {pid})")
        return True, pid
    else:
        print(f"[{ts}] ⚠️  Scanner dead — restarting...")
        new_pid = restart_scanner()
        time.sleep(3)
        
        if get_scanner_pid():
            print(f"[{ts}] ✅ Scanner restarted (PID {new_pid})")
            tg(f"⚠️ GoobClaw: Scanner restarted automatically (PID {new_pid})")
            return True, new_pid
        else:
            print(f"[{ts}] ❌ Restart failed!")
            tg("❌ GoobClaw: Scanner restart FAILED. Manual intervention needed.")
            return False, None

def run():
    print("🦞 GoobClaw Monitor starting...")
    print("Platform:", sys.platform)
    print("Scanner directory:", SCANNER_DIR)
    print("Scanner script:", SCANNER_SCRIPT)
    
    tg("🦞 GoobClaw monitor is live — Windows-compatible version")

    last_check = 0
    last_update = 0

    while True:
        now = time.time()

        if now - last_check >= CHECK_INTERVAL:
            check_and_fix()
            last_check = now

        if now - last_update >= UPDATE_INTERVAL:
            send_update()
            last_update = now

        time.sleep(60)

if __name__ == "__main__":
    run()
