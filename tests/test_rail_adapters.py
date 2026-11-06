"""The Braintree adapters against a stand-in SDK, and the run record (runmeta). No network: the `braintree` module
is replaced by a small fake that answers like the sandbox did (docs/arastirma/2026-10-23-braintree-deneme.md)."""

import json
import sys
import types
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from counterfoil import runmeta
from counterfoil.rail import BraintreeRail, FakeRail, FakeTxn, SandboxRail
from counterfoil.scenarios import load_records
from counterfoil.store import Store


class NotFoundError(Exception):
    pass


def ok(txn):
    return NS(is_success=True, transaction=txn)


def failed(*errors, message="failed"):
    return NS(is_success=False, errors=NS(deep_errors=[NS(code=c, message=m) for c, m in errors]), message=message)


class FakeSDK:
    """Just the parts of the braintree SDK the adapters touch."""

    def __init__(self):
        self.txns: dict[str, NS] = {}
        self.calls: list[tuple] = []
        self.next_id = 0
        self.sale_result = None
        self.customer_result = None
        sdk = self

        class Transaction:
            def refund(self, tid, amount):
                sdk.calls.append(("refund", tid, amount))
                parent = sdk.txns[tid]
                rid = sdk._new(amount, "submitted_for_settlement")
                parent.refund_ids.append(rid)
                return ok(sdk.txns[rid])

            def void(self, tid):
                sdk.calls.append(("void", tid))
                return failed(("91504", "Transaction can only be voided if authorized"))

            def sale(self, params):
                sdk.calls.append(("sale", params))
                if sdk.sale_result is not None:
                    return sdk.sale_result
                return ok(sdk.txns[sdk._new(params["amount"], "submitted_for_settlement")])

            def find(self, tid):
                if tid not in sdk.txns:
                    raise NotFoundError(tid)
                return sdk.txns[tid]

        class Customer:
            def create(self, params):
                sdk.calls.append(("customer", params))
                if sdk.customer_result is not None:
                    return sdk.customer_result
                return NS(is_success=True, customer=NS(payment_methods=[NS(token="real-vault-1")]))

        self.module = types.ModuleType("braintree")
        self.module.BraintreeGateway = lambda config: NS(transaction=Transaction(), customer=Customer(), config=config)
        self.module.Configuration = lambda **kw: kw
        self.module.Environment = NS(Sandbox="sandbox-env")
        self.module.exceptions = NS(NotFoundError=NotFoundError)

    def _new(self, amount, status):
        self.next_id += 1
        tid = f"bt-{self.next_id}"
        self.txns[tid] = NS(
            id=tid, amount=Decimal(str(amount)), status=status, refund_ids=[], payment_instrument_type="paypal_account"
        )
        return tid


