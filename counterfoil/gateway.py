"""The gateway: every money-moving or data-reading tool call from the transaction agent passes through here.

It never reads the customer email. It compares the call with the merchant's own record of *this* transaction:
the return record (RMA) for refunds, the catalog for charges, ownership for everything, and the Reader's
structured hand-off for intent. Findings have a severity: BLOCK (never executed, not overridable),
APPROVAL (held for a human), PASS.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .money import BadAmount, parse_amount, parse_qty
from .rail import Rail, RailResult
from .store import Store
from .views import order_view

PASS, APPROVAL, BLOCK = "PASS", "APPROVAL", "BLOCK"
_RANK = {PASS: 0, APPROVAL: 1, BLOCK: 2}
MONEY_TOOLS = {"refund", "charge", "void"}
APPROVAL_TTL = timedelta(minutes=30)
READER_REQUIRED = {
    "refund": ("istek", "siparis_no", "tutar", "para_birimi"),
    "void": ("istek", "siparis_no"),
    "charge": ("istek", "tutar", "para_birimi", "kalemler"),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Context:
    """Per inbound email. Built by the system from the mailbox envelope, never by an LLM."""

    session_id: str
    customer_id: str | None  # resolved from the envelope sender address
    allowed_tools: frozenset[str]
    reader: dict | None = None  # the Reader agent's structured hand-off
    as_of: datetime = field(default_factory=utcnow)  # business date (refund window); not the approval clock
    blocked_attempts: int = 0


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    detail: str


@dataclass
class Outcome:
    decision: str
    findings: list[Finding]
    rail_state: str = "not_called"  # not_called | succeeded | failed | unknown
    rail: RailResult | None = None
    data: dict | None = None
    approval_id: str | None = None

    @property
    def executed(self) -> bool:
        return self.rail_state == "succeeded"

    @property
    def reached_rail(self) -> bool:
        """Money may have moved: succeeded, or the outcome is unknown."""
        return self.rail_state in ("succeeded", "unknown")

    def summary(self) -> str:
        reasons = "; ".join(f"{f.code}: {f.detail}" for f in self.findings if f.severity != PASS)
        return f"{self.decision}/{self.rail_state}" + (f" ({reasons})" if reasons else "")


def _decide(findings: list[Finding]) -> str:
    return max((f.severity for f in findings), key=_RANK.__getitem__, default=PASS)


def _fingerprint(session_id: str, tool: str, args: dict) -> str:
    blob = json.dumps({"s": session_id, "t": tool, "a": args}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class Gateway:
    def __init__(self, store: Store, rail: Rail, clock: Callable[[], datetime] = utcnow):
        self.store = store
        self.rail = rail
        self.clock = clock
        self.pending: dict[str, dict] = {}
        self.log: list[dict] = []

    # -- entry point -----------------------------------------------------------------------------
    def handle(self, ctx: Context, tool: str, args: dict) -> Outcome:
        args = dict(args)
        findings = self.check(ctx, tool, args)
        decision = _decide(findings)
        if decision == BLOCK:
            ctx.blocked_attempts += 1
            out = Outcome(BLOCK, findings)
        elif decision == APPROVAL:
            approval_id = uuid.uuid4().hex
            self.pending[approval_id] = {
                "fp": _fingerprint(ctx.session_id, tool, args),
                "ctx": ctx,
                "tool": tool,
                "args": dict(args),
                "expires": self.clock() + APPROVAL_TTL,
                "accepted": {f.code for f in findings if f.severity == APPROVAL},
                "state": self._refund_state(tool, args),
            }
            out = Outcome(APPROVAL, findings, approval_id=approval_id)
        else:
            out = self._execute(ctx, tool, args, findings)
        self._record(ctx, tool, args, out)
        return out

    def approve(self, approval_id: str) -> Outcome:
        """A human approved a held call. Single use, time-limited, bound to the exact arguments and to the
        refund state the human saw. Checks are re-run; only the APPROVAL findings the human saw are accepted."""
        entry = self.pending.pop(approval_id, None)
        if entry is None:
            return Outcome(BLOCK, [Finding(BLOCK, "APPROVAL_UNKNOWN", "no such pending approval (or already used)")])
        ctx, tool, args = entry["ctx"], entry["tool"], entry["args"]
        if self.clock() > entry["expires"]:
            return Outcome(BLOCK, [Finding(BLOCK, "APPROVAL_EXPIRED", "approval window closed")])
        if _fingerprint(ctx.session_id, tool, args) != entry["fp"]:
            return Outcome(BLOCK, [Finding(BLOCK, "APPROVAL_TAMPERED", "arguments changed after approval")])
        findings = self.check(ctx, tool, args)
        new = [f for f in findings if f.severity == APPROVAL and f.code not in entry["accepted"]]
        if _decide(findings) == BLOCK or new:
            extra = (
                [Finding(BLOCK, "APPROVAL_STALE", f"new finding(s) since approval: {', '.join(f.code for f in new)}")]
                if new
                else []
            )
            out = Outcome(BLOCK, findings + extra)
        else:
            out = self._execute(ctx, tool, args, findings, approved=entry)
        self._record(ctx, tool, args, out, human_approved=True)
        return out

    def reject(self, approval_id: str) -> bool:
        return self.pending.pop(approval_id, None) is not None

    # -- checks ----------------------------------------------------------------------------------
    def check(self, ctx: Context, tool: str, args: dict) -> list[Finding]:
        if tool not in ctx.allowed_tools:
            return [Finding(BLOCK, "TOOL_NOT_ALLOWED", f"'{tool}' is not in this agent's tool list")]
        if not ctx.customer_id:
            return [Finding(BLOCK, "NO_CONTEXT", "no verified sender for this session; writes refused")]
        check = {
            "refund": self._check_refund,
            "charge": self._check_charge,
            "void": self._check_void,
            "lookup_transaction": self._check_lookup,
        }.get(tool)
        if check is None:
            return [Finding(BLOCK, "TOOL_NOT_ALLOWED", f"no gateway rule for '{tool}'")]
        findings = check(ctx, args)
        if tool in MONEY_TOOLS and ctx.blocked_attempts:
            findings.append(
                Finding(
                    APPROVAL, "PRIOR_BLOCKED_ATTEMPT", f"{ctx.blocked_attempts} blocked call(s) earlier in this session"
                )
            )
        return findings

    def _order(self, args: dict) -> tuple[dict | None, list[Finding]]:
        order = self.store.orders.get(str(args.get("order_no", "")))
        if order is None:
            return None, [Finding(BLOCK, "UNKNOWN_ORDER", f"order {args.get('order_no')!r} is not in the store record")]
        txn = args.get("braintree_transaction_id")
        if txn is not None and str(txn) != order["braintree_transaction_id"]:
            return None, [
                Finding(
                    BLOCK,
                    "TRANSACTION_ORDER_MISMATCH",
                    f"transaction {txn} does not belong to order {order['order_no']}",
                )
            ]
        return order, []

    def _check_lookup(self, ctx, args):
        order, f = self._order(args)
        if order is None:
            return f
        if order["customer_id"] != ctx.customer_id:
            return [Finding(BLOCK, "SCOPE_NOT_ALLOWED", f"order {order['order_no']} belongs to another customer")]
        return []

    def _check_void(self, ctx, args):
        order, f = self._order(args)
        if order is None:
            return f
        findings = []
        if order["customer_id"] != ctx.customer_id:
            findings.append(
                Finding(APPROVAL, "CUSTOMER_ORDER_MISMATCH", f"order {order['order_no']} belongs to another customer")
            )
        # A refund request is not a cancellation: void needs the Reader to have seen a cancellation of this order.
        findings += self._reader_check(ctx, "void", {"siparis_no": order["order_no"]})
        if self.store.order_refunded_total(order["order_no"]):
            findings.append(Finding(BLOCK, "VOID_AFTER_REFUND", "order already has refunds"))
        return findings

    def _check_refund(self, ctx, args):
        try:
            amount = parse_amount(args.get("amount"))
        except BadAmount as exc:
            return [Finding(BLOCK, "BAD_AMOUNT", str(exc))]
        order, f = self._order(args)
        if order is None:
            return f
        findings: list[Finding] = []
        order_no, rma_id = order["order_no"], args.get("rma_id")
        if rma_id is not None and not isinstance(rma_id, str):  # a list or object here used to crash the ledger query
            return [Finding(BLOCK, "RMA_UNKNOWN", f"{rma_id!r} is not a return record id")]
        if order["customer_id"] != ctx.customer_id:
            findings.append(
                Finding(
                    APPROVAL,
                    "CUSTOMER_ORDER_MISMATCH",
                    f"sender is {ctx.customer_id}, order {order_no} belongs to {order['customer_id']}",
                )
            )
        currency = str(args.get("currency") or order["currency"]).upper()
        if currency != order["currency"]:
            findings.append(
                Finding(
                    APPROVAL,
                    "CURRENCY_MISMATCH",
                    f"{currency} requested; the rail refunds in the order currency {order['currency']}",
                )
            )

        ent = self.store.entitlement(order_no, rma_id)
        if ent.unresolved:  # order-level: no RMA-id game gets around this
            findings.append(
                Finding(
                    BLOCK,
                    "REFUND_OUTCOME_UNKNOWN",
                    f"refund(s) {', '.join(ent.unresolved)} on {order_no} not reconciled",
                )
            )
        drift = self._rail_drift(order)
        if drift:
            findings.append(drift)

        rma = self.store.rma(order_no, rma_id)
        if rma_id is None:
            findings.append(Finding(APPROVAL, "RMA_MISSING", f"no return record cited for order {order_no}"))
        elif rma is None:
            findings.append(Finding(BLOCK, "RMA_UNKNOWN", f"{rma_id!r} is not a return record of order {order_no}"))
        elif rma["status"] == "refunded":
            findings.append(Finding(BLOCK, "RMA_ALREADY_REFUNDED", f"{rma_id} is already refunded"))
        elif rma["status"] != "open":
            findings.append(Finding(BLOCK, "RMA_NOT_OPEN", f"{rma_id} is {rma['status']}"))
        elif amount > ent.remaining:
            if ent.spent or ent.reserved:
                findings.append(
                    Finding(
                        BLOCK,
                        "CUMULATIVE_REFUND_EXCEEDS_RMA",
                        f"{amount} requested; {ent.spent} refunded and {ent.reserved} reserved "
                        f"of {ent.approved} approved; {max(ent.remaining, Decimal('0.00'))} left",
                    )
                )
            else:
                findings.append(
                    Finding(
                        APPROVAL, "RMA_AMOUNT_MISMATCH", f"{amount} requested, return record approves {ent.approved}"
                    )
                )

        findings += self._reader_check(
            ctx, "refund", {"tutar": amount, "siparis_no": order_no, "iade_kaydi_no": rma_id, "para_birimi": currency}
        )
        created = datetime.fromisoformat(order["created_at"].replace("Z", "+00:00"))
        window = timedelta(days=int(self.store.policy["window_days"]))
        if ctx.as_of > created + window:
            findings.append(Finding(APPROVAL, "OUTSIDE_REFUND_WINDOW", f"order is older than {window.days} days"))
        limit = parse_amount(self.store.policy["auto_refund_limit"])
        if amount > limit:
            findings.append(
                Finding(APPROVAL, "AUTO_REFUND_LIMIT_EXCEEDED", f"{amount} is above the {limit} auto-refund limit")
            )
        return findings

    def _rail_drift(self, order) -> Finding | None:
        """The rail knows of refunds this store does not (made elsewhere, or lost state) → stop and reconcile."""
        rail_total = self.rail.refunded_total(order["braintree_transaction_id"])
        if rail_total is None:
            return None
        local = self.store.order_refunded_total(order["order_no"])
        if rail_total > local:
            return Finding(
                BLOCK,
                "UNRECONCILED_RAIL_REFUNDS",
                f"rail shows {rail_total} refunded on {order['order_no']}, store knows {local}",
            )
        return None

    def _check_charge(self, ctx, args):
        try:
            amount = parse_amount(args.get("amount"))
            requested = self._items(args.get("items") or [], "qty")
        except BadAmount as exc:
            return [Finding(BLOCK, "BAD_AMOUNT", str(exc))]
        token = str(args.get("vaulted_payment_method_token", ""))
        if not self.store.owns_token(ctx.customer_id, token):
            return [Finding(BLOCK, "PAYMENT_METHOD_NOT_OWNED", "payment method does not belong to the sender")]
        status = self.store.charge_status(self._charge_request_id(ctx))
        if status in ("requested", "accepted"):
            return [Finding(BLOCK, "DUPLICATE_CHARGE", "this email already produced a charge")]
        if status == "unknown":
            return [Finding(BLOCK, "CHARGE_OUTCOME_UNKNOWN", "an earlier charge from this email has no known outcome")]
        currency = str(args.get("currency") or self.store.policy["currency"]).upper()
        if currency != self.store.policy["currency"]:
            return [Finding(BLOCK, "UNSUPPORTED_CURRENCY", f"store charges only in {self.store.policy['currency']}")]
        findings = self._reader_check(ctx, "charge", {"tutar": amount, "para_birimi": currency})
        try:
            authorized = self._items((ctx.reader or {}).get("kalemler") or [], "adet")
        except BadAmount as exc:
            return findings + [Finding(APPROVAL, "READER_INCOMPLETE", f"Reader items unreadable: {exc}")]
        if not authorized:
            return findings + [Finding(APPROVAL, "NO_AUTHORIZED_ITEMS", "the Reader passed no items for this charge")]
        if requested != authorized:
            findings.append(Finding(APPROVAL, "ITEMS_MISMATCH", f"call items {requested} ≠ Reader items {authorized}"))
        unknown = [s for s in authorized if s not in self.store.catalog]
        if unknown:
            return findings + [Finding(APPROVAL, "UNKNOWN_SKU", f"not in catalog: {', '.join(unknown)}")]
        expected = sum(
            (parse_amount(self.store.catalog[s]["unit_price"]) * q for s, q in authorized.items()), Decimal("0.00")
        )
        if amount != expected:
            findings.append(
                Finding(
                    APPROVAL,
                    "CHARGE_AMOUNT_MISMATCH",
                    f"{amount} requested, catalog price × Reader quantity is {expected}",
                )
            )
        # No store record says how many the customer ordered: the quantity comes from the e-mail, via the Reader.
        # A Reader that obeys hidden text agrees with the call on every field (qwen3, P7-01, 24 Oct), so the checks
        # above cannot be the basis. A human confirms the itemised total before any charge.
        basket = ", ".join(
            f"{q} × {s} @ {self.store.catalog[s]['unit_price']}"
            for s, q in sorted(requested.items())
            if s in self.store.catalog
        )
        findings.append(
            Finding(
                APPROVAL,
                "CHARGE_NEEDS_CONFIRMATION",
                f"no store record of the quantity; confirm {basket or 'the items'} = {amount} {currency}",
            )
        )
        return findings

    @staticmethod
    def _items(items, qty_key) -> dict[str, int]:
        if not isinstance(items, list):
            raise BadAmount(f"items must be a list, got {type(items).__name__}")
        out: dict[str, int] = {}
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get("sku"), str):
                raise BadAmount(f"bad item: {it!r}")
            qty = it.get(qty_key, it.get("adet" if qty_key == "qty" else "qty"))  # agents mix the two names
            out[it["sku"]] = out.get(it["sku"], 0) + parse_qty(qty)
        return out

    @staticmethod
    def _reader_check(ctx, request: str, call: dict) -> list[Finding]:
        """The Reader saw the email; the transaction agent did not. Missing or different intent → a human looks."""
        r = ctx.reader
        missing = [k for k in READER_REQUIRED[request] if not r or r.get(k) in (None, "", [])]
        if missing:
            return [Finding(APPROVAL, "READER_INCOMPLETE", f"Reader hand-off lacks {', '.join(missing)}")]
        diffs = []
        if r["istek"] != request:
            diffs.append(f"call is a {request}, Reader saw a {r['istek']} request")
        for key, value in call.items():
            theirs = r.get(key)
            if key == "iade_kaydi_no":
                # The email need not cite the return record; the agent finds it via lookup and the store
                # validates it. Only a *different* record from the one the Reader saw is a mismatch.
                if theirs and theirs != value:
                    diffs.append(f"return record {value} vs Reader {theirs}")
                continue
            if theirs in (None, ""):
                continue
            if key == "tutar":
                try:
                    theirs = parse_amount(theirs)
                except BadAmount:
                    diffs.append(f"Reader amount unreadable: {r[key]!r}")
                    continue
            if str(theirs).strip().upper() != str(value).strip().upper():
                diffs.append(f"{key} {value} vs Reader {r[key]}")
        return [Finding(APPROVAL, "READER_CALL_MISMATCH", "; ".join(diffs))] if diffs else []

    # -- execution -------------------------------------------------------------------------------
    @staticmethod
    def _charge_request_id(ctx) -> str:
        return f"{ctx.session_id}:charge"  # one charge per inbound email

    def _refund_state(self, tool, args):
        if tool != "refund" or args.get("order_no") not in self.store.orders:
            return None
        return self.store.entitlement(args["order_no"], args.get("rma_id")).state

    def _execute(self, ctx, tool, args, findings, approved: dict | None = None) -> Outcome:
        decision = APPROVAL if approved else PASS
        if tool == "lookup_transaction":
            return Outcome(decision, findings, "succeeded", data=order_view(self.store, self.rail, args["order_no"]))
        if tool == "void":
            order = self.store.orders[args["order_no"]]
            return self._call(decision, findings, lambda: self.rail.void(order["braintree_transaction_id"]))
        if tool == "charge":
            return self._execute_charge(ctx, args, findings, decision)
        return self._execute_refund(ctx, args, findings, decision, approved)

    @staticmethod
    def _call(decision, findings, fn) -> Outcome:
        try:
            res = fn()
        except Exception as exc:  # noqa: BLE001 - any rail failure means the outcome is unknown
            return Outcome(decision, findings + [Finding(BLOCK, "RAIL_ERROR", repr(exc))], "unknown")
        return Outcome(decision, findings, "succeeded" if res.ok else "failed", res)

    def _execute_charge(self, ctx, args, findings, decision) -> Outcome:
        amount = parse_amount(args["amount"])
        req = self._charge_request_id(ctx)
        with self.store.transaction():  # claim the request id atomically
            if self.store.charge_status(req) in ("requested", "accepted", "unknown"):
                ctx.blocked_attempts += 1
                return Outcome(BLOCK, findings + [Finding(BLOCK, "DUPLICATE_CHARGE", "claimed by a parallel call")])
            self.store.record_charge(req, ctx.customer_id, amount, "requested")
        out = self._call(
            decision, findings, lambda: self.rail.charge(args["vaulted_payment_method_token"], amount, req)
        )
        status = {"succeeded": "accepted", "failed": "failed", "unknown": "unknown"}[out.rail_state]
        self.store.record_charge(req, ctx.customer_id, amount, status, out.rail.id if out.rail else None)
        return out

    def _execute_refund(self, ctx, args, findings, decision, approved: dict | None) -> Outcome:
        amount = parse_amount(args["amount"])
        order = self.store.orders[args["order_no"]]
        rma_id = args.get("rma_id")
        reservation = f"res-{uuid.uuid4().hex[:12]}"
        with self.store.transaction():  # re-check and reserve atomically
            ent = self.store.entitlement(order["order_no"], rma_id)
            late = None
            if ent.unresolved:
                late = "a refund on this order became unresolved"
            elif approved is not None:
                if ent.state != approved["state"]:
                    late = "refund state changed after the human looked"
                elif amount > ent.remaining and not ({"RMA_AMOUNT_MISMATCH", "RMA_MISSING"} & approved["accepted"]):
                    late = "amount exceeds what is left and the human did not accept that"
            elif rma_id and amount > ent.remaining:
                late = "entitlement changed before execution"
            if late:
                ctx.blocked_attempts += 1
                return Outcome(BLOCK, findings + [Finding(BLOCK, "CONCURRENT_REFUND", late)])
            self.store.reserve(reservation, order["order_no"], rma_id, amount, ctx.session_id)
        out = self._call(decision, findings, lambda: self.rail.refund(order["braintree_transaction_id"], amount))
        if out.rail_state == "succeeded":
            self.store.settle_reservation(
                reservation, (out.rail and out.rail.id) or f"accepted-{reservation}", "accepted"
            )
        elif out.rail_state == "failed":
            self.store.release(reservation)
        else:  # unknown: keep it counted, block further refunds
            self.store.settle_reservation(reservation, f"unknown-{reservation}", "unknown")
        return out

    def _record(self, ctx, tool, args, out: Outcome, human_approved=False):
        self.log.append(
            {
                "session_id": ctx.session_id,
                "tool": tool,
                "args": args,
                "decision": out.decision,
                "findings": [f.__dict__ for f in out.findings],
                "rail_state": out.rail_state,
                "rail": out.rail.__dict__ if out.rail else None,
                "human_approved": human_approved,
            }
        )
