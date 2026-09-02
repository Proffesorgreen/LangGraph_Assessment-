"""
db_setup.py — Create and seed the SQLite customer database.

Run this ONCE before using part2_langgraph.py:
    python db_setup.py

Creates support_tickets.db with a 'customers' table populated
from the expanded mock data.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "support_tickets.db")

# Full customer seed data (previously in mock_data.py CUSTOMERS dict)
SEED_CUSTOMERS = [
    # customer_id, name, tier, open_tickets, past_escalations, account_age_days
    ("C001", "Alice Johnson",   "free",       0, 0,    45),
    ("C002", "Bob Martinez",    "pro",        2, 1,   380),
    ("C003", "Carol Chen",      "enterprise", 3, 4,  1100),
    ("C004", "Dave Okafor",     "pro",        0, 0,   200),
    ("C005", "Emily Park",      "free",       1, 0,    10),
    ("C006", "Fatima Rossi",    "pro",        4, 2,   550),
    ("C007", "George Tanaka",   "enterprise", 0, 0,    60),
    ("C008", "Hassan Ali",      "free",       0, 3,   730),
    ("C009", "Ines Dubois",     "pro",        1, 0,    90),
    ("C010", "Julia Andersen",  "enterprise", 5, 7,  2000),
]


def init_db(db_path: str = DB_PATH) -> None:
    """Create schema and seed customers table (idempotent)."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id      TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            tier             TEXT NOT NULL,
            open_tickets     INTEGER DEFAULT 0,
            past_escalations INTEGER DEFAULT 0,
            account_age_days INTEGER DEFAULT 0
        )
    """)

    # Upsert so re-running is safe
    cur.executemany("""
        INSERT INTO customers
            (customer_id, name, tier, open_tickets, past_escalations, account_age_days)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(customer_id) DO UPDATE SET
            name             = excluded.name,
            tier             = excluded.tier,
            open_tickets     = excluded.open_tickets,
            past_escalations = excluded.past_escalations,
            account_age_days = excluded.account_age_days
    """, SEED_CUSTOMERS)

    conn.commit()
    conn.close()
    print(f"[db_setup] Database ready at: {db_path}")
    print(f"[db_setup] Seeded {len(SEED_CUSTOMERS)} customers.")


if __name__ == "__main__":
    init_db()
