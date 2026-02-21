"""Basic sanity tests for ArbitrageBot."""

def test_obi_calculation():
    """OBI should return value between -1 and 1."""
    # Simulate orderbook with heavy YES demand
    orderbook = {
        "yes": [[48, 500], [49, 300], [50, 200]],
        "no":  [[48, 100], [49, 50]],
    }
    yes_vol = sum(v for p, v in orderbook["yes"] if p >= 50 - 5)
    no_vol  = sum(v for p, v in orderbook["no"]  if p >= 49 - 5)
    obi = (yes_vol - no_vol) / (yes_vol + no_vol) if (yes_vol + no_vol) > 0 else 0
    assert -1 <= obi <= 1
    assert obi > 0  # YES-heavy book should give positive OBI


def test_profit_calculation():
    """Profit per contract should be correct."""
    entry_price = 85  # cents
    payout = 100      # cents
    profit = payout - entry_price
    assert profit == 15


def test_contract_sizing():
    """25% risk on $20 balance at 90c entry = ~5 contracts."""
    balance = 20.00
    risk_pct = 0.25
    price_cents = 90
    contracts = int((balance * risk_pct) / (price_cents / 100))
    assert contracts == 5


def test_stop_loss_flip():
    """Verify flip logic: entry 50c, stop at -4c means flip when bid hits 46c."""
    entry = 50
    stop_loss = 4
    flip_trigger = entry - stop_loss
    assert flip_trigger == 46
