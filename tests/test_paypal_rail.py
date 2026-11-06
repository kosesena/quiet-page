"""PayPal REST rail with the HTTP layer faked (no network): request shapes, error mapping, idempotency, unknown
outcomes, the fixture mapping, and the gate in front of Agent Toolkit's create_refund."""

import json
import re
from decimal import Decimal

import pytest

from counterfoil.gateway import APPROVAL, BLOCK, PASS, Gateway
from counterfoil.paypal import SANDBOX, PayPalRestRail, PayPalSandboxRail, PayPalUnknown
from counterfoil.scenarios import attempt, build, load_scenarios
from counterfoil.toolkit import create_refund

BY_ID = {s["id"]: s for s in load_scenarios()}
CLIENT_ID, SECRET = "test-client-id-abc", "test-secret-xyz"


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", SECRET)
    monkeypatch.delenv("PAYPAL_ENVIRONMENT", raising=False)


class FakePayPal:
    """Just enough of the PayPal sandbox: OAuth, Orders v2 (card / vault_id, captured at once), captures, refunds
    with PayPal's limits, authorization void, /v3/vault, and PayPal-Request-Id idempotency."""

    def __init__(self):
        self.requests: list[tuple[str, str, dict, dict | None]] = []
        self.captures, self.orders, self.auths, self.done = {}, {}, {}, {}
        self.n = 0
        self.fail_next: int | None = None
        self.tokens_issued = 0

    def _id(self, p):
        self.n += 1
        return f"{p}{self.n:04d}"

    def add_capture(self, value, currency="USD"):
        oid, cid = self._id("ORDER"), self._id("CAP")
        self.captures[cid] = {
            "id": cid,
            "status": "COMPLETED",
            "amount": {"value": value, "currency_code": currency},
            "supplementary_data": {"related_ids": {"order_id": oid}},
        }
        self.orders[oid] = {
            "id": oid,
            "status": "COMPLETED",
            "purchase_units": [{"payments": {"captures": [self.captures[cid]], "refunds": []}}],
        }
        return cid

    def __call__(self, method, url, headers, body, timeout):
        assert url.startswith(SANDBOX)
        path = url[len(SANDBOX) :]
        payload = json.loads(body) if body and headers.get("Content-Type") == "application/json" else None
        self.requests.append((method, path, headers, payload))
        if self.fail_next:
            code, self.fail_next = self.fail_next, None
            return code, {"name": "INTERNAL_SERVER_ERROR"}
        rid = headers.get("PayPal-Request-Id")
        if rid and rid in self.done:
            return self.done[rid]
        out = self._route(method, path, payload)
        if rid:
            self.done[rid] = out
        return out

    def _route(self, method, path, p):
        if path == "/v1/oauth2/token":
            self.tokens_issued += 1
            return 200, {"access_token": f"A21-token-{self.tokens_issued}", "expires_in": 32400}
        if m := re.fullmatch(r"/v2/payments/captures/(\w+)", path):
            c = self.captures.get(m[1])
            return (
                (200, c) if c else (404, {"name": "RESOURCE_NOT_FOUND", "details": [{"issue": "INVALID_RESOURCE_ID"}]})
            )
        if m := re.fullmatch(r"/v2/checkout/orders/(\w+)", path):
            return 200, self.orders[m[1]]
        if m := re.fullmatch(r"/v2/payments/captures/(\w+)/refund", path):
            return self._refund(m[1], p)
        if m := re.fullmatch(r"/v2/payments/authorizations/(\w+)/void", path):
            if self.auths.get(m[1]) != "CREATED":
                return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PREVIOUSLY_VOIDED"}]}
            self.auths[m[1]] = "VOIDED"
            return 204, None
        if path == "/v2/checkout/orders":
            src = p["payment_source"]
            if not ("card" in src or src.get("paypal", {}).get("vault_id")):
                return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PAYER_ACTION_REQUIRED"}]}
            amt = p["purchase_units"][0]["amount"]
            cid = self.add_capture(amt["value"], amt["currency_code"])
            oid = self.captures[cid]["supplementary_data"]["related_ids"]["order_id"]
            return 201, self.orders[oid]
        if path == "/v3/vault/setup-tokens":
            return 201, {"id": self._id("SETUP"), "status": "APPROVED"}
        if path == "/v3/vault/payment-tokens":
            return 201, {"id": self._id("VAULT")}
        raise AssertionError(f"unexpected {method} {path}")

    def _refund(self, cid, p):
        cap = self.captures[cid]
        order = self.orders[cap["supplementary_data"]["related_ids"]["order_id"]]
        refunds = order["purchase_units"][0]["payments"]["refunds"]
        done = sum((Decimal(r["amount"]["value"]) for r in refunds), Decimal("0"))
        total = Decimal(cap["amount"]["value"])
        if done >= total:
            return 422, {
                "name": "UNPROCESSABLE_ENTITY",
                "details": [
                    {"issue": "CAPTURE_FULLY_REFUNDED", "description": "The capture has already been fully refunded"}
                ],
            }
        if done + Decimal(p["amount"]["value"]) > total:
            return 422, {
                "name": "UNPROCESSABLE_ENTITY",
                "details": [
                    {
                        "issue": "REFUND_AMOUNT_EXCEEDED",
                        "description": "The refund amount must be less than or equal to the capture amount that has not yet been refunded.",
                    }
                ],
            }
        r = {
            "id": self._id("REF"),
            "status": "COMPLETED",
            "amount": p["amount"],
            "links": [{"rel": "up", "href": f"{SANDBOX}/v2/payments/captures/{cid}"}],
        }
        refunds.append(r)
        return 201, r

    def money_posts(self):
        return [
            (m, path) for m, path, _, _ in self.requests if m == "POST" and "/refund" in path or path.endswith("/void")
        ]


