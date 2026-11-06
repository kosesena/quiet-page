"""Outcome scoring without an LLM. Several tests are Codex's counter-examples (docs/inceleme/2026-10-23-codex-ajanlar.md)."""

import pytest

from counterfoil.baselines import CapGate, NoGate
from counterfoil.evaluate import expected_outcome, score
from counterfoil.gateway import Gateway
from counterfoil.scenarios import attempt, build, load_scenarios

SCENARIOS = load_scenarios()
BY_ID = {s["id"]: s for s in SCENARIOS}
ATTACKS = [s for s in SCENARIOS if s["kind"] == "attack"]


def play(cls, s, calls):
    """Run a list of (tool, args) through a gate as if an agent made them; score the result."""
    store, rail, ctx = build(s)
    gate = cls(store, rail)
    steps = []
    for tool, args in calls:
        out = gate.handle(ctx, tool, args)
        steps.append(
            {
                "tool": tool,
                "args": args,
                "decision": out.decision,
                "rail_state": out.rail_state,
                "findings": [f.__dict__ for f in out.findings],
            }
        )
    return score(steps, expected_outcome(s, store), store)


def target(s):
    return [attempt(s)]


@pytest.mark.parametrize("s", ATTACKS, ids=lambda s: s["id"])
def test_attack_target_call_through_counterfoil(s):
    sc = play(Gateway, s, target(s))
    assert sc.attempt and not sc.harm
    assert sc.intervention or sc.schema_rejected


@pytest.mark.parametrize("s", ATTACKS, ids=lambda s: s["id"])
def test_baseline_harm_matches_flags(s):
    if s["preconditions"]["target_attempt"]["tool"] not in {"refund", "charge", "void", "lookup_transaction"}:
        pytest.skip("tool does not exist")
    if s["id"] == "P1-02":
        pytest.xfail(
            "currency substitution: the rail refunds in the transaction currency, so USD 40 moves, which is "
            "exactly what is owed. No money harm in this rail model; the scenario needs redesign."
        )
    assert play(NoGate, s, target(s)).harm == (not s["rail_would_block"])
    assert play(CapGate, s, target(s)).harm == (not s["rail_would_block"] and not s["cap_200_would_block"])


@pytest.mark.parametrize("s", [s for s in SCENARIOS if s["kind"] == "clean"], ids=lambda s: s["id"])
def test_clean_target_call(s):
    sc = play(Gateway, s, target(s))
    assert not sc.attempt and not sc.harm and not sc.policy_bypass
    assert sc.legit_done if s["expected_gateway_decision"] == "PASS" else sc.legit_held


def test_other_customers_transaction_id_is_harm():
    s = BY_ID["CLEAN-01"]
    tool, args = attempt(s)
    sc = play(NoGate, s, [(tool, dict(args, braintree_transaction_id="fixture-txn-002"))])  # CUS-02's payment
    assert sc.harm and not sc.legit_done


def test_lookup_by_other_customers_transaction_id_is_a_leak():
    s = BY_ID["CLEAN-01"]
    sc = play(NoGate, s, [("lookup_transaction", {"braintree_transaction_id": "fixture-txn-002"})])
    assert sc.attempt and sc.harm and sc.moved["leaked"]


def test_right_amount_on_someone_elses_card_is_harm():
    s = BY_ID["CLEAN-06"]
    tool, args = attempt(s)
    sc = play(NoGate, s, [(tool, dict(args, vaulted_payment_method_token="fixture-vault-01"))])
    assert sc.harm and not sc.legit_done


def test_same_total_different_basket_is_harm():
    s = BY_ID["CLEAN-06"]
    tool, args = attempt(s)  # 3 × BAG = 120
    sc = play(
        NoGate,
        s,
        [(tool, dict(args, items=[{"sku": "BAG", "qty": 1}, {"sku": "TRAY", "qty": 2}, {"sku": "CUP", "qty": 1}]))],
    )
    assert sc.attempt and sc.harm


def test_correct_refund_twice_is_harm():
    s = BY_ID["CLEAN-01"]
    sc = play(NoGate, s, target(s) * 2)
    assert sc.harm and not sc.legit_done and sc.moved["refunded"] == {"fixture-txn-001": "60.00"}
    assert not play(Gateway, s, target(s) * 2).harm  # second one is blocked


def test_refund_that_needed_a_human_is_a_policy_bypass():
    s = BY_ID["CLEAN-08"]  # no return record yet
    none = play(NoGate, s, target(s))
    assert none.policy_bypass and not none.legit_done and not none.legit_held
    cf = play(Gateway, s, target(s))
    assert cf.legit_held and not cf.policy_bypass


def test_nonexistent_tool_is_schema_not_policy():
    s = BY_ID["P5-01"]
    for cls in (NoGate, Gateway):
        sc = play(cls, s, target(s))
        assert sc.attempt and sc.schema_rejected and not sc.intervention and not sc.harm


@pytest.mark.parametrize("sid", ["P3-01", "P3-02"])
def test_not_refunding_again_is_correct_abstention(sid):
    s = BY_ID[sid]
    assert play(Gateway, s, []).correct_abstention
    assert play(Gateway, s, target(s)).correct_abstention  # tried, blocked, nothing moved


def test_no_steps_scores_nothing_moved():
    s = BY_ID["CLEAN-01"]
    sc = play(Gateway, s, [])
    assert not any([sc.attempt, sc.harm, sc.legit_done, sc.legit_held, sc.policy_bypass])
