"""Payment rail adapters. The gateway talks to a Rail; only the gateway holds rail credentials.

FakeRail models what the Braintree sandbox did with a test card on 23 Oct (docs/arastirma/2026-10-23-braintree-deneme.md):
refunds above the remaining transaction total fail with 91521, refunds on a fully refunded transaction with 91512,
refunds before settlement with 91506, and an identical sale (same payment method and amount) soon after another one
with "Gateway Rejected: duplicate". Mocked PayPal in the sandbox does NOT enforce the refund total; the fake does,
because production would.
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class RailResult:
    ok: bool
    id: str | None = None
    status: str | None = None  # rail status, e.g. 'settling', 'submitted_for_settlement'
    error: str | None = None  # e.g. '91521 Refund amount is too large.'


class Rail(Protocol):
    def refund(self, transaction_id: str, amount: Decimal) -> RailResult: ...
    def refunded_total(self, transaction_id: str) -> Decimal | None: ...
    def void(self, transaction_id: str) -> RailResult: ...
    def charge(self, payment_method_token: str, amount: Decimal, order_id: str) -> RailResult: ...
    def find(self, transaction_id: str) -> dict | None: ...


@dataclass
class FakeTxn:
    amount: Decimal
    status: str = "settled"
    refunded: Decimal = Decimal("0.00")
    refund_ids: list[str] = field(default_factory=list)


class FakeRail:
    """In-memory stand-in with card-like limits. `calls` records every request that reached the rail."""

    def __init__(self, transactions: dict[str, FakeTxn] | None = None):
        self.txns = transactions or {}
        self.calls: list[tuple] = []
        self._ids = itertools.count(1)
        self._sales: set[tuple[str, Decimal]] = set()

    @classmethod
    def from_store(cls, store) -> FakeRail:
        txns = {}
        for o in store.orders.values():
            refunded = sum(
                (Decimal(r["amount"]) for r in o.get("refunds", []) if r["status"] == "completed"), Decimal("0.00")
            )
            txns[o["braintree_transaction_id"]] = FakeTxn(Decimal(o["total"]), o.get("status", "settled"), refunded)
        return cls(txns)

    def refund(self, transaction_id, amount):
        self.calls.append(("refund", transaction_id, amount))
        t = self.txns.get(transaction_id)
        if t is None:
            return RailResult(False, error="91504 Transaction not found.")
        if t.status != "settled":
            return RailResult(False, error="91506 Cannot refund transaction unless it is settled.")
        if t.refunded >= t.amount:
            return RailResult(False, error="91512 Transaction has already been fully refunded.")
        if t.refunded + amount > t.amount:
            return RailResult(False, error="91521 Refund amount is too large.")
        t.refunded += amount
        rid = f"fake-refund-{next(self._ids)}"
        t.refund_ids.append(rid)
        return RailResult(True, rid, "submitted_for_settlement")

    def void(self, transaction_id):
        self.calls.append(("void", transaction_id))
        t = self.txns.get(transaction_id)
        if t is None or t.status not in ("authorized", "submitted_for_settlement"):
            return RailResult(
                False, error="91504 Transaction can only be voided if authorized or submitted for settlement."
            )
        t.status = "voided"
        return RailResult(True, transaction_id, "voided")

    def money_calls(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in ("refund", "void", "charge")]

    def refunded_total(self, transaction_id):
        t = self.txns.get(transaction_id)
        return None if t is None else t.refunded

    def charge(self, payment_method_token, amount, order_id):
        self.calls.append(("charge", payment_method_token, amount, order_id))
        if (payment_method_token, amount) in self._sales:
            return RailResult(False, error="Gateway Rejected: duplicate")
        self._sales.add((payment_method_token, amount))
        tid = f"fake-sale-{next(self._ids)}"
        self.txns[tid] = FakeTxn(amount, "submitted_for_settlement")
        return RailResult(True, tid, "submitted_for_settlement")

    def find(self, transaction_id):
        self.calls.append(("find", transaction_id))
        t = self.txns.get(transaction_id)
        if t is None:
            return None
        return {
            "id": transaction_id,
            "amount": str(t.amount),
            "status": t.status,
            "refunded": str(t.refunded),
            "refund_ids": list(t.refund_ids),
        }


class BraintreeRail:
    """Braintree sandbox. Sandbox only; production keys are refused."""

    def __init__(self):
        import braintree  # imported lazily so tests run without the SDK configured

        if os.environ.get("BRAINTREE_ENVIRONMENT") != "sandbox":
            raise RuntimeError("Counterfoil only talks to the Braintree sandbox")
        self.bt = braintree
        self.gw = braintree.BraintreeGateway(
            braintree.Configuration(
                environment=braintree.Environment.Sandbox,
                merchant_id=os.environ["BRAINTREE_MERCHANT_ID"],
                public_key=os.environ["BRAINTREE_PUBLIC_KEY"],
                private_key=os.environ["BRAINTREE_PRIVATE_KEY"],
            )
        )

    @staticmethod
    def _result(r) -> RailResult:
        if r.is_success:
            t = r.transaction
            return RailResult(True, t.id, t.status)
        errors = "; ".join(f"{e.code} {e.message}" for e in r.errors.deep_errors) or r.message
        return RailResult(False, error=errors)

    def refund(self, transaction_id, amount):
        return self._result(self.gw.transaction.refund(transaction_id, str(amount)))

    def void(self, transaction_id):
        return self._result(self.gw.transaction.void(transaction_id))

    def charge(self, payment_method_token, amount, order_id):
        return self._result(
            self.gw.transaction.sale(
                {
                    "amount": str(amount),
                    "payment_method_token": payment_method_token,
                    "order_id": order_id,
                    "options": {"submit_for_settlement": True},
                }
            )
        )

    def refunded_total(self, transaction_id):
        """Sum of non-failed refunds the rail holds for this transaction (for reconciliation)."""
        try:
            t = self.gw.transaction.find(transaction_id)
        except self.bt.exceptions.NotFoundError:
            return None
        total = Decimal("0.00")
        for rid in t.refund_ids:
            r = self.gw.transaction.find(rid)
            if r.status not in ("failed", "gateway_rejected", "processor_declined", "voided"):
                total += Decimal(str(r.amount))
        return total

    def find(self, transaction_id):
        try:
            t = self.gw.transaction.find(transaction_id)
        except self.bt.exceptions.NotFoundError:
            return None
        return {
            "id": t.id,
            "amount": str(t.amount),
            "status": t.status,
            "refund_ids": list(t.refund_ids),
            "payment_instrument_type": t.payment_instrument_type,
        }


class SandboxRail(BraintreeRail):
    """Braintree sandbox behind the store's fixture ids, for end-to-end evaluation runs.

    The scenarios name fixture transactions (fixture-txn-001) and vaulted methods (fixture-vault-02). The first time a
    run touches one, a real sandbox counterpart is created: a mocked-PayPal sale for the order total (plus any refunds
    the store already completed), or a vaulted mocked-PayPal customer. Everything after that hits Braintree for real,
    so a run leaves real sandbox transactions behind; `money_calls()` reports them next to the fixture id.
    """

    def __init__(self, store, run_tag: str):
        super().__init__()
        self.store, self.tag = store, run_tag
        self.orders = {o["braintree_transaction_id"]: o for o in store.orders.values()}
        self.real: dict[str, str] = {}  # fixture id -> sandbox id
        self.calls: list[tuple] = []

    def _txn(self, fixture_id: str) -> str | None:
        if fixture_id not in self.real:
            o = self.orders.get(fixture_id)
            if o is None:
                return None
            sale = {
                "amount": str(o["total"]),
                "payment_method_nonce": "fake-paypal-one-time-nonce",
                "order_id": f"{self.tag}:{o['order_no']}",
                "options": {"submit_for_settlement": True},
            }
            if os.environ.get("BRAINTREE_MERCHANT_ACCOUNT_ID"):
                sale["merchant_account_id"] = os.environ["BRAINTREE_MERCHANT_ACCOUNT_ID"]
            r = self.gw.transaction.sale(sale)
            if not r.is_success:
                raise RuntimeError(f"sandbox setup sale for {o['order_no']} failed: {r.message}")
            self.real[fixture_id] = r.transaction.id
            done = self.store.db.execute(
                "SELECT amount FROM refunds WHERE order_no=? AND status='completed'", (o["order_no"],)
            ).fetchall()
            for (amount,) in done:  # history the scenario says already happened
                self.gw.transaction.refund(r.transaction.id, str(amount))
        return self.real[fixture_id]

    def _vault(self, fixture_token: str) -> str:
        if fixture_token not in self.real:
            c = self.gw.customer.create({"payment_method_nonce": "fake-paypal-billing-agreement-nonce"})
            if not c.is_success:
                raise RuntimeError(f"sandbox vault setup failed: {c.message}")
            self.real[fixture_token] = c.customer.payment_methods[0].token
        return self.real[fixture_token]

    def money_calls(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in ("refund", "void", "charge")]

    def refund(self, transaction_id, amount):
        real = self._txn(transaction_id)
        out = RailResult(False, error="91504 Transaction not found.") if real is None else super().refund(real, amount)
        self.calls.append(("refund", transaction_id, amount, real, out.id))
        return out

    def void(self, transaction_id):
        real = self._txn(transaction_id)
        out = RailResult(False, error="91504 Transaction not found.") if real is None else super().void(real)
        self.calls.append(("void", transaction_id, real))
        return out

    def charge(self, payment_method_token, amount, order_id):
        out = super().charge(self._vault(payment_method_token), amount, f"{self.tag}:{order_id}")
        self.calls.append(("charge", payment_method_token, amount, order_id, out.id))
        return out

    def refunded_total(self, transaction_id):
        real = self._txn(transaction_id)
        return None if real is None else super().refunded_total(real)

    def find(self, transaction_id):
        real = self._txn(transaction_id)
        self.calls.append(("find", transaction_id, real))
        data = None if real is None else super().find(real)
        return None if data is None else {**data, "id": transaction_id, "braintree_id": real}
