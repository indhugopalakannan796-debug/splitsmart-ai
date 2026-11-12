import json
import pytest
from app import db


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """
    Sets up a temporary SQLite database initialized with default members.
    """
    temp_db = str(tmp_path / "test_members.db")
    monkeypatch.setattr(db, "DB_PATH", temp_db)
    db.init_db()
    return temp_db


def test_rename_member(test_db):
    """
    Renaming a member updates their name in members table,
    and updates assignments_json and shares_json in existing expenses.
    """
    members = db.get_members()
    indhu = next(m for m in members if m["name"] == "Indhu")
    indhu_id = indhu["id"]

    # Create an expense with Indhu in assignments and shares
    exp_id = db.create_expense(
        description="Dinner Feast",
        paid_by=indhu_id,
        total_minor=20000,
        items_json=json.dumps([{"id": 1, "name": "Pizza", "price_minor": 20000, "qty": 1}]),
        assignments_json=json.dumps([{"item_id": 1, "people": ["Indhu", "Ravi"]}]),
        shares_json=json.dumps({"Indhu": 10000, "Ravi": 10000})
    )

    # Rename Indhu -> Indira
    renamed = db.rename_member(indhu_id, "Indira")
    assert renamed["name"] == "Indira"

    # Verify member row updated
    updated_member = db.get_member_by_id(indhu_id)
    assert updated_member["name"] == "Indira"

    # Verify expense updated
    exp = db.get_expense(exp_id)
    assert exp["paid_by_name"] == "Indira"

    assignments = json.loads(exp["assignments_json"])
    assert "Indira" in assignments[0]["people"]
    assert "Indhu" not in assignments[0]["people"]

    shares = json.loads(exp["shares_json"])
    assert "Indira" in shares
    assert "Indhu" not in shares
    assert shares["Indira"] == 10000


def test_delete_member_blocked_when_used(test_db):
    """
    Deleting a member who has expenses, shares, or payments must be blocked with a clear reason.
    An unused member can be safely deleted.
    """
    # 1. Freshly added unused member can be deleted
    new_m = db.add_member("Maya")
    maya_id = new_m["id"]

    in_use, reason = db.is_member_in_use(maya_id)
    assert in_use is False
    assert reason == ""

    # Delete Maya
    db.delete_member(maya_id)
    assert db.get_member_by_id(maya_id) is None

    # 2. Member who has an expense as payer CANNOT be deleted
    members = db.get_members()
    karthik = next(m for m in members if m["name"] == "Karthik")
    karthik_id = karthik["id"]

    db.create_expense(
        description="Lunch",
        paid_by=karthik_id,
        total_minor=10000,
        items_json="[]",
        assignments_json=json.dumps([{"item_id": 1, "people": ["Karthik"]}]),
        shares_json=json.dumps({"Karthik": 10000})
    )

    in_use_karthik, reason_karthik = db.is_member_in_use(karthik_id)
    assert in_use_karthik is True
    assert "Cannot delete 'Karthik'" in reason_karthik
