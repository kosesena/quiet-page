"""The merchant's system of record: orders, return records (RMAs), refunds, reservations and charges.

Orders, catalog and customers are read-only fixtures. Refunds, reservations and charges live in SQLite so that
"check remaining entitlement, then reserve it" is one transaction. The running app must pass a file path
(state has to survive a restart); ':memory:' is for tests.

Refund states: accepted (rail took it, not yet settled; counts as spent), completed, pending/unknown
(outcome not known: blocks new refunds on the order until reconciled), failed (does not count).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .money import parse_amount

SCHEMA = """
CREATE TABLE IF NOT EXISTS refunds (
    refund_id   TEXT PRIMARY KEY,
    order_no    TEXT NOT NULL,
    rma_id      TEXT,
    amount      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('accepted', 'completed', 'pending', 'failed', 'unknown'))
);
CREATE TABLE IF NOT EXISTS reservations (
    reservation_id TEXT PRIMARY KEY,
    order_no       TEXT NOT NULL,
    rma_id         TEXT,
    amount         TEXT NOT NULL,
    session_id     TEXT NOT NULL,
    refund_id      TEXT,
    status         TEXT NOT NULL CHECK (status IN ('active', 'released', 'settled'))
);
CREATE TABLE IF NOT EXISTS charges (
    request_id  TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    amount      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('requested', 'accepted', 'failed', 'unknown')),
    rail_id     TEXT
);
"""
SPENT = ("accepted", "completed")
UNRESOLVED = ("pending", "unknown")


@dataclass(frozen=True)
class Entitlement:
    approved: Decimal
    spent: Decimal  # accepted + completed refunds on this RMA
    reserved: Decimal  # in-flight reservations on this RMA
    unresolved: tuple[str, ...]  # refund ids on the ORDER (any RMA) whose outcome is not known

    @property
    def remaining(self) -> Decimal:
        return self.approved - self.spent - self.reserved

    @property
    def state(self) -> tuple[str, str]:
        """What a human saw when approving; execution refuses if this moved."""
        return str(self.spent), str(self.reserved)


class Store:
    def __init__(self, records: dict, db_path: str = ":memory:"):
        self.records = records
        self.policy = records["refund_policy"]
        self.catalog = {c["sku"]: c for c in records["catalog"]}
        self.customers = {c["customer_id"]: c for c in records["customers"]}
        self.orders = {o["order_no"]: o for o in records["orders"]}
        self.db = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self._lock = threading.RLock()  # one connection is shared; every statement goes through the lock
        with self._lock:
            self.db.executescript(SCHEMA)
            for order in self.orders.values():
                for r in order.get("refunds", []):
                    self.db.execute(
                        "INSERT OR IGNORE INTO refunds VALUES (?,?,?,?,?)",
                        (r["refund_id"], order["order_no"], r.get("rma_id"), r["amount"], r["status"]),
                    )

    @classmethod
    def from_file(cls, path: str | Path, db_path: str = ":memory:") -> Store:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), db_path)

    def sql(self, query: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self.db.execute(query, params).fetchall()

    # -- lookups ---------------------------------------------------------------------------------
    def customer_by_email(self, email: str) -> dict | None:
        email = email.strip().lower()
        return next((c for c in self.customers.values() if c["email"].lower() == email), None)

    def rma(self, order_no: str, rma_id: str | None) -> dict | None:
        order = self.orders.get(order_no)
        if not order or not rma_id:
            return None
        return next((r for r in order.get("returns", []) if r["rma_id"] == rma_id), None)

    def owns_token(self, customer_id: str, token: str) -> bool:
        methods = self.customers.get(customer_id, {}).get("vaulted_payment_methods", [])
        return any(m["token"] == token for m in methods)

    # -- refund state ----------------------------------------------------------------------------
    @contextmanager
    def transaction(self):
        """Serialises check-then-reserve (thread lock + BEGIN IMMEDIATE for other processes). Re-entrant."""
        with self._lock:
            if self.db.in_transaction:
                yield
                return
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def entitlement(self, order_no: str, rma_id: str | None) -> Entitlement:
        with self.transaction():
            rma = self.rma(order_no, rma_id)
            approved = parse_amount(rma["approved_refund_amount"]) if rma else Decimal("0.00")
            rows = self.db.execute(
                "SELECT amount, status FROM refunds WHERE order_no=? AND rma_id IS ?", (order_no, rma_id)
            ).fetchall()
            spent = sum((Decimal(a) for a, s in rows if s in SPENT), Decimal("0.00"))
            reserved = sum(
                (
                    Decimal(a)
                    for (a,) in self.db.execute(
                        "SELECT amount FROM reservations WHERE order_no=? AND rma_id IS ? AND status='active' AND refund_id IS NULL",
                        (order_no, rma_id),
                    )
                ),
                Decimal("0.00"),
            )
            unresolved = tuple(
                rid
                for (rid,) in self.db.execute(
                    f"SELECT refund_id FROM refunds WHERE order_no=? AND status IN {UNRESOLVED}",  # noqa: S608 - constant tuple
                    (order_no,),
                )
            )
            return Entitlement(approved, spent, reserved, unresolved)

    def order_refunded_total(self, order_no: str) -> Decimal:
        """Everything this store believes went out on the order, any RMA or none (accepted, completed, unknown)."""
        rows = self.sql(
            "SELECT amount FROM refunds WHERE order_no=? AND status IN ('accepted','completed','pending','unknown')",
            (order_no,),
        )
        return sum((Decimal(a) for (a,) in rows), Decimal("0.00"))

    def reserve(self, reservation_id: str, order_no: str, rma_id: str | None, amount: Decimal, session_id: str) -> None:
        with self.transaction():
            self.db.execute(
                "INSERT INTO reservations VALUES (?,?,?,?,?,NULL,'active')",
                (reservation_id, order_no, rma_id, str(amount), session_id),
            )

    def settle_reservation(self, reservation_id: str, refund_id: str, status: str) -> None:
        """Reservation → refund row in one transaction, so the amount is never counted as neither."""
        with self.transaction():
            row = self.db.execute(
                "SELECT order_no, rma_id, amount FROM reservations WHERE reservation_id=?", (reservation_id,)
            ).fetchone()
            new_state = "released" if status == "failed" else "settled"
            self.db.execute("INSERT OR REPLACE INTO refunds VALUES (?,?,?,?,?)", (refund_id, *row, status))
            self.db.execute(
                "UPDATE reservations SET status=?, refund_id=? WHERE reservation_id=?",
                (new_state, refund_id, reservation_id),
            )

    def release(self, reservation_id: str) -> None:
        with self.transaction():
            self.db.execute("UPDATE reservations SET status='released' WHERE reservation_id=?", (reservation_id,))

    def set_refund_status(self, refund_id: str, status: str) -> None:
        """Reconciliation: the rail told us how an accepted/unknown refund ended."""
        with self.transaction():
            self.db.execute("UPDATE refunds SET status=? WHERE refund_id=?", (status, refund_id))

    # -- charges ---------------------------------------------------------------------------------
    def charge_status(self, request_id: str) -> str | None:
        rows = self.sql("SELECT status FROM charges WHERE request_id=?", (request_id,))
        return rows[0][0] if rows else None

    def record_charge(
        self, request_id: str, customer_id: str, amount: Decimal, status: str, rail_id: str | None = None
    ) -> None:
        with self.transaction():
            self.db.execute(
                "INSERT OR REPLACE INTO charges VALUES (?,?,?,?,?)",
                (request_id, customer_id, str(amount), status, rail_id),
            )
