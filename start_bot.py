#!/usr/bin/env python3
"""
Simple Auto-Launcher - Start and forget
"""
import subprocess
import sys
import os

def main():
    print("🚀 Starting Kalshi Auto-Launcher...")
    print("This will:")
    print("  1. Monitor for active markets")
    print("  2. Auto-start trading bot when opportunities found")
    print("  3. Auto-stop when markets close")
    print("  4. Send Telegram alerts")
    print("\nPress Ctrl+C to stop")
    print("=" * 50)
    
    # Run the auto-launcher
    try:
        subprocess.run([sys.executable, "auto_launcher.py"], cwd=os.getcwd())
    except KeyboardInterrupt:
        print("\n🛑 Stopped")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
