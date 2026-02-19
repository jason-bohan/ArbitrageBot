import math

def calculate_kalshi_arbitrage(account_balance, price_yes, price_no):
    """
    One-stop calculator for Kalshi arbitrage. 
    Accounts for typical taker fees and total capital allocation.
    """
    # 1. Fee Calculation 
    # Kalshi fees vary, but a safe estimate for a 'taker' (instant match) 
    # is roughly 7% of the profit potential.
    price_sum = price_yes + price_no
    profit_potential = 1.00 - price_sum
    
    # Simple fee estimate (adjust based on your actual tier)
    estimated_fee_per_pair = 0.07 * price_sum * (1 - price_sum)
    
    total_cost_per_pair = price_sum + estimated_fee_per_pair
    
    # 2. Capital Allocation
    if total_cost_per_pair >= 1.00:
        return "NO ARBITRAGE: The total cost (with fees) is >= $1.00. You would lose money."

    total_pairs = math.floor(account_balance / total_cost_per_pair)
    total_investment = total_pairs * total_cost_per_pair
    guaranteed_payout = total_pairs * 1.00
    net_profit = guaranteed_payout - total_investment
    roi_percent = (net_profit / total_investment) * 100

    # 3. Output Results
    print(f"--- Kalshi Arbitrage Analysis ---")
    print(f"Balance: ${account_balance:.2f} | Yes: ${price_yes:.2f} | No: ${price_no:.2f}")
    print(f"Total Cost Per Pair (incl. fees): ${total_cost_per_pair:.4f}")
    print(f"---------------------------------")
    print(f"Number of Pairs to Buy: {total_pairs}")
    print(f"Total Outlay:          ${total_investment:.2f}")
    print(f"Guaranteed Payout:     ${guaranteed_payout:.2f}")
    print(f"Net Profit:            ${net_profit:.2f}")
    print(f"ROI:                   {roi_percent:.2f}%")
    
    return net_profit

# Run a test with your $0.47 scenario and a $50 balance
calculate_kalshi_arbitrage(account_balance=50.00, price_yes=0.47, price_no=0.47)