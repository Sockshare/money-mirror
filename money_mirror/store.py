"""Local store: transactions, learned category rules, and settings-adjacent data.

File: ~/.money_mirror/money.db  (SQLite, permission 600)
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import date

from .config import data_dir


def _db_path():
    return data_dir() / "money.db"


@contextmanager
def _conn():
    path = _db_path()
    if not path.exists():
        # Pre-create with private permissions so there is never a world-readable window.
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                merchant TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                raw_category TEXT,
                account TEXT,
                source_file TEXT,
                imported_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
            CREATE INDEX IF NOT EXISTS idx_txn_merchant ON transactions(merchant);
            CREATE TABLE IF NOT EXISTS rules (
                merchant TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                rows INTEGER,
                imported_at TEXT,
                first_date TEXT,
                last_date TEXT
            );
            """
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def txn_id(d: date, description: str, amount: float, account: str) -> str:
    """Stable id so re-importing the same export doesn't duplicate rows."""
    raw = f"{d.isoformat()}|{description.strip().lower()}|{amount:.2f}|{account.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def add_transactions(rows: list[dict], source_file: str) -> tuple[int, int]:
    """rows: dicts with date, description, merchant, amount, category, raw_category, account.
    Returns (added, duplicates_skipped)."""
    added = dup = 0
    seen_in_file: dict[str, int] = {}
    with _conn() as c:
        for r in rows:
            base = txn_id(r["date"], r["description"], r["amount"], r.get("account", ""))
            # Two genuinely identical rows in ONE file (e.g. two coffees same day) must both survive.
            n = seen_in_file.get(base, 0)
            seen_in_file[base] = n + 1
            tid = base if n == 0 else f"{base}-{n}"
            cur = c.execute(
                "INSERT OR IGNORE INTO transactions (id, date, description, merchant, amount, category, raw_category, account, source_file, imported_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
                (tid, r["date"].isoformat(), r["description"], r["merchant"], r["amount"], r["category"], r.get("raw_category", ""), r.get("account", ""), source_file),
            )
            if cur.rowcount:
                added += 1
            else:
                dup += 1
        if added:
            dates = [r["date"] for r in rows]
            c.execute(
                "INSERT INTO imports (filename, rows, imported_at, first_date, last_date) VALUES (?,?,datetime('now'),?,?)",
                (source_file, added, min(dates).isoformat(), max(dates).isoformat()),
            )
    return added, dup


def all_transactions() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM transactions ORDER BY date, id").fetchall()
    return [dict(r) for r in rows]


def count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


def set_category(txn_id_: str, category: str, learn_merchant: bool) -> int:
    """Change one transaction's category; optionally apply to every transaction of that merchant and remember it."""
    with _conn() as c:
        row = c.execute("SELECT merchant FROM transactions WHERE id = ?", (txn_id_,)).fetchone()
        if not row:
            return 0
        if learn_merchant:
            c.execute("INSERT OR REPLACE INTO rules (merchant, category, source) VALUES (?,?,'user')", (row["merchant"].lower(), category))
            cur = c.execute("UPDATE transactions SET category = ? WHERE merchant = ?", (category, row["merchant"]))
            return cur.rowcount
        cur = c.execute("UPDATE transactions SET category = ? WHERE id = ?", (category, txn_id_))
        return cur.rowcount


def rules() -> dict[str, str]:
    with _conn() as c:
        return {r["merchant"]: r["category"] for r in c.execute("SELECT merchant, category FROM rules")}


def add_rules(mapping: dict[str, str], source: str) -> None:
    with _conn() as c:
        for m, cat in mapping.items():
            c.execute("INSERT OR IGNORE INTO rules (merchant, category, source) VALUES (?,?,?)", (m.lower(), cat, source))
            c.execute("UPDATE transactions SET category = ? WHERE LOWER(merchant) = ? AND category = 'Other'", (cat, m.lower()))


def imports() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM imports ORDER BY id DESC")]


def delete_all() -> int:
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        c.execute("DELETE FROM transactions")
        c.execute("DELETE FROM imports")
        c.execute("DELETE FROM rules WHERE source != 'user'")
        return n


def delete_everything_including_rules() -> None:
    with _conn() as c:
        for t in ("transactions", "imports", "rules"):
            c.execute(f"DELETE FROM {t}")
