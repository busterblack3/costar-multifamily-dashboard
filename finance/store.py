"""SQLite storage for accounts, transactions, categorization rules, and budgets.

Design notes:
- Money is stored as integer cents (see ``money.py``).
- A transaction's identity is ``(account_id, txn_id)``; ``sync`` upserts and
  **never clobbers** a row's manual category or note.
- Everything lives under a git-ignored data dir (default ``.finance/``), so
  financial data and credentials are never committed.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Optional

from . import money
from .simplefin import Account, Transaction

DEFAULT_DIR = Path(os.environ.get("FINANCE_DIR", ".finance"))
DB_NAME = "finance.db"
CONFIG_NAME = "config.json"

TRANSFER_CATEGORY = "Transfer"


SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    org             TEXT,
    currency        TEXT DEFAULT 'USD',
    balance_cents   INTEGER,
    available_cents INTEGER,
    balance_date    INTEGER
);

CREATE TABLE IF NOT EXISTS transactions (
    account_id      TEXT NOT NULL,
    txn_id          TEXT NOT NULL,
    posted          INTEGER NOT NULL,
    amount_cents    INTEGER NOT NULL,
    description     TEXT,
    payee           TEXT,
    memo            TEXT,
    pending         INTEGER DEFAULT 0,
    category        TEXT,
    manual_category INTEGER DEFAULT 0,
    note            TEXT,
    PRIMARY KEY (account_id, txn_id)
);
CREATE INDEX IF NOT EXISTS idx_txn_posted ON transactions(posted);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);

CREATE TABLE IF NOT EXISTS rules (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern  TEXT NOT NULL,
    field    TEXT NOT NULL DEFAULT 'both',   -- payee | description | both
    is_regex INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS budgets (
    category      TEXT PRIMARY KEY,
    monthly_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, data_dir: Path | str = DEFAULT_DIR):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / DB_NAME
        self.config_path = self.dir / CONFIG_NAME
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # -- credentials / config ---------------------------------------------
    def get_access_url(self) -> Optional[str]:
        """Access URL from env (preferred for cloud) or the local config file."""
        env = os.environ.get("SIMPLEFIN_ACCESS_URL")
        if env:
            return env.strip()
        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text())
                if cfg.get("access_url"):
                    return cfg["access_url"]
            except Exception:  # noqa: BLE001
                return None
        return None

    def save_access_url(self, access_url: str) -> None:
        cfg = {}
        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text())
            except Exception:  # noqa: BLE001
                cfg = {}
        cfg["access_url"] = access_url
        self.config_path.write_text(json.dumps(cfg, indent=2))
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass

    # -- meta --------------------------------------------------------------
    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # -- accounts / transactions ------------------------------------------
    def upsert_account(self, a: Account) -> None:
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO accounts(id, name, org, currency, balance_cents,
                                     available_cents, balance_date)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    org=excluded.org,
                    currency=excluded.currency,
                    balance_cents=excluded.balance_cents,
                    available_cents=excluded.available_cents,
                    balance_date=excluded.balance_date
                """,
                (
                    a.id,
                    a.name,
                    a.org.name,
                    a.currency,
                    money.to_cents(a.balance),
                    money.to_cents(a.available_balance)
                    if a.available_balance is not None
                    else None,
                    a.balance_date,
                ),
            )

    def upsert_transaction(self, account_id: str, t: Transaction) -> bool:
        """Insert or update a transaction. Returns True if it was newly inserted.

        Manual category and note are preserved across syncs; the auto category
        is only filled by categorization, not here.
        """
        existing = self.conn.execute(
            "SELECT 1 FROM transactions WHERE account_id=? AND txn_id=?",
            (account_id, t.id),
        ).fetchone()
        is_new = existing is None
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO transactions(
                    account_id, txn_id, posted, amount_cents, description,
                    payee, memo, pending)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id, txn_id) DO UPDATE SET
                    posted=excluded.posted,
                    amount_cents=excluded.amount_cents,
                    description=excluded.description,
                    payee=excluded.payee,
                    memo=excluded.memo,
                    pending=excluded.pending
                """,
                (
                    account_id,
                    t.id,
                    t.posted,
                    money.to_cents(t.amount),
                    t.description,
                    t.payee,
                    t.memo,
                    1 if t.pending else 0,
                ),
            )
        return is_new

    def ingest(self, accounts: Iterable[Account]) -> dict:
        """Store a set of accounts + their transactions. Returns counts."""
        accounts = list(accounts)
        n_new = n_txn = 0
        for a in accounts:
            self.upsert_account(a)
            for t in a.transactions:
                n_txn += 1
                if self.upsert_transaction(a.id, t):
                    n_new += 1
        return {"accounts": len(accounts), "transactions": n_txn, "new": n_new}

    # -- queries -----------------------------------------------------------
    def accounts(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM accounts ORDER BY name"
        ).fetchall()

    def account_name(self, account_id: str) -> str:
        row = self.conn.execute(
            "SELECT name FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
        return row["name"] if row else account_id

    def transactions(
        self,
        *,
        start: Optional[int] = None,
        end: Optional[int] = None,
        account_id: Optional[str] = None,
        uncategorized: bool = False,
        include_pending: bool = True,
        limit: Optional[int] = None,
        order: str = "DESC",
    ) -> list[sqlite3.Row]:
        clauses, args = [], []
        if start is not None:
            clauses.append("posted >= ?")
            args.append(int(start))
        if end is not None:
            clauses.append("posted < ?")
            args.append(int(end))
        if account_id:
            clauses.append("account_id = ?")
            args.append(account_id)
        if uncategorized:
            clauses.append("(category IS NULL OR category = '')")
        if not include_pending:
            clauses.append("pending = 0")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "DESC" if str(order).upper() != "ASC" else "ASC"
        sql = f"SELECT * FROM transactions {where} ORDER BY posted {order}, rowid {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql, args).fetchall()

    def set_category(
        self, account_id: str, txn_id: str, category: str, *, manual: bool
    ) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE transactions SET category=?, manual_category=? "
                "WHERE account_id=? AND txn_id=?",
                (category, 1 if manual else 0, account_id, txn_id),
            )

    def set_note(self, account_id: str, txn_id: str, note: str) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE transactions SET note=? WHERE account_id=? AND txn_id=?",
                (note, account_id, txn_id),
            )

    # -- rules -------------------------------------------------------------
    def rules(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM rules ORDER BY priority DESC, id ASC"
        ).fetchall()

    def add_rule(
        self,
        pattern: str,
        category: str,
        *,
        field: str = "both",
        is_regex: bool = False,
        priority: int = 100,
    ) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO rules(pattern, field, is_regex, category, priority) "
                "VALUES(?,?,?,?,?)",
                (pattern, field, 1 if is_regex else 0, category, priority),
            )
            return cur.lastrowid

    def rule_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS n FROM rules").fetchone()["n"]

    # -- budgets -----------------------------------------------------------
    def set_budget(self, category: str, monthly_cents: int) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO budgets(category, monthly_cents) VALUES(?,?) "
                "ON CONFLICT(category) DO UPDATE SET monthly_cents=excluded.monthly_cents",
                (category, monthly_cents),
            )

    def budgets(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT category, monthly_cents FROM budgets").fetchall()
        return {r["category"]: r["monthly_cents"] for r in rows}

    def categories(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM transactions "
            "WHERE category IS NOT NULL AND category != '' ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]
