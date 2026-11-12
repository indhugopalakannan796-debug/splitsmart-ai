import sqlite3
import os
import json
from typing import List, Dict, Any, Optional, Tuple

DB_PATH = os.environ.get("SQLITE_DB_PATH", "splitsmart.db")
DEFAULT_MEMBERS = ["Indhu", "Ravi", "Priya", "Karthik", "Arun"]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT,
                paid_by INTEGER NOT NULL,
                total_minor INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                assignments_json TEXT NOT NULL,
                shares_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (paid_by) REFERENCES members(id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_id INTEGER,
                from_member INTEGER NOT NULL,
                to_member INTEGER NOT NULL,
                amount_minor INTEGER NOT NULL,
                paypal_order_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                approve_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (expense_id) REFERENCES expenses(id),
                FOREIGN KEY (from_member) REFERENCES members(id),
                FOREIGN KEY (to_member) REFERENCES members(id)
            );
        """)
        
        # Seed members if empty
        cursor.execute("SELECT COUNT(*) FROM members;")
        count = cursor.fetchone()[0]
        if count == 0:
            for name in DEFAULT_MEMBERS:
                cursor.execute("INSERT OR IGNORE INTO members (name) VALUES (?);", (name,))
        conn.commit()


def reset_db() -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM payments;")
        cursor.execute("DELETE FROM expenses;")
        cursor.execute("DELETE FROM members;")
        for name in DEFAULT_MEMBERS:
            cursor.execute("INSERT INTO members (name) VALUES (?);", (name,))
        conn.commit()


def get_members() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM members ORDER BY id ASC;")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_member_by_name(name: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM members WHERE LOWER(name) = LOWER(?);", (name.strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_member_by_id(member_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM members WHERE id = ?;", (member_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_or_create_member(name: str) -> Dict[str, Any]:
    clean_name = name.strip()
    existing = get_member_by_name(clean_name)
    if existing:
        return existing
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO members (name) VALUES (?);", (clean_name,))
        conn.commit()
        new_id = cursor.lastrowid
        return {"id": new_id, "name": clean_name}


def add_member(name: str) -> Dict[str, Any]:
    clean_name = name.strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO members (name) VALUES (?);", (clean_name,))
        conn.commit()
        return {"id": cursor.lastrowid, "name": clean_name}


def rename_member(member_id: int, new_name: str) -> Dict[str, Any]:
    clean_name = new_name.strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM members WHERE id = ?;", (member_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Member with id {member_id} not found")
        old_name = row["name"]

        cursor.execute("UPDATE members SET name = ? WHERE id = ?;", (clean_name, member_id))

        if old_name != clean_name:
            cursor.execute("SELECT id, assignments_json, shares_json FROM expenses;")
            expenses = cursor.fetchall()
            for exp in expenses:
                exp_id = exp["id"]
                raw_assign = exp["assignments_json"]
                raw_shares = exp["shares_json"]
                changed = False

                assign_data = []
                try:
                    assign_data = json.loads(raw_assign) if raw_assign else []
                    if isinstance(assign_data, list):
                        for item in assign_data:
                            if isinstance(item, dict) and "people" in item and isinstance(item["people"], list):
                                for idx, p in enumerate(item["people"]):
                                    if p == old_name:
                                        item["people"][idx] = clean_name
                                        changed = True
                except Exception:
                    pass

                shares_data = {}
                try:
                    shares_data = json.loads(raw_shares) if raw_shares else {}
                    if isinstance(shares_data, dict) and old_name in shares_data:
                        shares_data[clean_name] = shares_data.pop(old_name)
                        changed = True
                except Exception:
                    pass

                if changed:
                    cursor.execute(
                        "UPDATE expenses SET assignments_json = ?, shares_json = ? WHERE id = ?;",
                        (json.dumps(assign_data), json.dumps(shares_data), exp_id)
                    )

        conn.commit()
        return {"id": member_id, "name": clean_name}


def is_member_in_use(member_id: int) -> Tuple[bool, str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM members WHERE id = ?;", (member_id,))
        row = cursor.fetchone()
        if not row:
            return False, "Member not found"
        name = row["name"]

        # Check if member paid any expense
        cursor.execute("SELECT COUNT(*) FROM expenses WHERE paid_by = ?;", (member_id,))
        if cursor.fetchone()[0] > 0:
            return True, f"Cannot delete '{name}': they have recorded expenses as payer."

        # Check if member is involved in payments
        cursor.execute("SELECT COUNT(*) FROM payments WHERE from_member = ? OR to_member = ?;", (member_id, member_id))
        if cursor.fetchone()[0] > 0:
            return True, f"Cannot delete '{name}': they are involved in payment transactions."

        # Check if member is in shares or assignments of any existing expense
        cursor.execute("SELECT assignments_json, shares_json FROM expenses;")
        for exp in cursor.fetchall():
            try:
                shares = json.loads(exp["shares_json"] or "{}")
                if isinstance(shares, dict) and name in shares and shares[name] > 0:
                    return True, f"Cannot delete '{name}': they have assigned shares in existing expenses."
            except Exception:
                pass

            try:
                assignments = json.loads(exp["assignments_json"] or "[]")
                if isinstance(assignments, list):
                    for item in assignments:
                        if isinstance(item, dict) and name in item.get("people", []):
                            return True, f"Cannot delete '{name}': they are assigned items in existing expenses."
            except Exception:
                pass

    return False, ""


def delete_member(member_id: int) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM members WHERE id = ?;", (member_id,))
        conn.commit()


def create_expense(
    description: str,
    paid_by: int,
    total_minor: int,
    items_json: str,
    assignments_json: str,
    shares_json: str
) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO expenses (description, paid_by, total_minor, items_json, assignments_json, shares_json)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (description, paid_by, total_minor, items_json, assignments_json, shares_json)
        )
        conn.commit()
        return cursor.lastrowid


def get_expenses() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.*, m.name as paid_by_name
            FROM expenses e
            JOIN members m ON e.paid_by = m.id
            ORDER BY e.id DESC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def get_expense(expense_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.*, m.name as paid_by_name
            FROM expenses e
            JOIN members m ON e.paid_by = m.id
            WHERE e.id = ?;
            """,
            (expense_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def create_payment(
    expense_id: Optional[int],
    from_member: int,
    to_member: int,
    amount_minor: int,
    paypal_order_id: Optional[str] = None,
    approve_url: Optional[str] = None,
    status: str = "pending"
) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO payments (expense_id, from_member, to_member, amount_minor, paypal_order_id, approve_url, status)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (expense_id, from_member, to_member, amount_minor, paypal_order_id, approve_url, status)
        )
        conn.commit()
        return cursor.lastrowid


