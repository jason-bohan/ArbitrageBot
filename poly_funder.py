import os
import asyncio
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

# Load your .env file
load_dotenv()

async def check_wallet_readiness():
    # 1. Setup client
    client = ClobClient(
        "https://clob.polymarket.com", 
        POLYGON, 
        os.getenv("POLY_PRIVATE_KEY")
    )
    
    funder_address = os.getenv("POLY_FUNDER")
    
    # 2. Check Allowance (Required for trading)
    # This checks if the exchange is allowed to move your USDC.e
    allowance = await client.get_allowance()
    
    # 3. Check Balance
    # Polymarket API returns the balance in 'base units' (6 decimals)
    # So 1,000,000 = 1 USDC
    print(f"--- Wallet Health Check ---")
    print(f"Proxy Wallet: {funder_address}")
    print(f"Allowance set: {'✅' if int(allowance) > 0 else '❌ (Need to Approve)'}")
    
    # In a real bot, you'd use a web3 call here to get the exact USDC.e balance.
    # For now, if you can place a tiny $0.10 test order, you are good.
    print("\nNext step: Try a small $0.10 test limit order to verify everything.")

if __name__ == "__main__":
    asyncio.run(check_wallet_readiness())