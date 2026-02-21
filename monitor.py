#!/usr/bin/env python3
"""
GoobClaw Monitor — checks scanner every 15 min, texts Jason every 30 min.
"""

import os
import time
import subprocess
import requests
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = "8327315190:AAGBDny1KAk9m27YOCGmxD2ElQofliyGdLI"
JASON_CHAT_ID  = "7478453115"
SCANNER_DIR    = "/home/jasonbohan2/ArbitrageBot"
SCANNER_SCRIPT = "arb_scanner.py"
SCANNER_LOG    = os.path.join(SCANNER_DIR, "scanner.log")
PID_FILE       = os.path.join(SCANNER_DIR, "scanner.pid")

CHECK_INTERVAL  = 15 * 60   # 15 minutes in seconds
UPDATE_INTERVAL = 30 * 60   # 30 minutes in seconds


def tg(msg):
    """Send a Telegram message to Jason."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": JASON_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"[tg error] {e}")


def get_scanner_pid():
    """Find running arb_scanner.py PID."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "arb_scanner.py"],
            capture_output=True, text=True
        )
        pids = result.stdout.strip().split()
        return int(pids[0]) if pids else None
    except:
        return None


def restart_scanner():
    """Start the scanner in the background."""
    log = open(SCANNER_LOG, "a")
    proc = subprocess.Popen(
        ["python3", SCANNER_SCRIPT],
        cwd=SCANNER_DIR,
        stdout=log,
        stderr=log,
        start_new_session=True
    )
    log.close()
    return proc.pid


def get_balance():
    sys.path.insert(0, SCANNER_DIR)
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


def tail_log(n=30):
    """Get last n lines of scanner log."""
    try:
        with open(SCANNER_LOG, "r") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).strip()
    except:
        return "(log unreadable)"


def get_current_spreads():
    """Get current spreads from the API."""
    sys.path.insert(0, SCANNER_DIR)
    try:
        from kalshi_connection import get_kalshi_headers
        lines = []
        for series in ["KXETH15M", "KXBTC15M"]:
            path = f"/trade-api/v2/markets?series_ticker={series}&status=open&limit=1"
            res = requests.get(
                "https://api.elections.kalshi.com" + path,
                headers=get_kalshi_headers("GET", path),
                timeout=10
            )
            if res.status_code == 200:
                markets = res.json().get("markets", [])
                for m in markets:
                    ya = m.get("yes_ask", 0)
                    na = m.get("no_ask", 0)
                    total = ya + na
                    gap = total - 100
                    arb = "🚀 ARB!" if total < 100 else f"+{gap}¢ from arb"
                    lines.append(f"{series}: {ya}¢+{na}¢={total}¢ ({arb})")
        return "\n".join(lines)
    except Exception as e:
        return f"(spread error: {e})"


def count_trades():
    """Count how many trades were placed today."""
    try:
        log = tail_log(200)
        return log.count("✅ ORDER PLACED")
    except:
        return 0


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
            tg(f"⚠️ GoobClaw: Scanner had died — restarted automatically (PID {new_pid})")
            return True, new_pid
        else:
            print(f"[{ts}] ❌ Restart failed!")
            tg("❌ GoobClaw: Scanner restart FAILED. Manual intervention needed.")
            return False, None


def send_update():
    """30-min update to Jason."""
    balance, portfolio = get_balance()
    spreads = get_current_spreads()
    trades = count_trades()
    pid = get_scanner_pid()
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    status = "🟢 Running" if pid else "🔴 DOWN"
    bal_str = f"${balance:.2f}" if balance is not None else "unknown"
    port_str = f"${portfolio:.2f}" if portfolio is not None else "unknown"

    msg = (
        f"🦞 *GoobClaw Update* — {ts}\n\n"
        f"*Scanner:* {status} (PID {pid})\n"
        f"*Balance:* {bal_str} | *Open positions:* {port_str}\n"
        f"*Trades placed this session:* {trades}\n\n"
        f"*Current spreads:*\n{spreads}"
    )
    tg(msg)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 📤 Update sent to Jason")


def run():
    print("🦞 GoobClaw Monitor starting...")
    tg("🦞 GoobClaw monitor is live — will update you every 30 min and auto-restart scanner if it dies.")

    last_check  = 0
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
