"""Gate invariants as property-based tests (hypothesis).

The example tests pin one scenario each. Here hypothesis drives the gate with arbitrary sequences of refund, charge,
void and lookup calls from several sessions and customers, plus manager approvals (some tampered with or too late),
clock jumps and a rail that sometimes fails or times out after moving money. After every step it checks:

- a BLOCKed or held call never reaches the rail, and nothing else reaches it more than once per call;
- an approval executes at most once, inside its 30 minutes, and only with the arguments it was issued for;
- per return record, the money that left (accepted, completed and unknown refunds) never exceeds the approved amount,
  unless a manager explicitly approved an RMA_AMOUNT_MISMATCH on it;
- every refund the rail executed is in the store's ledger, with the same amount: no money moves unrecorded;
- a call that executes without a human owns what it touches, and no charge executes without a human;
- one charge per e-mail reaches the rail, approvals included;
- amounts are exact Decimals with two places: no float drift, whatever the input.

Runtime is kept CI-friendly; set HYPOTHESIS_PROFILE=thorough for a long local run.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from counterfoil.gateway import APPROVAL, APPROVAL_TTL, BLOCK, PASS, Context, Gateway
from counterfoil.money import MAX_AMOUNT, BadAmount, parse_amount, parse_qty
from counterfoil.rail import FakeRail
from counterfoil.scenarios import load_records
from counterfoil.store import Store

settings.register_profile("ci", max_examples=60, stateful_step_count=25, deadline=None)
settings.register_profile(
    "thorough", max_examples=2000, stateful_step_count=60, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.register_profile("mutation", max_examples=60, stateful_step_count=25, deadline=None, derandomize=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

RECORDS = load_records()
ORDERS = {o["order_no"]: o for o in RECORDS["orders"]}
CUSTOMERS = sorted(c["customer_id"] for c in RECORDS["customers"])
TOKENS = sorted(m["token"] for c in RECORDS["customers"] for m in c.get("vaulted_payment_methods", []))
SKUS = sorted(c["sku"] for c in RECORDS["catalog"]) + ["GHOST"]
PRICE = {c["sku"]: Decimal(c["unit_price"]) for c in RECORDS["catalog"]}
RMAS = {
    (o["order_no"], r["rma_id"]): Decimal(r["approved_refund_amount"])
    for o in ORDERS.values()
    for r in o.get("returns", [])
}
AS_OF = datetime(2026, 10, 23, 12, tzinfo=UTC)
ALL_TOOLS = frozenset({"refund", "void", "charge", "lookup_transaction"})

cents = st.integers(min_value=1, max_value=40_000)
amount_text = cents.map(lambda c: f"{c // 100}.{c % 100:02d}")
odd_amounts = st.sampled_from(["30", "1e3", "30,00", "-5.00", "0", "0.001", "NaN", "", None, 30.0, True, "  25.00 "])
amounts = st.one_of(amount_text, amount_text, odd_amounts)
order_nos = st.sampled_from(sorted(ORDERS) + ["ST-9999"])


class FlakyRail(FakeRail):
    """FakeRail that can be told to raise once, before or after moving money (a timeout after the rail acted)."""

    def __init__(self, txns):
        super().__init__(txns)
        self.fail_next: str | None = None

    def _maybe(self, fn, *a):
        mode, self.fail_next = self.fail_next, None
        if mode == "before":
            raise TimeoutError("rail unreachable")
        res = fn(*a)
        if mode == "after":
            raise TimeoutError("rail timed out after acting")
        return res

    def refund(self, transaction_id, amount):
        return self._maybe(super().refund, transaction_id, amount)

    def charge(self, payment_method_token, amount, order_id):
        return self._maybe(super().charge, payment_method_token, amount, order_id)

    def void(self, transaction_id):
        return self._maybe(super().void, transaction_id)


class Clock:
    def __init__(self):
        self.now = AS_OF

    def __call__(self):
        return self.now


@dataclass
class Held:
    ctx: Context
    tool: str
    args: dict
    issued: datetime
    accepted: set = field(default_factory=set)


def reader_for(tool, args, customer) -> dict:
    """The Reader hand-off a faithful Reader would have produced for exactly this call."""
    items = [{"sku": i.get("sku"), "adet": i.get("qty")} for i in (args.get("items") or []) if isinstance(i, dict)]
    return {
        "musteri_email": customer,
        "istek": tool,
        "siparis_no": args.get("order_no"),
        "iade_kaydi_no": args.get("rma_id"),
        "tutar": args.get("amount"),
        "para_birimi": args.get("currency", "USD"),
        "kalemler": items,
        "not": "",
    }


class GateMachine(RuleBasedStateMachine):
    @initialize()
    def setup(self):
        self.store = Store(RECORDS)
        base = FakeRail.from_store(self.store)
        self.rail = FlakyRail(base.txns)
        self.clock = Clock()
        self.gw = Gateway(self.store, self.rail, clock=self.clock)
        # one e-mail per customer to start with; new_session adds more (other customers, no sender, read-only)
        self.sessions = [Context(f"s{n}", c, ALL_TOOLS, reader=None, as_of=AS_OF) for n, c in enumerate(CUSTOMERS)]
        self.held: dict[str, Held] = {}
        self.used: set[str] = set()  # approval ids that already executed
        self.over_approved: set[tuple] = set()  # (order, rma) where a manager accepted RMA_AMOUNT_MISMATCH
        self.charges_by_session: dict[str, int] = {}
        self.initial_ledger = {o: self._ledger_total(o) for o in ORDERS}

    # -- helpers -----------------------------------------------------------------------------------
    def _ledger_total(self, order_no) -> Decimal:
        return self.store.order_refunded_total(order_no)

    def _money_calls(self):
        return list(self.rail.money_calls())

    def _session(self, i) -> Context:
        return self.sessions[i % len(self.sessions)]

    def _note_rail(self, before, tool, args):
        """Check what reached the rail during one gate call and remember refunds for the ledger invariant."""
        new = self._money_calls()[before:]
        assert len(new) <= 1, f"one call reached the rail {len(new)} times: {new}"
        if not new:
            return None
        call = new[0]
        assert call[0] == tool
        order = ORDERS.get(str(args.get("order_no")))
        if tool == "refund":
            assert call[1] == order["braintree_transaction_id"] and call[2] == parse_amount(args["amount"])
        elif tool == "void":
            assert call[1] == order["braintree_transaction_id"]
        elif tool == "charge":
            assert call[1] == args["vaulted_payment_method_token"] and call[2] == parse_amount(args["amount"])
        return call

    def _after_execution(self, ctx, tool, args, out, human: Held | None, call):
        if call is None:
            return
        if tool == "charge":
            self.charges_by_session[ctx.session_id] = self.charges_by_session.get(ctx.session_id, 0) + 1
            assert self.charges_by_session[ctx.session_id] == 1, "a second charge for one e-mail reached the rail"
            assert self.store.owns_token(ctx.customer_id, args["vaulted_payment_method_token"])
        if human is None and tool in ("refund", "void"):
            assert ORDERS[args["order_no"]]["customer_id"] == ctx.customer_id, "money moved on another customer's order"
        if tool == "charge":
            # no store record says how many the customer ordered, so every charge waits for a human
            assert human is not None, "a charge reached the rail without confirmation"

    # -- rules ---------------------------------------------------------------------------------------
    @rule(
        customer=st.sampled_from(CUSTOMERS + [None]),
        tools=st.sampled_from([ALL_TOOLS, frozenset({"lookup_transaction"})]),
    )
    def new_session(self, customer, tools):
        ctx = Context(f"s{len(self.sessions)}", customer, tools, reader=None, as_of=AS_OF)
        self.sessions.append(ctx)

    @rule(
        i=st.integers(0, 50),
        order_no=order_nos,
        rma=st.sampled_from(["own", None, "RMA-1042", "invented"]),
        amount=amounts,
        currency=st.sampled_from(["USD", "usd ", "EUR", None]),
        faithful_reader=st.booleans(),
    )
    def refund(self, i, order_no, rma, amount, currency, faithful_reader):
        ctx = self._session(i)
        order = ORDERS.get(order_no)
        if rma == "own":
            rma = order["returns"][0]["rma_id"] if order and order.get("returns") else None
        args = {"order_no": order_no, "rma_id": rma, "amount": amount}
        if currency is not None:
            args["currency"] = currency
        self._call(ctx, "refund", args, faithful_reader)

    @rule(
        i=st.integers(0, 50),
        token=st.sampled_from(TOKENS + ["tok-stolen"]),
        items=st.lists(st.fixed_dictionaries({"sku": st.sampled_from(SKUS), "qty": st.integers(1, 6)}), max_size=3),
        priced=st.booleans(),
        amount=amounts,
        faithful_reader=st.booleans(),
    )
    def charge(self, i, token, items, priced, amount, faithful_reader):
        ctx = self._session(i)
        if priced and all(it["sku"] in PRICE for it in items) and items:
            total = sum((PRICE[it["sku"]] * it["qty"] for it in items), Decimal("0.00"))
            amount = str(total) if total <= MAX_AMOUNT else amount
        args = {"vaulted_payment_method_token": token, "items": items, "amount": amount, "currency": "USD"}
        self._call(ctx, "charge", args, faithful_reader)

    @rule(i=st.integers(0, 50), data=st.data(), split=st.booleans())
    def genuine_refund(self, i, data, split):
        """A customer refunding their own open return record, the Reader agreeing: the path that should PASS."""
        ctx = self._session(i)
        own = [(o, r) for (o, r) in RMAS if ORDERS[o]["customer_id"] == ctx.customer_id]
        if not own:
            return
        order_no, rma_id = data.draw(st.sampled_from(own))
        top = int(RMAS[(order_no, rma_id)] * 100) // (2 if split else 1)
        c = data.draw(st.integers(1, max(top, 1)))
        args = {"order_no": order_no, "rma_id": rma_id, "amount": f"{c // 100}.{c % 100:02d}", "currency": "USD"}
        self._call(ctx, "refund", args, faithful_reader=True)

    @rule(
        i=st.integers(0, 50),
        items=st.lists(
            st.fixed_dictionaries({"sku": st.sampled_from(sorted(PRICE)), "qty": st.integers(1, 4)}),
            min_size=1,
            max_size=3,
        ),
        inflate=st.sampled_from([0, 0, 1, 5]),
    )
    def genuine_reorder(self, i, items, inflate):
        """A reorder on the sender's own saved method at catalog price; sometimes the call inflates one quantity
        the Reader did not see (the P7 shape)."""
        ctx = self._session(i)
        tokens = [
            m["token"]
            for c in RECORDS["customers"]
            if c["customer_id"] == ctx.customer_id
            for m in c["vaulted_payment_methods"]
        ]
        if not tokens:
            return
        ctx.reader = reader_for("charge", {"items": items, "currency": "USD"}, ctx.customer_id)
        called = [dict(it) for it in items]
        called[0]["qty"] += inflate
        total = sum((PRICE[it["sku"]] * it["qty"] for it in called), Decimal("0.00"))
        ctx.reader["tutar"] = str(sum((PRICE[it["sku"]] * it["qty"] for it in items), Decimal("0.00")))
        args = {"vaulted_payment_method_token": tokens[0], "items": called, "amount": str(total), "currency": "USD"}
        self._call(ctx, "charge", args, faithful_reader=False)

    @rule(i=st.integers(0, 50), order_no=order_nos, faithful_reader=st.booleans())
    def void(self, i, order_no, faithful_reader):
        self._call(self._session(i), "void", {"order_no": order_no}, faithful_reader)

    @rule(i=st.integers(0, 50), order_no=order_nos)
    def lookup(self, i, order_no):
        ctx = self._session(i)
        before = len(self._money_calls())
        out = self.gw.handle(ctx, "lookup_transaction", {"order_no": order_no})
        assert len(self._money_calls()) == before
        if out.data is not None:
            assert ORDERS[order_no]["customer_id"] == ctx.customer_id, "another customer's order was read"

    @staticmethod
    def _well_formed(out):
        assert out.decision in (PASS, APPROVAL, BLOCK)
        for f in out.findings:
            assert f.severity in (APPROVAL, BLOCK) and f.code.isupper() and f.code.replace("_", "").isalpha()
            assert isinstance(f.detail, str) and f.detail, f"{f.code} has no explanation"

    def _call(self, ctx, tool, args, faithful_reader):
        if faithful_reader:
            ctx.reader = reader_for(tool, args, ctx.customer_id)
        before = len(self._money_calls())
        out = self.gw.handle(ctx, tool, dict(args))
        self._well_formed(out)
        call = self._note_rail(before, tool, args)
        if out.decision == BLOCK or out.decision == APPROVAL:
            assert call is None, f"{out.decision} call reached the rail: {out.summary()}"
        if out.decision == APPROVAL:
            entry = self.gw.pending[out.approval_id]
            self.held[out.approval_id] = Held(ctx, tool, dict(args), self.clock(), set(entry["accepted"]))
        if out.decision == PASS:
            self._after_execution(ctx, tool, args, out, None, call)

    @precondition(lambda self: self.held)
    @rule(data=st.data(), tamper=st.booleans())
    def approve(self, data, tamper):
        approval_id = data.draw(st.sampled_from(list(self.held)))  # insertion order: ids are random uuids
        h = self.held[approval_id]
        if tamper and approval_id in self.gw.pending:
            self.gw.pending[approval_id]["args"]["amount"] = "1.00" if h.args.get("amount") != "1.00" else "2.00"
        before = len(self._money_calls())
        out = self.gw.approve(approval_id)
        self._well_formed(out)
        call = self._note_rail(before, h.tool, h.args)
        if call is not None:
            assert approval_id not in self.used, "an approval executed twice"
            assert not tamper, "a tampered approval executed"
            assert self.clock() <= h.issued + APPROVAL_TTL, "an expired approval executed"
            self.used.add(approval_id)
        if out.decision == BLOCK:
            assert call is None
        else:
            self.used.add(approval_id)
            if h.tool == "refund" and "RMA_AMOUNT_MISMATCH" in h.accepted:
                self.over_approved.add((h.args["order_no"], h.args.get("rma_id")))
            self._after_execution(h.ctx, h.tool, h.args, out, h, call)

    @precondition(lambda self: self.held)
    @rule(data=st.data())
    def reject(self, data):
        approval_id = data.draw(st.sampled_from(list(self.held)))  # insertion order: ids are random uuids
        self.gw.reject(approval_id)

    @rule(minutes=st.sampled_from([1, 10, 29, 31, 120]))
    def time_passes(self, minutes):
        self.clock.now += timedelta(minutes=minutes)

    @rule(mode=st.sampled_from(["before", "after"]))
    def rail_will_fail(self, mode):
        self.rail.fail_next = mode

    # -- invariants ----------------------------------------------------------------------------------
    @invariant()
    def refunds_per_rma_stay_within_the_approved_amount(self):
        if not hasattr(self, "store"):
            return
        for (order_no, rma_id), approved in RMAS.items():
            if (order_no, rma_id) in self.over_approved:
                continue
            out = self.store.sql(
                "SELECT amount FROM refunds WHERE order_no=? AND rma_id=? AND status IN "
                "('accepted','completed','unknown','pending')",
                (order_no, rma_id),
            )
            total = sum((Decimal(a) for (a,) in out), Decimal("0.00"))
            fixture_pending = sum(
                (Decimal(r["amount"]) for r in ORDERS[order_no].get("refunds", []) if r["status"] == "pending"),
                Decimal("0.00"),
            )
            assert total - fixture_pending <= approved, f"{rma_id}: {total} out against {approved} approved"

    @invariant()
    def every_rail_refund_is_in_the_ledger(self):
        if not hasattr(self, "store"):
            return
        for order_no in ORDERS:
            on_rail = self.rail.txns[ORDERS[order_no]["braintree_transaction_id"]].refunded
            start = sum(
                (Decimal(r["amount"]) for r in ORDERS[order_no].get("refunds", []) if r["status"] == "completed"),
                Decimal("0.00"),
            )
            moved = on_rail - start
            recorded = self._ledger_total(order_no) - self.initial_ledger[order_no]
            # unknown rows may be refunds the rail never saw (raised before acting), so ledger ≥ rail, never <
            assert recorded >= moved, f"{order_no}: rail moved {moved}, ledger recorded {recorded}"

    @invariant()
    def amounts_in_the_ledger_are_exact_cents(self):
        if not hasattr(self, "store"):
            return
        for (a,) in self.store.sql("SELECT amount FROM refunds UNION ALL SELECT amount FROM charges"):
            assert Decimal(a) == Decimal(a).quantize(Decimal("0.01")) and Decimal(a).as_tuple().exponent == -2

    def teardown(self):
        if hasattr(self, "store"):
            self.store.db.close()


TestGateStateMachine = GateMachine.TestCase


# -- money parsing ---------------------------------------------------------------------------------------
@given(cents)
def test_amount_text_parses_to_the_exact_cents(c):
    text = f"{c // 100}.{c % 100:02d}"
    assert parse_amount(text) == Decimal(c) / 100
    assert parse_amount(text).as_tuple().exponent == -2
    assert parse_amount(str(parse_amount(text))) == parse_amount(text)


@given(st.lists(cents, min_size=1, max_size=50))
def test_sums_of_parsed_amounts_do_not_drift(cs):
    total = sum((parse_amount(f"{c // 100}.{c % 100:02d}") for c in cs), Decimal("0.00"))
    assert total == Decimal(sum(cs)) / 100  # 0.1 + 0.2 is 0.30 here, not 0.30000000000000004


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_floats_are_never_money(x):
    try:
        parse_amount(x)
    except BadAmount:
        return
    raise AssertionError(f"float {x!r} was accepted")


@given(st.one_of(st.text(max_size=20), st.integers(), st.decimals(), st.none(), st.booleans(), st.binary(max_size=8)))
def test_parse_amount_accepts_only_positive_two_place_values_below_the_maximum(value):
    try:
        amount = parse_amount(value)
    except BadAmount:
        return
    assert isinstance(amount, Decimal) and amount.is_finite()
    assert Decimal("0.01") <= amount <= MAX_AMOUNT
    assert amount == amount.quantize(Decimal("0.01")) and amount.as_tuple().exponent == -2


@given(st.one_of(st.integers(), st.floats(), st.text(max_size=4), st.booleans(), st.none()))
def test_quantities_are_small_positive_ints(value):
    try:
        q = parse_qty(value)
    except BadAmount:
        return
    assert type(q) is int and 1 <= q <= 1000


# -- the gate never crashes on what an agent may send ---------------------------------------------------
json_values = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.text(max_size=12)),
    lambda inner: st.one_of(st.lists(inner, max_size=3), st.dictionaries(st.text(max_size=8), inner, max_size=3)),
    max_leaves=8,
)
arg_keys = st.sampled_from(
    ["order_no", "rma_id", "amount", "currency", "braintree_transaction_id", "vaulted_payment_method_token", "items"]
)


@settings(max_examples=150, deadline=None)
@given(
    tool=st.sampled_from(["refund", "charge", "void", "lookup_transaction", "export"]),
    args=st.dictionaries(arg_keys, st.one_of(json_values, order_nos, amounts), max_size=7),
    reader=st.one_of(
        st.none(), st.dictionaries(st.sampled_from(["istek", "tutar", "siparis_no", "kalemler"]), json_values)
    ),
)
def test_arbitrary_tool_arguments_get_a_decision_not_a_crash(tool, args, reader):
    store = Store(RECORDS)
    rail = FakeRail.from_store(store)
    gw = Gateway(store, rail)
    ctx = Context("fuzz", "CUS-01", ALL_TOOLS, reader=reader, as_of=AS_OF)
    try:
        out = gw.handle(ctx, tool, args)
        assert out.decision in (PASS, APPROVAL, BLOCK)
        if out.decision != PASS:
            assert not rail.money_calls()
    finally:
        store.db.close()


VALID_CALLS = {
    "refund": {"order_no": "ST-1042", "rma_id": "RMA-1042", "amount": "30.00", "currency": "USD"},
    "charge": {
        "vaulted_payment_method_token": "fixture-vault-01",
        "items": [{"sku": "CUP", "qty": 1}],
        "amount": "25.00",
        "currency": "USD",
    },
    "void": {"order_no": "ST-1058"},
    "lookup_transaction": {"order_no": "ST-1042"},
}


@settings(max_examples=300, deadline=None)
@given(tool=st.sampled_from(sorted(VALID_CALLS)), data=st.data(), value=json_values)
def test_one_malformed_argument_in_an_otherwise_valid_call_is_refused_cleanly(tool, data, value):
    """Start from a call that would PASS and break one argument: the gate must still answer, never raise, and the
    rail must only see the call if the broken value happens to mean the same thing."""
    args = dict(VALID_CALLS[tool])
    key = data.draw(st.sampled_from(sorted(args) + ["braintree_transaction_id"]))
    args[key] = value
    store = Store(RECORDS)
    rail = FakeRail.from_store(store)
    gw = Gateway(store, rail)
    ctx = Context("fuzz", "CUS-01", ALL_TOOLS, reader=reader_for(tool, VALID_CALLS[tool], "CUS-01"), as_of=AS_OF)
    try:
        out = gw.handle(ctx, tool, args)
        assert out.decision in (PASS, APPROVAL, BLOCK)
        if out.decision != PASS:
            assert not rail.money_calls()
    finally:
        store.db.close()
