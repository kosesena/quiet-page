"""Every finding code the gate can emit, with its severity and the smallest call that triggers it, plus the
boundaries and execution paths that mutation testing (docs/quality.md) showed the other tests did not pin down.
Finding codes are an interface: the agent sees them, the dashboard groups by them, the manager reads them."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from counterfoil.gateway import APPROVAL, APPROVAL_TTL, BLOCK, PASS, Context, Finding, Gateway, Outcome, _decide, utcnow
from counterfoil.rail import FakeRail
from counterfoil.scenarios import load_records
from counterfoil.store import Store

AS_OF = datetime(2026, 10, 23, 12, tzinfo=UTC)
ALL = frozenset({"refund", "void", "charge", "lookup_transaction"})
REFUND = {"order_no": "ST-1042", "rma_id": "RMA-1042", "amount": "30.00", "currency": "USD"}
CHARGE = {
    "vaulted_payment_method_token": "fixture-vault-01",
    "items": [{"sku": "CUP", "qty": 1}],
    "amount": "25.00",
    "currency": "USD",
}


class Clock:
    def __init__(self):
        self.now = AS_OF

    def __call__(self):
        return self.now


def reader(tool, args):
    return {
        "istek": tool,
        "siparis_no": args.get("order_no"),
        "iade_kaydi_no": args.get("rma_id"),
        "tutar": args.get("amount"),
        "para_birimi": args.get("currency", "USD"),
        "kalemler": [{"sku": i["sku"], "adet": i["qty"]} for i in args.get("items", [])],
        "not": "",
    }


def gate(records=None):
    store = Store(records or load_records())
    rail = FakeRail.from_store(store)
    clock = Clock()
    return Gateway(store, rail, clock=clock), rail, clock


def session(customer="CUS-01", tool=None, args=None, tools=ALL, sid="s1", **reader_overrides):
    r = reader(tool, args) if tool else None
    if r is not None:
        r.update(reader_overrides)
    return Context(sid, customer, tools, reader=r, as_of=AS_OF)


def codes(out: Outcome) -> dict[str, str]:
    return {f.code: f.severity for f in out.findings}


# -- every code, its severity -------------------------------------------------------------------------
def _records_with(**changes):
    rec = load_records()
    for order in rec["orders"]:
        for rma in order.get("returns", []):
            if rma["rma_id"] in changes:
                rma.update(changes[rma["rma_id"]])
    return rec


CASES = [
    # (id, customer, tool, args, reader overrides, expected code, severity)
    ("tool not in list", "CUS-01", "export", {}, {}, "TOOL_NOT_ALLOWED", BLOCK),
    ("no sender", None, "refund", REFUND, {}, "NO_CONTEXT", BLOCK),
    ("unknown order", "CUS-01", "refund", dict(REFUND, order_no="ST-9999"), {}, "UNKNOWN_ORDER", BLOCK),
    (
        "transaction of another order",
        "CUS-01",
        "refund",
        dict(REFUND, braintree_transaction_id="fixture-txn-002"),
        {},
        "TRANSACTION_ORDER_MISMATCH",
        BLOCK,
    ),
    ("bad refund amount", "CUS-01", "refund", dict(REFUND, amount="30,00"), {}, "BAD_AMOUNT", BLOCK),
    ("rma id is a list", "CUS-01", "refund", dict(REFUND, rma_id=["RMA-1042"]), {}, "RMA_UNKNOWN", BLOCK),
    ("rma of another order", "CUS-01", "refund", dict(REFUND, rma_id="RMA-1043"), {}, "RMA_UNKNOWN", BLOCK),
    ("no rma", "CUS-01", "refund", dict(REFUND, rma_id=None), {}, "RMA_MISSING", APPROVAL),
    ("other customer's order", "CUS-02", "refund", REFUND, {}, "CUSTOMER_ORDER_MISMATCH", APPROVAL),
    ("currency", "CUS-01", "refund", dict(REFUND, currency="EUR"), {}, "CURRENCY_MISMATCH", APPROVAL),
    ("over the rma", "CUS-01", "refund", dict(REFUND, amount="30.01"), {}, "RMA_AMOUNT_MISMATCH", APPROVAL),
    (
        "reader saw another order",
        "CUS-01",
        "refund",
        REFUND,
        {"siparis_no": "ST-1043"},
        "READER_CALL_MISMATCH",
        APPROVAL,
    ),
    (
        "reader saw another currency",
        "CUS-01",
        "refund",
        REFUND,
        {"para_birimi": "EUR"},
        "READER_CALL_MISMATCH",
        APPROVAL,
    ),
    (
        "reader saw another rma",
        "CUS-01",
        "refund",
        REFUND,
        {"iade_kaydi_no": "RMA-9"},
        "READER_CALL_MISMATCH",
        APPROVAL,
    ),
    ("reader saw a charge", "CUS-01", "refund", REFUND, {"istek": "charge"}, "READER_CALL_MISMATCH", APPROVAL),
    ("reader amount unreadable", "CUS-01", "refund", REFUND, {"tutar": "thirty"}, "READER_CALL_MISMATCH", APPROVAL),
    ("reader saw nothing", "CUS-01", "refund", REFUND, {"tutar": None}, "READER_INCOMPLETE", APPROVAL),
    ("reader amount blank", "CUS-01", "refund", REFUND, {"tutar": ""}, "READER_INCOMPLETE", APPROVAL),
    (
        "void of another customer's order",
        "CUS-02",
        "void",
        {"order_no": "ST-1058"},
        {},
        "CUSTOMER_ORDER_MISMATCH",
        APPROVAL,
    ),
    (
        "void, reader saw another order",
        "CUS-01",
        "void",
        {"order_no": "ST-1058"},
        {"siparis_no": "ST-1042"},
        "READER_CALL_MISMATCH",
        APPROVAL,
    ),
    (
        "lookup of another customer's order",
        "CUS-01",
        "lookup_transaction",
        {"order_no": "ST-1043"},
        {},
        "SCOPE_NOT_ALLOWED",
        BLOCK,
    ),
    ("bad charge amount", "CUS-01", "charge", dict(CHARGE, amount=25.0), {}, "BAD_AMOUNT", BLOCK),
    (
        "bad charge quantity",
        "CUS-01",
        "charge",
        dict(CHARGE, items=[{"sku": "CUP", "qty": "1"}]),
        {},
        "BAD_AMOUNT",
        BLOCK,
    ),
    (
        "someone else's method",
        "CUS-01",
        "charge",
        dict(CHARGE, vaulted_payment_method_token="fixture-vault-02"),
        {},
        "PAYMENT_METHOD_NOT_OWNED",
        BLOCK,
    ),
    ("charge in EUR", "CUS-01", "charge", dict(CHARGE, currency="EUR"), {}, "UNSUPPORTED_CURRENCY", BLOCK),
    ("charge above the reader", "CUS-01", "charge", CHARGE, {"tutar": "20.00"}, "READER_CALL_MISMATCH", APPROVAL),
    (
        "reader saw another currency for a charge",
        "CUS-01",
        "charge",
        CHARGE,
        {"para_birimi": "EUR"},
        "READER_CALL_MISMATCH",
        APPROVAL,
    ),
    (
        "reader items unreadable",
        "CUS-01",
        "charge",
        CHARGE,
        {"kalemler": [{"sku": "CUP", "adet": 1.5}]},
        "READER_INCOMPLETE",
        APPROVAL,
    ),
    ("reader items not a list", "CUS-01", "charge", CHARGE, {"kalemler": "one cup"}, "READER_INCOMPLETE", APPROVAL),
    ("reader passed no items", "CUS-01", "charge", dict(CHARGE, items=[]), {}, "READER_INCOMPLETE", APPROVAL),
    (
        "call items differ",
        "CUS-01",
        "charge",
        CHARGE,
        {"kalemler": [{"sku": "BAG", "adet": 1}]},
        "ITEMS_MISMATCH",
        APPROVAL,
    ),
    ("unknown sku", "CUS-01", "charge", dict(CHARGE, items=[{"sku": "GHOST", "qty": 1}]), {}, "UNKNOWN_SKU", APPROVAL),
    (
        "price is not catalog x qty",
        "CUS-01",
        "charge",
        dict(CHARGE, amount="24.00"),
        {"tutar": "24.00"},
        "CHARGE_AMOUNT_MISMATCH",
        APPROVAL,
    ),
]


@pytest.mark.parametrize(
    ("customer", "tool", "args", "overrides", "code", "severity"), [c[1:] for c in CASES], ids=[c[0] for c in CASES]
)
def test_each_finding_has_its_code_and_severity(customer, tool, args, overrides, code, severity):
    gw, rail, _ = gate()
    tools = ALL | {"export"}
    ctx = session(customer, tool if tool in ALL else None, args, tools=tools, **overrides)
    out = gw.handle(ctx, tool, dict(args))
    assert codes(out).get(code) == severity, out.summary()
    assert out.decision == (BLOCK if BLOCK in codes(out).values() else APPROVAL)
    assert not rail.money_calls()
    assert all(isinstance(f.detail, str) and f.detail for f in out.findings), "every finding explains itself"


def test_allowed_tool_without_a_gateway_rule_is_refused():
    gw, rail, _ = gate()
    out = gw.handle(session(tools=ALL | {"export"}), "export", {})
    assert codes(out) == {"TOOL_NOT_ALLOWED": BLOCK} and "no gateway rule" in out.findings[0].detail


def test_rma_not_open_blocks():
    gw, rail, _ = gate(_records_with(**{"RMA-1042": {"status": "rejected"}}))
    out = gw.handle(session("CUS-01", "refund", REFUND), "refund", dict(REFUND))
    assert codes(out)["RMA_NOT_OPEN"] == BLOCK and "rejected" in out.findings[0].detail
    assert not rail.money_calls()


def test_void_after_a_refund_blocks():
    gw, rail, _ = gate()
    gw.store.db.execute("INSERT INTO refunds VALUES ('rf-x','ST-1058','RMA-1058','5.00','accepted')")
    out = gw.handle(session("CUS-01", "void", {"order_no": "ST-1058"}), "void", {"order_no": "ST-1058"})
    assert codes(out)["VOID_AFTER_REFUND"] == BLOCK and not rail.money_calls()


# -- execution paths ---------------------------------------------------------------------------------
def test_a_matching_void_executes_on_the_order_transaction():
    gw, rail, _ = gate()
    out = gw.handle(session("CUS-01", "void", {"order_no": "ST-1058"}), "void", {"order_no": "ST-1058"})
    assert out.decision == PASS and out.executed
    assert rail.money_calls() == [("void", "fixture-txn-011")] and rail.txns["fixture-txn-011"].status == "voided"


def test_lookup_returns_the_order_view():
    gw, rail, _ = gate()
    out = gw.handle(session(), "lookup_transaction", {"order_no": "ST-1042"})
    assert out.decision == PASS and out.data and out.data["order_no"] == "ST-1042"


def confirmed_charge(gw, ctx, args):
    """Every charge is held for the customer's confirmation of the itemised total; confirm it."""
    held = gw.handle(ctx, "charge", dict(args))
    assert codes(held) == {"CHARGE_NEEDS_CONFIRMATION": APPROVAL}, held.summary()
    return gw.approve(held.approval_id)


