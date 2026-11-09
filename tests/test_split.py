import pytest
from app.split import compute_shares
from app.ai import DEMO_RECEIPT_ITEMS, DEMO_TAX_MINOR, DEMO_DISCOUNT_MINOR, DEMO_ASSIGNMENTS


def test_demo_bill_expected_shares():
    """
    The demo bill: shares sum exactly to 136500 minor units and match expected shares:
    Indhu: 194.25 (19425), Ravi: 351.75 (35175), Priya: 372.75 (37275), Karthik: 446.25 (44625), Arun: 0.
    Total: 136500.
    """
    members = ["Indhu", "Ravi", "Priya", "Karthik", "Arun"]
    result = compute_shares(
        items=DEMO_RECEIPT_ITEMS,
        assignments=DEMO_ASSIGNMENTS,
        tax_minor=DEMO_TAX_MINOR,
        discount_minor=DEMO_DISCOUNT_MINOR,
        members=members
    )

    shares = result["shares"]
    assert sum(shares.values()) == 136500, f"Expected total 136500, got {sum(shares.values())}"
    assert shares["Indhu"] == 19425, f"Expected Indhu 19425, got {shares['Indhu']}"
    assert shares["Ravi"] == 35175, f"Expected Ravi 35175, got {shares['Ravi']}"
    assert shares["Priya"] == 37275, f"Expected Priya 37275, got {shares['Priya']}"
    assert shares["Karthik"] == 44625, f"Expected Karthik 44625, got {shares['Karthik']}"
    assert shares["Arun"] == 0, f"Expected Arun 0, got {shares['Arun']}"


def test_partial_participation():
    """
    Partial participation: a 3-of-5 shared item is split only among those 3.
    """
    members = ["Indhu", "Ravi", "Priya", "Karthik", "Arun"]
    items = [
        {"id": 1, "name": "Boat Ride", "price_minor": 3000, "qty": 1}
    ]
    assignments = [
        {"item_id": 1, "people": ["Indhu", "Ravi", "Priya"]}
    ]

    result = compute_shares(
        items=items,
        assignments=assignments,
        tax_minor=0,
        discount_minor=0,
        members=members
    )

    shares = result["shares"]
    assert shares["Indhu"] == 1000
    assert shares["Ravi"] == 1000
    assert shares["Priya"] == 1000
    assert shares["Karthik"] == 0
    assert shares["Arun"] == 0
    assert sum(shares.values()) == 3000


def test_awkward_totals_rounding():
    """
    Rounding: awkward totals (e.g. 100 split 3 ways) still sum exactly.
    """
    members = ["Alice", "Bob", "Charlie"]
    items = [
        {"id": 1, "name": "Snack", "price_minor": 100, "qty": 1}
    ]
    assignments = [
        {"item_id": 1, "people": ["Alice", "Bob", "Charlie"]}
    ]

    result = compute_shares(
        items=items,
        assignments=assignments,
        tax_minor=0,
        discount_minor=0,
        members=members
    )

    shares = result["shares"]
    assert sum(shares.values()) == 100
    assert set(shares.values()) == {33, 34}

    # Another awkward split with 7 people and tax
    seven_members = [f"User{i}" for i in range(1, 8)]
    complex_items = [
        {"id": 10, "name": "Shared Platter", "price_minor": 1000, "qty": 1}
    ]
    complex_assignments = [
        {"item_id": 10, "people": seven_members}
    ]
    complex_result = compute_shares(
        items=complex_items,
        assignments=complex_assignments,
        tax_minor=53,
        discount_minor=12,
        members=seven_members
    )
    # Total = 1000 + 53 - 12 = 1041
    assert sum(complex_result["shares"].values()) == 1041
