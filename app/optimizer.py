from typing import List, Dict, Any, Tuple


def optimize_transfers(net_balances: Dict[str, int]) -> List[Dict[str, Any]]:
    """
    Given net balances {name: minor} (positive = should receive, negative = should pay),
    returns a reduced list of transfers using greedy creditor-debtor matching.
    NOTE: This is a heuristic greedy approach, returning a reduced list of transfers.
    """
    # Separate into creditors and debtors
    creditors: List[Dict[str, Any]] = []
    debtors: List[Dict[str, Any]] = []

    for name, balance in net_balances.items():
        if balance > 0:
            creditors.append({"name": name, "amount": balance})
        elif balance < 0:
            debtors.append({"name": name, "amount": -balance})

    transfers: List[Dict[str, Any]] = []

    # Sort descending by amount
    creditors.sort(key=lambda x: x["amount"], reverse=True)
    debtors.sort(key=lambda x: x["amount"], reverse=True)

    while creditors and debtors:
        creditor = creditors[0]
        debtor = debtors[0]

        transfer_amount = min(creditor["amount"], debtor["amount"])
        if transfer_amount > 0:
            transfers.append({
                "from": debtor["name"],
                "to": creditor["name"],
                "amount_minor": transfer_amount
            })

        creditor["amount"] -= transfer_amount
        debtor["amount"] -= transfer_amount

        if creditor["amount"] == 0:
            creditors.pop(0)
        if debtor["amount"] == 0:
            debtors.pop(0)

        # Re-sort to maintain greedy priority
        creditors.sort(key=lambda x: x["amount"], reverse=True)
        debtors.sort(key=lambda x: x["amount"], reverse=True)

    return transfers


def calculate_net_balances(
    expenses: List[Dict[str, Any]],
    members: List[str]
) -> Tuple[Dict[str, int], int]:
    """
    For each expense:
      - Payer is credited the total
      - Each person is debited their share
    Returns (net_balances, raw_transfers_count_before)
    """
    net_balances: Dict[str, int] = {name: 0 for name in members}
    raw_transfers_count = 0

    for expense in expenses:
        payer = expense.get("paid_by_name") or expense.get("paid_by")
        total = expense.get("total_minor", 0)
        shares = expense.get("shares", {})

        if payer in net_balances:
            net_balances[payer] += total

        for person, share_minor in shares.items():
            if person in net_balances:
                net_balances[person] -= int(share_minor)
                if person != payer and int(share_minor) > 0:
                    raw_transfers_count += 1

    return net_balances, raw_transfers_count