def test_a_charge_is_recorded_against_the_email_with_the_rail_id():
    gw, rail, _ = gate()
    out = confirmed_charge(gw, session("CUS-01", "charge", CHARGE), CHARGE)
    assert out.decision == APPROVAL and out.executed
    assert rail.money_calls() == [("charge", "fixture-vault-01", Decimal("25.00"), "s1:charge")]
    assert gw.store.sql("SELECT * FROM charges") == [("s1:charge", "CUS-01", "25.00", "accepted", out.rail.id)]


def test_a_second_charge_from_one_email_is_refused_by_the_check_not_only_by_the_claim():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "charge", CHARGE)
    assert confirmed_charge(gw, ctx, CHARGE).executed
    out = gw.handle(ctx, "charge", dict(CHARGE))
    assert codes(out) == {"DUPLICATE_CHARGE": BLOCK} and "already produced" in out.findings[0].detail
    assert len(rail.money_calls()) == 1


@pytest.mark.parametrize("status", ["requested", "accepted"])
def test_a_charge_in_flight_or_done_counts_as_the_email_s_charge(status):
    gw, rail, _ = gate()
    gw.store.record_charge("s1:charge", "CUS-01", Decimal("25.00"), status)
    out = gw.handle(session("CUS-01", "charge", CHARGE), "charge", dict(CHARGE))
    assert codes(out) == {"DUPLICATE_CHARGE": BLOCK} and not rail.money_calls()
    assert "already produced" in out.findings[0].detail  # caught by the check, not only by the claim