def update_payment(payment_id: int, status: str, paypal_order_id: Optional[str] = None, approve_url: Optional[str] = None) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        updates = ["status = ?"]
        params = [status]
        if paypal_order_id is not None:
            updates.append("paypal_order_id = ?")
            params.append(paypal_order_id)
        if approve_url is not None:
            updates.append("approve_url = ?")
            params.append(approve_url)
        params.append(payment_id)
        cursor.execute(f"UPDATE payments SET {', '.join(updates)} WHERE id = ?;", tuple(params))
        conn.commit()


def update_payment_by_order_id(order_id: str, status: str) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE payments SET status = ? WHERE paypal_order_id = ?;", (status, order_id))
        conn.commit()


def get_payment(payment_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.*, f.name as from_name, t.name as to_name
            FROM payments p
            JOIN members f ON p.from_member = f.id
            JOIN members t ON p.to_member = t.id
            WHERE p.id = ?;
            """,
            (payment_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_payment_by_order_id(order_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.*, f.name as from_name, t.name as to_name
            FROM payments p
            JOIN members f ON p.from_member = f.id
            JOIN members t ON p.to_member = t.id
            WHERE p.paypal_order_id = ?;
            """,
            (order_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_payments() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.*, f.name as from_name, t.name as to_name
            FROM payments p
            JOIN members f ON p.from_member = f.id
            JOIN members t ON p.to_member = t.id
            ORDER BY p.id DESC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]
