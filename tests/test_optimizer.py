import pytest
from app.optimizer import optimize_transfers, calculate_net_balances


def test_optimizer_zeroes_balances_with_at_most_4_transfers():
    """
    Test net table {Indhu:+500, Ravi:+200, Priya:-400, Karthik:-200, Arun:-100}
    (in whole units) yields transfers that zero every balance with at most 4 transfers.
    """
    net_balances = {
        "Indhu": 500,
        "Ravi": 200,
        "Priya": -400,
        "Karthik": -200,
        "Arun": -100
    }

    transfers = optimize_transfers(net_balances)

    # Must yield at most 4 transfers
    assert len(transfers) <= 4, f"Expected at most 4 transfers, got {len(transfers)}: {transfers}"

    # Verify transfers zero every balance
    simulated_balances = {
        "Indhu": 500,
        "Ravi": 200,
        "Priya": -400,
        "Karthik": -200,
        "Arun": -100
    }

    for t in transfers:
        debtor = t["from"]
        creditor = t["to"]
        amt = t["amount_minor"]
        assert amt > 0, "Transfer amount must be strictly positive"
        simulated_balances[debtor] += amt
        simulated_balances[creditor] -= amt

    for person, bal in simulated_balances.items():
        assert bal == 0, f"Person {person} balance was not zeroed: {bal}"


def test_calculate_net_balances_multi_expense():
    """
    Verify net balance calculation across multiple expenses with different payers.
    Expense 1: Karthik pays 300; Karthik share 100, Indhu share 100, Ravi share 100.
    Expense 2: Indhu pays 150; Indhu share 50, Ravi share 100.
    """
    expenses = [
        {
            "paid_by_name": "Karthik",
            "total_minor": 300,
            "shares": {"Karthik": 100, "Indhu": 100, "Ravi": 100}
        },
        {
            "paid_by_name": "Indhu",
            "total_minor": 150,
            "shares": {"Indhu": 50, "Ravi": 100}
        }
    ]
    members = ["Indhu", "Ravi", "Priya", "Karthik", "Arun"]
    balances, raw_count = calculate_net_balances(expenses, members)

    # Karthik: +300 - 100 = +200
    # Indhu: -100 + 150 - 50 = 0
    # Ravi: -100 - 100 = -200
    # Priya: 0
    # Arun: 0
    assert balances["Karthik"] == 200
    assert balances["Indhu"] == 0
    assert balances["Ravi"] == -200
    assert balances["Priya"] == 0
    assert balances["Arun"] == 0
    assert sum(balances.values()) == 0
    assert raw_count == 3  # (Indhu, Ravi for exp1) + (Ravi for exp2)

    # Reduced transfers
    transfers = optimize_transfers(balances)
    assert len(transfers) == 1
    assert transfers[0] == {"from": "Ravi", "to": "Karthik", "amount_minor": 200}