def test_a_charge_with_unknown_outcome_blocks_the_next_one():
    gw, rail, _ = gate()
    gw.store.record_charge("s1:charge", "CUS-01", Decimal("25.00"), "unknown")
    out = gw.handle(session("CUS-01", "charge", CHARGE), "charge", dict(CHARGE))
    assert codes(out) == {"CHARGE_OUTCOME_UNKNOWN": BLOCK} and not rail.money_calls() and out.findings[0].detail


@pytest.mark.parametrize("status", ["requested", "accepted", "unknown"])
def test_the_charge_claim_refuses_a_parallel_call_that_passed_the_check(status):
    gw, rail, _ = gate()
    ctx = session("CUS-01", "charge", CHARGE)
    ctx.blocked_attempts = 1
    gw.store.record_charge("s1:charge", "CUS-01", Decimal("25.00"), status)  # the other call claimed it first
    out = gw._execute_charge(ctx, dict(CHARGE), [], PASS)
    assert out.decision == BLOCK and codes(out) == {"DUPLICATE_CHARGE": BLOCK} and "parallel" in out.findings[0].detail
    assert ctx.blocked_attempts == 2 and not rail.money_calls()


def test_the_charge_is_claimed_before_the_rail_is_called():
    """If the process dies while the rail is working, the e-mail's charge is already on record."""
    gw, rail, _ = gate()
    seen = []
    real = rail.charge

    def charge(*a):
        seen.append(gw.store.sql("SELECT amount, status FROM charges WHERE request_id='s1:charge'"))
        return real(*a)

    rail.charge = charge
    assert confirmed_charge(gw, session("CUS-01", "charge", CHARGE), CHARGE).executed
    assert seen == [[("25.00", "requested")]]