def rail():
    pp = FakePayPal()
    return PayPalRestRail(transport=pp), pp


# -- configuration -------------------------------------------------------------------------------------
def test_refuses_without_credentials(monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET")
    with pytest.raises(RuntimeError, match="PAYPAL_CLIENT_SECRET"):
        PayPalRestRail(transport=FakePayPal())


def test_refuses_live_environment(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENVIRONMENT", "live")
    with pytest.raises(RuntimeError, match="sandbox"):
        PayPalRestRail(transport=FakePayPal())


def test_secret_never_in_repr_or_errors():
    r, pp = rail()
    r.find("CAP9999")  # token fetched
    pp.fail_next = 503
    with pytest.raises(PayPalUnknown) as exc:
        r.find("CAP9999")
    texts = [repr(r), str(exc.value), r.refund("CAP9999", Decimal("1.00")).error]
    r._token, pp.fail_next = None, 401
    with pytest.raises(RuntimeError) as token_exc:
        r.find("CAP9999")
    for text in texts + [str(token_exc.value)]:
        assert SECRET not in text and CLIENT_ID not in text and r._auth not in text


def test_token_is_fetched_once_and_cached():
    r, pp = rail()
    cid = pp.add_capture("50.00")
    r.find(cid)
    r.refund(cid, Decimal("10.00"))
    assert pp.tokens_issued == 1
    auth = next(h for m, p, h, _ in pp.requests if p == "/v1/oauth2/token")["Authorization"]
    assert auth.startswith("Basic ")


# -- the Rail interface --------------------------------------------------------------------------------
def test_refund_is_the_toolkit_rest_call():
    r, pp = rail()
    cid = pp.add_capture("90.00")
    out = r.refund(cid, Decimal("30.00"))
    assert out.ok and out.status == "COMPLETED" and out.id.startswith("REF")
    method, path, headers, payload = next(x for x in pp.requests if x[1].endswith("/refund"))
    assert (method, path) == ("POST", f"/v2/payments/captures/{cid}/refund")
    assert payload == {"amount": {"value": "30.00", "currency_code": "USD"}}
    assert headers["PayPal-Request-Id"] and headers["Authorization"].startswith("Bearer ")


def test_refund_limits_map_to_failed_results():
    r, pp = rail()
    cid = pp.add_capture("50.00")
    too_big = r.refund(cid, Decimal("60.00"))
    assert not too_big.ok and "REFUND_AMOUNT_EXCEEDED" in too_big.error and too_big.error.startswith("422")
    assert r.refund(cid, Decimal("50.00")).ok
    assert "CAPTURE_FULLY_REFUNDED" in r.refund(cid, Decimal("1.00")).error


def test_refunded_total_and_find_read_the_order():
    r, pp = rail()
    cid = pp.add_capture("90.00")
    other = pp.add_capture("10.00")
    r.refund(cid, Decimal("30.00"))
    r.refund(cid, Decimal("20.00"))
    r.refund(other, Decimal("5.00"))
    assert r.refunded_total(cid) == Decimal("50.00")
    found = r.find(cid)
    assert found["amount"] == "90.00" and found["refunded"] == "50.00" and len(found["refund_ids"]) == 2
    assert r.find("CAP9999") is None and r.refunded_total("CAP9999") is None


def test_5xx_and_network_errors_are_unknown_not_failed():
    r, pp = rail()
    cid = pp.add_capture("50.00")
    r.find(cid)
    pp.fail_next = 500
    with pytest.raises(PayPalUnknown):
        r.find(cid)

    def down(*a):
        raise PayPalUnknown("POST /v2/payments/captures: TimeoutError")

    r.send = down
    with pytest.raises(PayPalUnknown):
        r.refund(cid, Decimal("1.00"))


def test_retry_with_the_same_request_id_moves_money_once():
    r, pp = rail()
    cid = pp.add_capture("50.00")
    first = r.refund(cid, Decimal("20.00"), request_id="cf-refund-res-1")
    again = r.refund(cid, Decimal("20.00"), request_id="cf-refund-res-1")
    assert first.id == again.id and r.refunded_total(cid) == Decimal("20.00")


def test_charge_uses_the_vault_id_and_captures():
    r, pp = rail()
    out = r.charge("VAULT-PAYPAL-1", Decimal("25.00"), "session-1:charge")
    assert out.ok and out.id.startswith("CAP")
    _, _, headers, payload = next(x for x in pp.requests if x[1] == "/v2/checkout/orders")
    assert payload["payment_source"] == {"paypal": {"vault_id": "VAULT-PAYPAL-1"}}
    assert payload["intent"] == "CAPTURE" and payload["purchase_units"][0]["amount"] == {
        "currency_code": "USD",
        "value": "25.00",
    }
    assert headers["PayPal-Request-Id"] == "cf-charge-session-1:charge"
    assert r.charge("VAULT-PAYPAL-1", Decimal("25.00"), "session-1:charge").id == out.id  # same request, no 2nd sale


def test_void_an_authorization():
    r, pp = rail()
    pp.auths["AUTH0001"] = "CREATED"
    assert r.void("AUTH0001").ok
    again = r.void("AUTH0001")
    assert not again.ok and "PREVIOUSLY_VOIDED" in again.error


# -- behind the gate, on the fixture store -------------------------------------------------------------
def gate_on_paypal(sid):
    store, _, ctx = build(BY_ID[sid])
    pp = FakePayPal()
    paypal = PayPalSandboxRail(store, f"test-{sid}", transport=pp)
    return Gateway(store, paypal), paypal, pp, ctx


def test_clean_refund_reaches_paypal_through_the_gate():
    gw, paypal, pp, ctx = gate_on_paypal("CLEAN-01")
    tool, args = attempt(BY_ID["CLEAN-01"])
    out = gw.handle(ctx, tool, args)
    assert out.decision == PASS and out.executed and out.rail.id.startswith("REF")
    assert [c[0] for c in paypal.money_calls()] == ["refund"]
    real = paypal.real["fixture-txn-001"]
    assert ("POST", f"/v2/payments/captures/{real}/refund") in pp.money_posts()


@pytest.mark.parametrize("sid", ["P1-01", "P6-01", "P3-01"])
def test_attacks_stop_before_paypal(sid):
    gw, paypal, pp, ctx = gate_on_paypal(sid)
    tool, args = attempt(BY_ID[sid])
    out = gw.handle(ctx, tool, args)
    assert out.decision in (APPROVAL, BLOCK) and not paypal.money_calls()


def test_setup_replays_completed_refunds_so_reconciliation_agrees():
    gw, paypal, pp, ctx = gate_on_paypal("P3-01")  # a refund the store already paid
    order = gw.store.orders["ST-1050"]
    local = sum(
        Decimal(a)
        for (a,) in gw.store.sql("SELECT amount FROM refunds WHERE order_no='ST-1050' AND status='completed'")
    )
    assert paypal.refunded_total(order["braintree_transaction_id"]) == local


def test_charge_on_a_fixture_token_uses_a_vaulted_sandbox_card():
    store, _, _ = build(BY_ID["CLEAN-06"])
    pp = FakePayPal()
    paypal = PayPalSandboxRail(store, "t", transport=pp)
    out = paypal.charge("fixture-vault-02", Decimal("120.00"), "s:charge")
    payload = next(x[3] for x in pp.requests if x[1] == "/v2/checkout/orders" and "vault_id" in json.dumps(x[3]))
    assert out.ok and payload["payment_source"] == {"card": {"vault_id": paypal.real["fixture-vault-02"]}}


# -- Agent Toolkit's create_refund, gated -------------------------------------------------------------------
def test_toolkit_create_refund_params_go_through_the_gate():
    gw, paypal, pp, ctx = gate_on_paypal("CLEAN-01")
    _, args = attempt(BY_ID["CLEAN-01"])
    params = {
        "capture_id": "fixture-txn-001",
        "amount": {"currency_code": "USD", "value": "30.00"},
        "rma_id": args["rma_id"],
        "note_to_payer": "Return received",
    }
    out = create_refund(gw, ctx, params)
    assert out.decision == PASS and out.executed


def test_toolkit_full_refund_without_amount_is_checked_as_the_order_total():
    gw, paypal, pp, ctx = gate_on_paypal("P1-01")
    out = create_refund(gw, ctx, {"capture_id": "fixture-txn-001", "rma_id": "RMA-1042"})
    assert out.decision != PASS and not paypal.money_calls()


def test_toolkit_unknown_capture_is_blocked():
    gw, paypal, pp, ctx = gate_on_paypal("CLEAN-01")
    out = create_refund(
        gw, ctx, {"capture_id": "5TY05013RG002845M", "amount": {"currency_code": "USD", "value": "1.00"}}
    )
    assert out.decision == BLOCK and out.findings[0].code == "UNKNOWN_CAPTURE" and not pp.requests


def test_expired_token_is_refreshed_once_on_401():
    r, pp = rail()
    cid = pp.add_capture("50.00")
    r.find(cid)
    pp.fail_next = 401
    assert r.find(cid)["id"] == cid and pp.tokens_issued == 2


def test_urllib_transport_maps_http_errors_and_network_failures(monkeypatch):
    import io
    import urllib.error

    from counterfoil import paypal

    class Resp(io.BytesIO):
        status = 201

    def ok(req, timeout):
        assert req.full_url.startswith(SANDBOX) and req.get_method() == "POST"
        return Resp(b'{"id": "REF1"}')

    monkeypatch.setattr(paypal.urllib.request, "urlopen", ok)
    assert paypal.urllib_transport("POST", f"{SANDBOX}/x", {}, b"{}", 5) == (201, {"id": "REF1"})

    def http_error(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 422, "x", {}, io.BytesIO(b'{"name": "UNPROCESSABLE_ENTITY"}'))

    monkeypatch.setattr(paypal.urllib.request, "urlopen", http_error)
    assert paypal.urllib_transport("POST", f"{SANDBOX}/x", {}, None, 5) == (422, {"name": "UNPROCESSABLE_ENTITY"})

    def down(req, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(paypal.urllib.request, "urlopen", down)
    with pytest.raises(PayPalUnknown, match="URLError"):
        paypal.urllib_transport("GET", f"{SANDBOX}/x?secret=1", {}, None, 5)
