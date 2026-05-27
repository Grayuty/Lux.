"""
database.py — SQLite database layer
Handles all DB operations: materials, payments, users, cart
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot.db")


def get_conn() -> sqlite3.Connection:
    """Return a connection with row_factory so rows behave like dicts."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db():
    """Create tables if they don't exist and seed sample materials on first run."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS materials (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                price       INTEGER NOT NULL,
                description TEXT    NOT NULL,
                active      INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS payments (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id   INTEGER NOT NULL,
                telegram_username  TEXT    NOT NULL,
                first_name         TEXT    NOT NULL,
                material_id        INTEGER NOT NULL DEFAULT 0,
                material_name      TEXT    NOT NULL DEFAULT 'Cart Purchase',
                amount             INTEGER NOT NULL,
                reference          TEXT    UNIQUE NOT NULL,
                token              TEXT    UNIQUE NOT NULL,
                status             TEXT    NOT NULL DEFAULT 'pending',
                cart_snapshot      TEXT,
                paid_at            TEXT,
                created_at         TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                telegram_user_id INTEGER PRIMARY KEY,
                username         TEXT,
                first_name       TEXT,
                first_seen       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cart_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                material_id INTEGER NOT NULL,
                quantity    INTEGER NOT NULL DEFAULT 1,
                UNIQUE(user_id, material_id)
            );
        """)

        # Migrate existing payments table: add cart_snapshot if missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(payments)").fetchall()]
        if "cart_snapshot" not in cols:
            conn.execute("ALTER TABLE payments ADD COLUMN cart_snapshot TEXT")
            logger.info("Migrated payments table: added cart_snapshot column.")

        # Seed sample materials only on first run
        count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        if count == 0:
            _seed_materials(conn)
            logger.info("Sample materials seeded into database.")


def _seed_materials(conn: sqlite3.Connection):
    samples = [
        ("Mathematics Study Pack",      2000, "Algebra, calculus, statistics — full notes with past questions."),
        ("English Language & Lit Pack", 1500, "Grammar, essay writing, comprehension, and literature guides."),
        ("Physics Study Pack",          2000, "Mechanics, waves, electricity, optics — worked solutions included."),
        ("Chemistry Study Pack",        2000, "Organic, inorganic & physical chemistry with WAEC/JAMB tips."),
        ("Biology Study Pack",          1500, "Cells, genetics, ecology, human biology — detailed diagrams."),
        ("Complete Bundle (5 Packs)",   7500, "All five packs at a bundled discount. Best value!"),
    ]
    conn.executemany(
        "INSERT INTO materials (name, price, description) VALUES (?, ?, ?)",
        samples,
    )


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def add_material(name: str, price: int, description: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO materials (name, price, description) VALUES (?, ?, ?)",
            (name, price, description),
        )
        return cur.lastrowid


def get_active_materials() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM materials WHERE active = 1 ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_materials() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM materials ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_material(material_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM materials WHERE id = ?", (material_id,)
        ).fetchone()
        return dict(row) if row else None


def deactivate_material(material_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE materials SET active = 0 WHERE id = ?", (material_id,)
        )
        return cur.rowcount > 0


def activate_material(material_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE materials SET active = 1 WHERE id = ?", (material_id,)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

def add_to_cart(user_id: int, material_id: int) -> dict:
    """
    Add one unit of material_id to the user's cart.
    If already present, increment quantity by 1.
    Returns {"added": True, "quantity": N}.
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT quantity FROM cart_items WHERE user_id=? AND material_id=?",
            (user_id, material_id),
        ).fetchone()

        if existing:
            new_qty = existing["quantity"] + 1
            conn.execute(
                "UPDATE cart_items SET quantity=? WHERE user_id=? AND material_id=?",
                (new_qty, user_id, material_id),
            )
        else:
            new_qty = 1
            conn.execute(
                "INSERT INTO cart_items (user_id, material_id, quantity) VALUES (?, ?, 1)",
                (user_id, material_id),
            )
    return {"added": True, "quantity": new_qty}


def remove_from_cart(user_id: int, material_id: int) -> bool:
    """
    Remove one unit of material_id from the cart.
    If quantity becomes 0, the row is deleted.
    Returns True if the row existed.
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT quantity FROM cart_items WHERE user_id=? AND material_id=?",
            (user_id, material_id),
        ).fetchone()
        if not existing:
            return False
        if existing["quantity"] <= 1:
            conn.execute(
                "DELETE FROM cart_items WHERE user_id=? AND material_id=?",
                (user_id, material_id),
            )
        else:
            conn.execute(
                "UPDATE cart_items SET quantity=quantity-1 WHERE user_id=? AND material_id=?",
                (user_id, material_id),
            )
    return True