def test_a_failed_rail_refund_leaves_the_order_retryable():
    gw, rail, _ = gate()
    rail.txns["fixture-txn-001"].status = "submitted_for_settlement"
    ctx = session("CUS-01", "refund", REFUND)
    assert gw.handle(ctx, "refund", dict(REFUND)).rail_state == "failed"
    rail.txns["fixture-txn-001"].status = "settled"
    assert gw.store.entitlement("ST-1042", "RMA-1042").unresolved == ()
    assert gw.handle(ctx, "refund", dict(REFUND)).executed


def test_a_rail_exception_is_reported_as_rail_error_and_unknown():
    gw, rail, _ = gate()

    def boom(*a):
        raise TimeoutError("no answer")

    rail.refund = boom
    out = gw.handle(session("CUS-01", "refund", REFUND), "refund", dict(REFUND))
    assert out.decision == PASS and out.rail_state == "unknown" and codes(out) == {"RAIL_ERROR": BLOCK}
    assert "TimeoutError" in out.findings[0].detail


def test_execution_refuses_when_a_refund_on_the_order_became_unresolved_meanwhile():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", REFUND)
    gw.store.db.execute("INSERT INTO refunds VALUES ('rf-other','ST-1042',NULL,'5.00','unknown')")  # after the check
    out = gw._execute_refund(ctx, dict(REFUND), [], PASS, None)
    assert codes(out) == {"CONCURRENT_REFUND": BLOCK} and "unresolved" in out.findings[0].detail
    assert ctx.blocked_attempts == 1 and not rail.money_calls()


