#!/bin/bash
# GoobClaw Keepalive — restarts bots if they crash
cd /home/jasonbohan2/ArbitrageBot

while true; do
    if ! pgrep -f "flipper.py" > /dev/null; then
        echo "[$(date)] Restarting flipper..."
        python3 -u flipper.py >> flipper.log 2>&1 &
    fi
    if ! pgrep -f "scalper.py" > /dev/null; then
        echo "[$(date)] Restarting scalper..."
        python3 -u scalper.py >> scalper.log 2>&1 &
    fi
    if ! pgrep -f "arb_scanner.py" > /dev/null; then
        echo "[$(date)] Restarting arb_scanner..."
        python3 -u arb_scanner.py >> scanner.log 2>&1 &
    fi
    sleep 30
done
