import os
import time
import base64
import requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

load_dotenv()

BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")


def get_kalshi_headers_api(method: str, path: str, api_key: str, key_path: str) -> dict:
    """Build Kalshi auth headers using API key."""
    with open(key_path, "rb") as f:
        p_key = serialization.load_pem_private_key(f.read(), password=None)

    ts = str(int(time.time() * 1000))
    msg = ts + method + path
    sig = base64.b64encode(
        p_key.sign(
            msg.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    ).decode()

    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def get_kalshi_headers(method: str, path: str, account: int = 1) -> dict:
    """Build Kalshi auth headers. Uses API key for account 1, email/password for account 2."""
    
    if account == 2:
        # Account 2: Use email/password
        email = os.getenv("KALSHI_EMAIL")
        password = os.getenv("KALSHI_PASSWORD")
        
        if not email or not password:
            raise RuntimeError("Missing KALSHI_EMAIL or KALSHI_PASSWORD for account 2")
        
        # Login to get session token
        login_path = "/user-api/v1/auth/login"
        login_url = BASE_URL + login_path
        
        try:
            login_res = requests.post(login_url, json={
                "email": email,
                "password": password
            }, timeout=10)
            
            if login_res.status_code == 200:
                token = login_res.json().get("token")
                return {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            else:
                raise RuntimeError(f"Login failed: {login_res.status_code}")
        except Exception as e:
            raise RuntimeError(f"Account 2 login error: {e}")
    
    else:
        # Account 1: Use API key
        api_key = os.getenv("KALSHI_API_KEY_ID")
        key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
        
        if not api_key or not key_path:
            raise RuntimeError("Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PATH")
        
        return get_kalshi_headers_api(method, path, api_key, key_path)


def place_order(ticker: str, side: str, price_cents: int, count: int = 1, 
                action: str = "buy", account: int = 1):
    """Place an order on account 1 or 2.
    
    Returns (success: bool, response)
    """
    import uuid
    path = "/trade-api/v2/portfolio/orders"
    payload = {
        "action": action,
        "count": count,
        "side": side,
        "ticker": ticker,
        "type": "limit",
        "yes_price": price_cents if side == "yes" else 100 - price_cents,
        "client_order_id": str(uuid.uuid4())
    }
    headers = get_kalshi_headers("POST", path, account)
    headers["Content-Type"] = "application/json"
    
    base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
    
    try:
        res = requests.post(base_url + path, json=payload, headers=headers, timeout=10)
        return res.status_code == 201, res.text
    except Exception as e:
        return False, str(e)


def get_balance(account: int = 1) -> float:
    """Get balance for account 1 or 2."""
    path = "/trade-api/v2/portfolio/balance"
    base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
    
    try:
        headers = get_kalshi_headers("GET", path, account)
        res = requests.get(base_url + path, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json().get("balance", 0) / 100
    except:
        pass
    return None


def test_connection(timeout: int = 5, account: int = 1) -> dict:
    """Test the Kalshi balance endpoint for account 1 or 2."""
    b_path = "/trade-api/v2/portfolio/balance"
    base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
    url = base_url + b_path

    try:
        headers = get_kalshi_headers("GET", b_path, account)
    except Exception as e:
        return {"error": str(e)}

    try:
        res = requests.get(url, headers=headers, timeout=timeout)
        return {"status_code": res.status_code, "text": res.text}
    except Exception as e:
        return {"error": str(e)}


def test_connection(timeout: int = 5) -> dict:
    """Test the Kalshi balance endpoint and print debug info.

    Returns a dict with `status_code` or `error` for programmatic checks.
    """
    b_path = "/trade-api/v2/portfolio/balance"
    base_url = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com")
    url = base_url + b_path

    try:
        headers = get_kalshi_headers("GET", b_path)
    except Exception as e:
        print("ERROR building headers:", repr(e))
        return {"error": str(e)}

    print("DEBUG: Request URL:", url)
    print("DEBUG: Request headers:", headers)

    try:
        res = requests.get(url, headers=headers, timeout=timeout)
        print("DEBUG: Response status:", res.status_code)
        try:
            print("DEBUG: Response body (first 1000 chars):", res.text[:1000])
        except Exception:
            pass
        return {"status_code": res.status_code, "text": res.text}
    except Exception as e:
        print("ERROR requesting:", repr(e))
        return {"error": str(e)}


if __name__ == "__main__":
    import json
    import sys

    result = test_connection()
    print("Result:", json.dumps(result, indent=2))
    if isinstance(result, dict) and result.get("status_code") == 200:
        sys.exit(0)
    else:
        sys.exit(1)


def build_signature_debug(method: str, path: str) -> dict:
    """Return the timestamp, signed message and signature for debugging."""
    api_key = os.getenv("KALSHI_API_KEY_ID")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    if not api_key or not key_path:
        raise RuntimeError("Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PATH in environment")

    with open(key_path, "rb") as f:
        p_key = serialization.load_pem_private_key(f.read(), password=None)

    ts = str(int(time.time() * 1000))
    msg = ts + method + path
    sig = base64.b64encode(
        p_key.sign(
            msg.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    ).decode()

    return {"timestamp": ts, "message": msg, "signature": sig, "api_key": api_key}


if __name__ == "__main__":
    # allow running signature debug via flag
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug-signature", action="store_true", help="Print timestamp/msg/signature for GET balance")
    args, remaining = parser.parse_known_args()
    if args.debug_signature:
        dbg = build_signature_debug("GET", "/trade-api/v2/portfolio/balance")
        print("DEBUG-SIGNATURE:", dbg)
        raise SystemExit(0)