def test_execution_refuses_when_the_entitlement_shrank_meanwhile():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", REFUND)
    ctx.blocked_attempts = 1
    gw.store.reserve("res-other", "ST-1042", "RMA-1042", Decimal("10.00"), "s2")
    out = gw._execute_refund(ctx, dict(REFUND), [], PASS, None)
    assert codes(out) == {"CONCURRENT_REFUND": BLOCK} and ctx.blocked_attempts == 2 and not rail.money_calls()


@pytest.mark.parametrize(("accepted", "executes"), [({"CURRENCY_MISMATCH"}, False), ({"RMA_AMOUNT_MISMATCH"}, True)])
def test_execution_of_an_approval_rechecks_the_amount_against_what_the_human_accepted(accepted, executes):
    """Defence in depth: approve() re-runs the checks first, so this layer only matters if the records changed
    under the approval (say the return record's amount was lowered). It is exercised directly."""
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", REFUND)
    ent = gw.store.entitlement("ST-1042", "RMA-1042")
    approved = {"state": ent.state, "accepted": accepted}
    out = gw._execute_refund(ctx, dict(REFUND, amount="40.00"), [], APPROVAL, approved)
    assert out.executed is executes
    if not executes:
        assert codes(out) == {"CONCURRENT_REFUND": BLOCK} and "did not accept" in out.findings[0].detail


# -- approvals -----------------------------------------------------------------------------------------
def _held_refund(gw, args=None, **reader_overrides):
    args = dict(args or REFUND)
    ctx = session("CUS-01", "refund", args, **reader_overrides)
    held = gw.handle(ctx, "refund", dict(args, currency="usd "))  # held for the unstripped currency text
    assert held.decision == APPROVAL, held.summary()
    return ctx, held


def test_an_approved_call_executes_as_approval_and_is_logged_as_human_approved():
    gw, rail, _ = gate()
    ctx, held = _held_refund(gw)
    out = gw.approve(held.approval_id)
    assert out.decision == APPROVAL and out.executed
    first, second = gw.log
    assert (first["tool"], first["decision"], first["human_approved"]) == ("refund", APPROVAL, False)
    assert first["args"]["currency"] == "usd " and first["rail"] is None
    assert (second["tool"], second["decision"], second["human_approved"]) == ("refund", APPROVAL, True)
    assert second["args"]["amount"] == "30.00" and second["session_id"] == "s1"
    assert second["rail"]["ok"] is True and "CURRENCY_MISMATCH" in {f["code"] for f in second["findings"]}


def test_approval_is_valid_up_to_and_including_its_last_second():
    gw, rail, clock = gate()
    _, held = _held_refund(gw)
    clock.now += APPROVAL_TTL
    assert gw.approve(held.approval_id).executed


def test_approval_one_second_late_is_refused():
    gw, rail, clock = gate()
    _, held = _held_refund(gw)
    clock.now += APPROVAL_TTL + timedelta(seconds=1)
    out = gw.approve(held.approval_id)
    assert out.decision == BLOCK and codes(out) == {"APPROVAL_EXPIRED": BLOCK} and not rail.money_calls()


@pytest.mark.parametrize("how", ["unknown", "tampered", "stale"])
def test_refused_approvals_say_why(how):
    gw, rail, _ = gate()
    ctx, held = _held_refund(gw)
    if how == "unknown":
        out = gw.approve("nope")
        expected = "APPROVAL_UNKNOWN"
    elif how == "tampered":
        gw.pending[held.approval_id]["args"]["amount"] = "29.00"
        out = gw.approve(held.approval_id)
        expected = "APPROVAL_TAMPERED"
    else:
        ctx.blocked_attempts = 1
        out = gw.approve(held.approval_id)
        expected = "APPROVAL_STALE"
    assert out.decision == BLOCK and codes(out)[expected] == BLOCK and out.findings[-1].detail
    assert not rail.money_calls()


