import os
import asyncio
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from kalshi_python_async import KalshiClient

# Load variables from .env
load_dotenv()

async def main():
    print("--- Starting Arbitrage Bot ---")
    
    # 1. Initialize Polymarket
    poly_client = ClobClient(
        "https://clob.polymarket.com", 
        POLYGON, 
        os.getenv("POLY_PRIVATE_KEY")
    )
    
    # 2. Initialize Kalshi
    kalshi_client = KalshiClient(
        email=os.getenv("KALSHI_EMAIL"), 
        password=os.getenv("KALSHI_PASSWORD")
    )
    await kalshi_client.login()
    
    print("Successfully connected to both platforms!")
    
    # Placeholder for the scan logic we discussed
    # For now, let's just confirm the connection works
    print("Ready to scan markets.")

if __name__ == "__main__":
    asyncio.run(main())