@pytest.fixture
def sdk(monkeypatch):
    fake = FakeSDK()
    monkeypatch.setitem(sys.modules, "braintree", fake.module)
    for k, v in {
        "BRAINTREE_ENVIRONMENT": "sandbox",
        "BRAINTREE_MERCHANT_ID": "m",
        "BRAINTREE_PUBLIC_KEY": "pub",
        "BRAINTREE_PRIVATE_KEY": "priv",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("BRAINTREE_MERCHANT_ACCOUNT_ID", raising=False)
    return fake


# -- BraintreeRail -------------------------------------------------------------------------------------
def test_refuses_anything_but_the_sandbox(sdk, monkeypatch):
    monkeypatch.setenv("BRAINTREE_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="sandbox"):
        BraintreeRail()


def test_configures_the_sandbox_environment(sdk):
    rail = BraintreeRail()
    assert rail.gw.config["environment"] == "sandbox-env" and rail.gw.config["merchant_id"] == "m"


def test_refund_and_charge_map_to_rail_results(sdk):
    rail = BraintreeRail()
    sale = rail.charge("tok", Decimal("25.00"), "order-1")
    assert sale.ok and sale.status == "submitted_for_settlement"
    assert sdk.calls[-1][1] == {
        "amount": "25.00",
        "payment_method_token": "tok",
        "order_id": "order-1",
        "options": {"submit_for_settlement": True},
    }
    refund = rail.refund(sale.id, Decimal("10.00"))
    assert refund.ok and sdk.calls[-1] == ("refund", sale.id, "10.00")  # amounts go out as strings, never floats


def test_rail_errors_carry_codes(sdk):
    out = BraintreeRail().void("bt-x")
    assert not out.ok and out.error == "91504 Transaction can only be voided if authorized"
    sdk.sale_result = failed(message="Gateway Rejected: duplicate")
    assert BraintreeRail().charge("tok", Decimal("1.00"), "o").error == "Gateway Rejected: duplicate"


def test_refunded_total_ignores_refunds_that_did_not_go_through(sdk):
    rail = BraintreeRail()
    sale = rail.charge("tok", Decimal("100.00"), "o")
    for amount, status in [
        ("10.00", "settled"),
        ("20.00", "failed"),
        ("5.00", "voided"),
        ("7.00", "submitted_for_settlement"),
    ]:
        r = rail.refund(sale.id, Decimal(amount))
        sdk.txns[r.id].status = status
    assert rail.refunded_total(sale.id) == Decimal("17.00")
    assert rail.refunded_total("missing") is None


def test_find(sdk):
    rail = BraintreeRail()
    sale = rail.charge("tok", Decimal("3.00"), "o")
    assert rail.find(sale.id)["payment_instrument_type"] == "paypal_account"
    assert rail.find("missing") is None


# -- SandboxRail ---------------------------------------------------------------------------------------
def test_sandbox_rail_creates_real_counterparts_once_and_replays_history(sdk):
    store = Store(load_records())
    rail = SandboxRail(store, "run-1")
    out = rail.refund("fixture-txn-003", Decimal("5.00"))  # ST-1050 already has a completed USD 40.00 refund
    assert out.ok
    sales = [c for c in sdk.calls if c[0] == "sale"]
    assert len(sales) == 1 and sales[0][1]["amount"] == "120.00" and sales[0][1]["order_id"] == "run-1:ST-1050"
    history = [c for c in sdk.calls if c[0] == "refund"]
    assert [c[2] for c in history] == ["40.00", "5.00"]  # the scenario's earlier refund, then ours
    rail.refund("fixture-txn-003", Decimal("1.00"))
    assert len([c for c in sdk.calls if c[0] == "sale"]) == 1  # reused, not created again
    assert rail.money_calls()[0][:3] == ("refund", "fixture-txn-003", Decimal("5.00"))


def test_sandbox_rail_unknown_transactions_fail_like_the_rail(sdk):
    rail = SandboxRail(Store(load_records()), "run-1")
    assert rail.refund("nope", Decimal("1.00")).error.startswith("91504")
    assert rail.void("nope").error.startswith("91504")
    assert rail.refunded_total("nope") is None and rail.find("nope") is None


def test_sandbox_rail_vaults_a_payment_method_once(sdk):
    rail = SandboxRail(Store(load_records()), "run-1")
    rail.charge("fixture-vault-01", Decimal("25.00"), "reorder-1")
    rail.charge("fixture-vault-01", Decimal("50.00"), "reorder-2")
    assert len([c for c in sdk.calls if c[0] == "customer"]) == 1
    sales = [c[1] for c in sdk.calls if c[0] == "sale"]
    assert [s["payment_method_token"] for s in sales] == ["real-vault-1", "real-vault-1"]
    assert sales[0]["order_id"] == "run-1:reorder-1"


def test_sandbox_rail_find_maps_back_to_the_fixture_id(sdk, monkeypatch):
    monkeypatch.setenv("BRAINTREE_MERCHANT_ACCOUNT_ID", "acct")
    rail = SandboxRail(Store(load_records()), "run-1")
    found = rail.find("fixture-txn-001")
    assert found["id"] == "fixture-txn-001" and found["braintree_id"].startswith("bt-")
    assert [c[1] for c in sdk.calls if c[0] == "sale"][0]["merchant_account_id"] == "acct"
    assert rail.refunded_total("fixture-txn-001") == Decimal("0")


def test_sandbox_rail_setup_failures_are_loud(sdk):
    rail = SandboxRail(Store(load_records()), "run-1")
    sdk.sale_result = failed(message="processor declined")
    with pytest.raises(RuntimeError, match="setup sale"):
        rail.refund("fixture-txn-001", Decimal("1.00"))
    sdk.customer_result = NS(is_success=False, message="no")
    with pytest.raises(RuntimeError, match="vault setup"):
        rail.charge("fixture-vault-01", Decimal("1.00"), "o")


# -- FakeRail edge answers -----------------------------------------------------------------------------
def test_fake_rail_answers_like_the_card_sandbox():
    rail = FakeRail({"t": FakeTxn(Decimal("50.00")), "u": FakeTxn(Decimal("50.00"), "submitted_for_settlement")})
    assert rail.refund("missing", Decimal("1.00")).error.startswith("91504")
    assert rail.refund("u", Decimal("1.00")).error.startswith("91506")
    assert rail.refund("t", Decimal("50.01")).error.startswith("91521")
    assert rail.refund("t", Decimal("50.00")).ok
    assert rail.refund("t", Decimal("1.00")).error.startswith("91512")
    assert rail.void("t").error.startswith("91504") and rail.void("u").ok
    assert rail.charge("tok", Decimal("5.00"), "a").ok and "duplicate" in rail.charge("tok", Decimal("5.00"), "b").error
    assert rail.find("missing") is None and rail.find("t")["refunded"] == "50.00"


# -- runmeta -------------------------------------------------------------------------------------------
def test_run_record_has_machine_code_and_model_but_no_key(tmp_path, monkeypatch):
    cfg = NS(
        model="claude-x", base_url="https://gateway.astropods.ai/v1", temperature=0, seed=7, api_key="sk-secret-123"
    )
    out = tmp_path / "run.jsonl"
    path = runmeta.write(out, cfg, {"split": "dev"}, "fake")
    meta = json.loads(path.read_text())
    assert meta["selection"] == {"split": "dev"} and meta["rail"] == "fake"
    assert meta["model"]["endpoint_host"] == "gateway.astropods.ai" and "Bedrock" in meta["model"]["provider_route"]
    assert meta["machine"]["python"] and "commit" in meta["code"]
    assert "sk-secret-123" not in path.read_text()
    runmeta.finish(out, [{"status": "ok"}, {"status": "ok"}, {"status": "agent_error"}])
    meta = json.loads(path.read_text())
    assert meta["rows"] == 3 and meta["status"] == {"ok": 2, "agent_error": 1} and meta["finished_at"]


def test_run_record_survives_an_unreachable_local_model():
    cfg = NS(model="qwen2.5", base_url="http://127.0.0.1:9/v1", temperature=0, seed=None)
    info = runmeta.model(cfg)
    assert info["endpoint_host"] == "127.0.0.1:9" and "ollama_error" in info


def test_missing_tools_leave_fields_empty():
    assert runmeta._run("definitely-not-a-command-xyz") == ""