def test_approval_after_an_earlier_partial_refund_executes():
    """The refund state the human saw includes what was already refunded on that return record."""
    gw, rail, _ = gate()
    first = dict(REFUND, amount="10.00")
    assert gw.handle(session("CUS-01", "refund", first), "refund", dict(first)).executed
    _, held = _held_refund(gw, dict(REFUND, amount="20.00"))
    assert gw.approve(held.approval_id).executed


def test_an_approved_charge_executes_as_a_charge():
    gw, rail, _ = gate()
    call = dict(CHARGE, items=[{"sku": "CUP", "qty": 6}], amount="150.00")  # the P7 shape: Reader saw one cup
    held = gw.handle(session("CUS-01", "charge", CHARGE), "charge", call)
    assert held.decision == APPROVAL and {"ITEMS_MISMATCH", "CHARGE_AMOUNT_MISMATCH"} <= set(codes(held))
    out = gw.approve(held.approval_id)
    assert out.executed and rail.money_calls() == [("charge", "fixture-vault-01", Decimal("150.00"), "s1:charge")]


def test_a_block_found_at_approval_time_is_not_reported_as_stale():
    gw, rail, _ = gate()
    _, held = _held_refund(gw)
    gw.store.db.execute("INSERT INTO refunds VALUES ('rf-other','ST-1042',NULL,'5.00','unknown')")
    out = gw.approve(held.approval_id)
    assert out.decision == BLOCK and "REFUND_OUTCOME_UNKNOWN" in codes(out) and "APPROVAL_STALE" not in codes(out)


def test_approval_works_for_amounts_passed_as_decimal():
    gw, rail, _ = gate()
    _, held = _held_refund(gw, dict(REFUND, amount=Decimal("30.00")))
    assert gw.approve(held.approval_id).executed


def test_approval_for_exactly_what_is_left_executes():
    gw, rail, _ = gate()
    _, held = _held_refund(gw, dict(REFUND, amount="30.00"))
    out = gw.approve(held.approval_id)
    assert out.executed and sum(c[2] for c in rail.money_calls()) == Decimal("30.00")


# -- boundaries -----------------------------------------------------------------------------------------
def test_refund_on_the_last_day_of_the_window_is_not_held():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", REFUND)
    ctx.as_of = datetime(2026, 10, 10, 12, tzinfo=UTC) + timedelta(days=30)  # order created 10 Oct 12:00
    assert "OUTSIDE_REFUND_WINDOW" not in codes(gw.handle(ctx, "refund", dict(REFUND)))
    ctx.as_of += timedelta(seconds=1)
    late = {f.code: f for f in gw.check(ctx, "refund", dict(REFUND))}["OUTSIDE_REFUND_WINDOW"]
    assert late.severity == APPROVAL and "30 days" in late.detail


def test_cumulative_and_drift_findings_explain_the_numbers():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", dict(REFUND, amount="20.00"))
    gw.handle(ctx, "refund", dict(REFUND, amount="20.00"))
    over = {f.code: f for f in gw.check(ctx, "refund", dict(REFUND, amount="20.00"))}["CUMULATIVE_REFUND_EXCEEDS_RMA"]
    assert over.severity == BLOCK and "10.00 left" in over.detail
    rail.txns["fixture-txn-001"].refunded += Decimal("5.00")  # a refund made outside the store
    drift = {f.code: f for f in gw.check(ctx, "refund", dict(REFUND, amount="1.00"))}["UNRECONCILED_RAIL_REFUNDS"]
    assert drift.severity == BLOCK and "25.00" in drift.detail and "20.00" in drift.detail


