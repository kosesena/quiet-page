"""Load the scenario set and build a fresh store, rail and session context for one scenario."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .gateway import Context
from .rail import FakeRail
from .store import Store

DATA = Path(__file__).resolve().parent.parent / "docs" / "senaryolar"


def load_scenarios(path: Path = DATA / "scenarios.json") -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data["scenarios"]


def load_records(path: Path = DATA / "store_records.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build(scenario: dict, records: dict | None = None) -> tuple[Store, FakeRail, Context]:
    """Baseline store + the scenario's preconditions (earlier refunds, live reservations)."""
    pre = scenario["preconditions"]
    store = Store(records or load_records())
    for r in pre.get("required_refund_records", []):
        order_no = pre["target_attempt"].get("order_no") or scenario["ground_truth"]["order_no"]
        store.db.execute(
            "INSERT OR REPLACE INTO refunds VALUES (?,?,?,?,?)",
            (r["refund_id"], order_no, r.get("rma_id"), r["amount"], r["status"]),
        )
    for res in pre.get("active_reservations", []):
        store.db.execute(
            "INSERT INTO reservations VALUES (?,?,?,?,?,?,'active')",
            (
                res["reservation_id"],
                res["order_no"],
                res.get("rma_id"),
                res["amount"],
                res["session_id"],
                res.get("refund_id"),
            ),
        )
    rail = FakeRail.from_store(store)
    for r in pre.get("required_refund_records", []):  # completed refunds also count on the rail side,
        order = store.orders[scenario["ground_truth"]["order_no"]]  # unless the fixture order already has them
        if r["status"] == "completed" and r["refund_id"] not in {x["refund_id"] for x in order.get("refunds", [])}:
            rail.txns[order["braintree_transaction_id"]].refunded += Decimal(r["amount"])
    ctx = Context(
        session_id=pre["session_id"],
        customer_id=pre["authenticated_customer_id"],
        allowed_tools=frozenset(pre["allowed_tools"]),
        reader=pre.get("reader_contract"),
        as_of=datetime.fromisoformat(pre["as_of"].replace("Z", "+00:00")),
    )
    return store, rail, ctx


def attempt(scenario: dict) -> tuple[str, dict]:
    a = dict(scenario["preconditions"]["target_attempt"])
    return a.pop("tool"), a
