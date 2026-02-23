#!/usr/bin/env python3
"""
GoobClaw Monitor — Robust version with better process detection
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

def is_process_running(pid):
    """Check if a process with given PID is actually running."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            return str(pid) in result.stdout
        else:
            # Linux/Mac - check if process exists and is python
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "comm="],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0 and "python" in result.stdout.lower()
    except:
        return False

def get_scanner_pid():
    """Find running profit_bot.py PID - checks both PID file and running processes."""
    # First check PID file
    saved_pid = None
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                saved_pid = int(f.read().strip())
            if saved_pid and is_process_running(saved_pid):
                return saved_pid
        except:
            pass
    
    # PID file stale - search for running process
    try:
        result = subprocess.run(
            ["pgrep", "-f", "profit_bot.py"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split()
            return int(pids[0])
    except:
        pass
    
    return None

def restart_scanner():
    """Start the profit_bot in background with proper logging."""
    os.makedirs(SCANNER_DIR, exist_ok=True)
    
    python_cmd = "python3"
    
    # Open log file for output
    log_file = open(SCANNER_LOG, "a")
    
    proc = subprocess.Popen(
        [python_cmd, SCANNER_SCRIPT],
        cwd=SCANNER_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    
    # Save PID
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    
    log_file.close()
    return proc.pid

def get_balance():
    """Get current balance and positions."""
    try:
        from kalshi_connection import get_kalshi_headers
        base_url = "https://api.elections.kalshi.com"
        
        # Get balance
        path = "/trade-api/v2/portfolio/balance"
        res = requests.get(
            base_url + path,
            headers=get_kalshi_headers("GET", path),
            timeout=10
        )
        
        balance = None
        portfolio = None
        
        if res.status_code == 200:
            data = res.json()
            balance = data.get("balance", 0) / 100
            portfolio = data.get("portfolio_value", 0) / 100
        
        # Get open positions count
        pos_path = "/trade-api/v2/portfolio/positions"
        pos_res = requests.get(
            base_url + pos_path,
            headers=get_kalshi_headers("GET", pos_path),
            timeout=10
        )
        
        pos_count = 0
        if pos_res.status_code == 200:
            positions = pos_res.json().get("positions", [])
            pos_count = len(positions)
        
        return balance, portfolio, pos_count
        
    except Exception as e:
        print(f"[balance error] {e}")
    return None, None, 0


def get_recent_log():
    """Get last 10 lines of profit_bot.log"""
    try:
        if os.path.exists(SCANNER_LOG):
            with open(SCANNER_LOG, "r") as f:
                lines = f.readlines()
                return "".join(lines[-10:]).strip()
    except:
        pass
    return "(no log)"


def send_update():
    """30-min update to Jason."""
    balance, portfolio, pos_count = get_balance()
    pid = get_scanner_pid()
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    recent_log = get_recent_log()

    status = "🟢 Running" if pid else "🔴 DOWN"
    bal_str = f"${balance:.2f}" if balance is not None else "unknown"
    port_str = f"${portfolio:.2f}" if portfolio is not None else "unknown"

    msg = (
        f"🦞 *GoobClaw Update* — {ts}\n\n"
        f"*Scanner:* {status} (PID: {pid or 'N/A'})\n"
        f"*Balance:* {bal_str} | *Positions:* {pos_count}\n"
        f"*Last log:*\n{recent_log[-200:]}"
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
            tg(f"⚠️ GoobClaw: Scanner restarted (PID {new_pid})")
            return True, new_pid
        else:
            print(f"[{ts}] ❌ Restart failed!")
            tg("❌ GoobClaw: Restart FAILED")
            return False, None


def run():
    print("=" * 50)
    print("🦞 GoobClaw Monitor starting...")
    print("=" * 50)
    print(f"Dir: {SCANNER_DIR}")
    print(f"Script: {SCANNER_SCRIPT}")
    print(f"Log: {SCANNER_LOG}")
    print(f"PID file: {PID_FILE}")
    
    # Check initial state
    initial_pid = get_scanner_pid()
    print(f"Initial PID check: {initial_pid}")
    
    tg("🦞 Monitor online")

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