def test_refund_at_the_auto_limit_is_not_held_and_one_cent_above_is():
    gw, rail, _ = gate()
    args = {"order_no": "ST-1054", "rma_id": "RMA-1054", "amount": "200.00", "currency": "USD"}
    ctx = session("CUS-04", "refund", args)
    assert "AUTO_REFUND_LIMIT_EXCEEDED" not in codes(gw.handle(ctx, "refund", dict(args)))
    gw, rail, _ = gate()
    args = dict(args, amount="200.01")
    out = gw.handle(session("CUS-04", "refund", args), "refund", dict(args))
    assert codes(out).get("AUTO_REFUND_LIMIT_EXCEEDED") == APPROVAL


def test_every_blocked_attempt_is_counted():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", REFUND)
    gw.handle(ctx, "refund", dict(REFUND, order_no="ST-9999"))
    gw.handle(ctx, "refund", dict(REFUND, order_no="ST-9998"))
    assert ctx.blocked_attempts == 2
    held = gw.handle(ctx, "refund", dict(REFUND))
    assert held.decision == APPROVAL and "2 blocked call(s)" in next(
        f.detail for f in held.findings if f.code == "PRIOR_BLOCKED_ATTEMPT"
    )


# -- Reader comparison details ---------------------------------------------------------------------
def test_reader_amount_is_compared_as_money_not_text():
    gw, rail, _ = gate()
    out = gw.handle(session("CUS-01", "refund", REFUND, tutar="30"), "refund", dict(REFUND))
    assert out.decision == PASS, out.summary()


def test_a_reader_field_left_empty_does_not_hide_a_later_mismatch():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", REFUND, iade_kaydi_no=None, para_birimi="EUR")
    out = gw.handle(ctx, "refund", dict(REFUND))
    assert "para_birimi" in next(f.detail for f in out.findings if f.code == "READER_CALL_MISMATCH")


def test_reader_mismatches_are_all_listed():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "refund", REFUND, tutar="thirty", siparis_no="ST-1043")
    detail = next(f.detail for f in gw.handle(ctx, "refund", dict(REFUND)).findings if f.code == "READER_CALL_MISMATCH")
    assert "unreadable" in detail and "ST-1043" in detail and "; " in detail


def test_reader_and_call_may_name_quantities_either_way():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "charge", CHARGE)
    ctx.reader["kalemler"] = [{"sku": "CUP", "qty": 1}]  # Reader used the call's key
    call = dict(CHARGE, items=[{"sku": "CUP", "adet": 1}])  # and the agent the Reader's
    assert codes(gw.handle(ctx, "charge", call)) == {"CHARGE_NEEDS_CONFIRMATION": APPROVAL}  # no ITEMS_MISMATCH


def test_repeated_sku_lines_are_added_up():
    gw, rail, _ = gate()
    ctx = session("CUS-01", "charge", dict(CHARGE, items=[{"sku": "CUP", "qty": 2}], amount="50.00"))
    call = dict(CHARGE, items=[{"sku": "CUP", "qty": 1}, {"sku": "CUP", "qty": 1}], amount="50.00")
    assert codes(gw.handle(ctx, "charge", call)) == {"CHARGE_NEEDS_CONFIRMATION": APPROVAL}


# -- small pieces --------------------------------------------------------------------------------------
def test_decide_and_summary():
    assert _decide([]) == PASS
    assert _decide([Finding(APPROVAL, "A", "a"), Finding(BLOCK, "B", "b")]) == BLOCK
    assert _decide([Finding(PASS, "P", "p"), Finding(BLOCK, "B", "b")]) == BLOCK  # by rank, not alphabetically
    out = Outcome(BLOCK, [Finding(BLOCK, "X", "x"), Finding(APPROVAL, "Y", "y")])
    assert out.summary() == "BLOCK/not_called (X: x; Y: y)"
    assert Outcome(PASS, []).summary() == "PASS/not_called"


def test_the_clock_is_timezone_aware():
    assert utcnow().tzinfo is not None
