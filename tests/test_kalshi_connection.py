from kalshi_connection import build_signature_debug


def test_build_signature_debug_structure():
    dbg = build_signature_debug("GET", "/trade-api/v2/portfolio/balance")
    assert "timestamp" in dbg
    assert "message" in dbg
    assert "signature" in dbg
    assert "api_key" in dbg
    assert dbg["message"].endswith("/trade-api/v2/portfolio/balance")
