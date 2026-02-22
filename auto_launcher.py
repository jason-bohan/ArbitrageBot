#!/usr/bin/env python3
"""
Kalshi Auto-Launcher - Monitors markets and auto-starts trading bot
"""
import os
import subprocess
import time
import requests
import signal
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com"

# Global process handle
bot_process = None

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{os.getenv('TELEGRAM_TOKEN')}/sendMessage",
            json={"chat_id": os.getenv('JASON_CHAT_ID'), "text": msg, "parse_mode": "Markdown"},
            timeout=5
        )
    except:
        pass

def get_kalshi_headers(method, path):
    """Get Kalshi API headers."""
    from kalshi_connection import get_kalshi_headers as get_headers
    return get_headers(method, path)

def get_active_markets():
    """Get markets with actual trading opportunities."""
    path = f"/trade-api/v2/markets?status=open&limit=200"
    try:
        res = requests.get(BASE_URL + path, headers=get_kalshi_headers("GET", path), timeout=15)
        if res.status_code == 200:
            markets = res.json().get("markets", [])
            
            tradable = []
            for m in markets:
                ya = m.get("yes_ask", 0)
                na = m.get("no_ask", 0)
                
                # Both sides must be tradable (1-99 cents)
                if ya > 0 and ya < 100 and na > 0 and na < 100:
                    tradable.append((m, ya, na))
            
            return tradable
    except:
        pass
    return []

def check_arbitrage_opportunities(markets):
    """Find profitable arbitrage opportunities."""
    opportunities = []
    
    for m, ya, na in markets:
        total = ya + na
        if total < 99.5:  # Our threshold
            gross_profit = 100 - total
            fee_cost = gross_profit * 0.012  # 1.2% fees
            net_profit = gross_profit - fee_cost
            
            if net_profit >= 0.5:  # 50¢ minimum profit
                opportunities.append((m, ya, na, net_profit))
    
    return opportunities

def stop_bot():
    """Stop the running bot process."""
    global bot_process
    if bot_process:
        try:
            bot_process.terminate()
            bot_process.wait(timeout=10)
            print("🛑 Bot stopped")
            tg("🛑 *Trading bot stopped* - No more opportunities")
        except:
            try:
                bot_process.kill()
                print("🔴 Bot force killed")
            except:
                pass
        bot_process = None

def start_bot():
    """Start the trading bot."""
    global bot_process
    
    # Stop any running bot first
    stop_bot()
    
    # Choose which bot to run (paper vs live)
    bot_script = "profit_bot_paper.py"  # Safe default
    
    # Check if AUTO_TRADE is enabled in .env
    if os.getenv("AUTO_TRADE", "false").lower() == "true":
        bot_script = "profit_bot.py"
        print(f"🚀 Starting LIVE trading bot: {bot_script}")
        tg(f"🚀 *Starting LIVE trading bot* - Markets detected!")
    else:
        print(f"📝 Starting PAPER trading bot: {bot_script}")
        tg(f"📝 *Starting paper trading bot* - Markets detected!")
    
    try:
        # Start the bot process
        bot_process = subprocess.Popen(
            [sys.executable, bot_script],
            cwd=os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        print(f"✅ Bot started with PID: {bot_process.pid}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        tg(f"❌ *Failed to start bot*: {e}")
        return False

def monitor_bot_output():
    """Monitor and forward bot output."""
    global bot_process
    
    if bot_process and bot_process.poll() is None:
        try:
            # Read any available output
            output = bot_process.stdout.readline()
            if output:
                print(f"🤖 Bot: {output.strip()}")
                
                # Check if bot found trades
                if "arbitrage" in output.lower() or "late game" in output.lower():
                    if "🎯" in output:
                        tg(f"🎯 *Bot executing trade*\n{output.strip()}")
        except:
            pass

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    print("\n🛑 Shutting down auto-launcher...")
    stop_bot()
    sys.exit(0)

def main():
    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🤖 Kalshi Auto-Launcher Started")
    print("📊 Monitoring for market opportunities...")
    print("🚀 Will auto-start trading bot when opportunities found")
    print("=" * 60)
    
    tg("🤖 *Auto-Launcher Started* - Monitoring for opportunities")
    
    consecutive_checks = 0
    bot_running = False
    
    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            markets = get_active_markets()
            
            # Monitor bot output if running
            if bot_running:
                monitor_bot_output()
            
            print(f"[{ts}] Markets: {len(markets)} tradable | Bot: {'🟢 Running' if bot_running else '🔴 Stopped'}")
            
            if len(markets) > 0:
                # Check for arbitrage opportunities
                arb_opps = check_arbitrage_opportunities(markets)
                
                if len(arb_opps) > 0:
                    print(f"   💰 {len(arb_opps)} arbitrage opportunities found!")
                    
                    # Show top opportunities
                    for i, (m, ya, na, profit) in enumerate(arb_opps[:3]):
                        print(f"   {i+1}. {m['ticker']}: YES={ya}c, NO={na}c, Profit={profit:.1f}c")
                    
                    # Start bot if not running
                    if not bot_running:
                        if start_bot():
                            bot_running = True
                            consecutive_checks = 0
                    
                    consecutive_checks = 0  # Reset counter
                    
                else:
                    print(f"   📊 Markets active but no profitable arbitrage")
                    
                    # Keep bot running for a while in case late-game opportunities appear
                    if bot_running:
                        consecutive_checks += 1
                        if consecutive_checks > 10:  # 10 minutes with no arb
                            print("   ⏰ No arb for 10min, stopping bot")
                            stop_bot()
                            bot_running = False
                            consecutive_checks = 0
            else:
                print(f"   😴 No active markets")
                
                # Stop bot if no markets
                if bot_running:
                    print("   🛑 No markets, stopping bot")
                    stop_bot()
                    bot_running = False
                
                consecutive_checks = 0
            
            time.sleep(60)  # Check every minute
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)
    
    # Cleanup
    stop_bot()
    print("\n✅ Auto-launcher stopped")

if __name__ == "__main__":
    main()