def clear_cart(user_id: int):
    """Delete all cart items for a user."""
    with get_conn() as conn:
        conn.execute("DELETE FROM cart_items WHERE user_id=?", (user_id,))


def get_cart(user_id: int) -> list[dict]:
    """
    Return the user's cart as a list of enriched dicts:
    [{material_id, name, price, quantity, subtotal}, ...]
    Only includes materials that are still active.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ci.material_id, ci.quantity,
                   m.name, m.price, m.active
            FROM cart_items ci
            JOIN materials m ON m.id = ci.material_id
            WHERE ci.user_id = ?
            ORDER BY ci.id
            """,
            (user_id,),
        ).fetchall()

    items = []
    for r in rows:
        items.append({
            "material_id": r["material_id"],
            "name":        r["name"],
            "price":       r["price"],
            "quantity":    r["quantity"],
            "subtotal":    r["price"] * r["quantity"],
            "active":      r["active"],
        })
    return items


def calculate_cart_total(user_id: int) -> int:
    """Return the total Naira amount for a user's cart."""
    items = get_cart(user_id)
    return sum(i["subtotal"] for i in items)


def cart_item_count(user_id: int) -> int:
    """Return the total number of units in the cart."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM cart_items WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

def create_payment(
    telegram_user_id: int,
    telegram_username: str,
    first_name: str,
    amount: int,
    reference: str,
    token: str,
    cart_snapshot: list[dict],
    material_id: int = 0,
    material_name: str = "Cart Purchase",
) -> int:
    """
    Save a new pending payment record.
    cart_snapshot is a list of {name, price, quantity, subtotal} dicts.
    Returns the new row ID.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    snapshot_json = json.dumps(cart_snapshot)
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO payments
               (telegram_user_id, telegram_username, first_name,
                material_id, material_name, amount,
                reference, token, status, cart_snapshot, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (telegram_user_id, telegram_username, first_name,
             material_id, material_name, amount,
             reference, token, snapshot_json, now),
        )
        return cur.lastrowid


def get_payment_by_reference(reference: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE reference = ?", (reference,)
        ).fetchone()
        if not row:
            return None
        rec = dict(row)
        # Deserialize the cart snapshot
        if rec.get("cart_snapshot"):
            try:
                rec["cart_snapshot"] = json.loads(rec["cart_snapshot"])
            except (json.JSONDecodeError, TypeError):
                rec["cart_snapshot"] = []
        return rec


def mark_payment_paid(reference: str) -> dict | None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET status = 'paid', paid_at = ? WHERE reference = ?",
            (now, reference),
        )
    return get_payment_by_reference(reference)


def payment_already_verified(reference: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM payments WHERE reference = ?", (reference,)
        ).fetchone()
        return row is not None and row["status"] == "paid"


def get_all_payments(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM payments ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        rec = dict(r)
        if rec.get("cart_snapshot"):
            try:
                rec["cart_snapshot"] = json.loads(rec["cart_snapshot"])
            except Exception:
                rec["cart_snapshot"] = []
        result.append(rec)
    return result


def get_payment_stats() -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status='paid'"
        ).fetchone()[0]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status='paid'"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status='pending'"
        ).fetchone()[0]
        return {"total_paid": total, "total_revenue": revenue, "pending": pending}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def upsert_user(telegram_user_id: int, username: str, first_name: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (telegram_user_id, username, first_name, first_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(telegram_user_id) DO UPDATE SET
                   username = excluded.username,
                   first_name = excluded.first_name""",
            (telegram_user_id, username or "", first_name or "", now),
        )


def get_all_user_ids() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT telegram_user_id FROM users").fetchall()
        return [r["telegram_user_id"] for r in rows]
