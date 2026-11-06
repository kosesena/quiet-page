"""PayPal REST rail (Orders v2 + Payments v2, sandbox only). The same Rail interface as the Braintree adapters, so the
gate sits in front of the REST call PayPal Agent Toolkit's `create_refund` makes: POST /v2/payments/captures/{id}/refund.

A rail transaction id here is a PayPal capture id. Mapping onto the Rail methods:
  refund(capture, amount)   POST /v2/payments/captures/{capture}/refund      (Agent Toolkit: create_refund)
  void(authorization)       POST /v2/payments/authorizations/{id}/void       (captures cannot be voided)
  charge(vault_id, amount)  POST /v2/checkout/orders, intent CAPTURE, payment_source.<type>.vault_id
  find(capture)             GET  /v2/payments/captures/{capture} + GET /v2/checkout/orders/{order} for its refunds
  refunded_total(capture)   sum of the order's refunds on that capture that did not fail or get cancelled

Credentials come only from PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET and never leave this object (not in errors, not in
repr). Every money call carries a PayPal-Request-Id, so a retry after a timeout cannot move money twice. A 5xx or a
network error raises instead of returning a failed RailResult: the outcome is unknown, and the gate keeps the
reservation counted (rail_state 'unknown') rather than releasing it.

The HTTP layer is one injectable function, so the tests run with no network.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from decimal import Decimal

from .rail import RailResult

SANDBOX = "https://api-m.sandbox.paypal.com"
CREDENTIAL_VARS = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET")
DEAD = ("FAILED", "CANCELLED", "DECLINED")  # refund / capture states that moved no money
# PayPal's published sandbox Visa; only used to create setup purchases in the sandbox (PayPalSandboxRail)
SANDBOX_CARD = {"number": "4111111111111111", "expiry": "2030-12", "security_code": "123"}

# send(method, url, headers, body_bytes_or_None, timeout) -> (status_code, parsed_json_or_None)
Transport = Callable[[str, str, dict, bytes | None, float], tuple[int, dict | None]]


class PayPalUnknown(RuntimeError):
    """The request may or may not have reached PayPal (network error, timeout, 5xx)."""


def configured() -> bool:
    return all(os.environ.get(v) for v in CREDENTIAL_VARS)


def urllib_transport(method, url, headers, body, timeout):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PayPalUnknown(f"{method} {url.split('?')[0]}: {type(e).__name__}") from None


def _error(code: int, body: dict | None) -> str:
    """'422 UNPROCESSABLE_ENTITY REFUND_AMOUNT_EXCEEDED: The refund amount must be less than ...'"""
    body = body or {}
    detail = (body.get("details") or [{}])[0]
    issue = detail.get("issue") or body.get("error") or ""
    text = detail.get("description") or body.get("message") or body.get("error_description") or ""
    return " ".join(x for x in (str(code), body.get("name", ""), f"{issue}:" if issue else "", text) if x).rstrip(":")


class PayPalRestRail:
    """PayPal REST sandbox. Refuses anything but the sandbox host."""

    name = "paypal-sandbox"

    def __init__(
        self,
        transport: Transport | None = None,
        currency: str | None = None,
        vault_source: str = "paypal",
        timeout: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if os.environ.get("PAYPAL_ENVIRONMENT", "sandbox") != "sandbox":
            raise RuntimeError("Counterfoil only talks to the PayPal sandbox")
        missing = [v for v in CREDENTIAL_VARS if not os.environ.get(v)]
        if missing:
            raise RuntimeError(f"PayPal REST rail needs {', '.join(missing)} in the environment")
        self._auth = base64.b64encode(
            f"{os.environ['PAYPAL_CLIENT_ID']}:{os.environ['PAYPAL_CLIENT_SECRET']}".encode()
        ).decode()
        self.send = transport or urllib_transport
        self.currency = currency or os.environ.get("PAYPAL_CURRENCY", "USD")
        self.vault_source = vault_source  # 'paypal' (vaulted PayPal wallet) or 'card'
        self.timeout, self.clock = timeout, clock
        self._token: tuple[str, float] | None = None
        self.calls: list[tuple] = []

    def __repr__(self):
        return f"PayPalRestRail(base={SANDBOX!r}, currency={self.currency!r})"

    # -- HTTP --------------------------------------------------------------------------------------
    def _access_token(self) -> str:
        if self._token and self.clock() < self._token[1]:
            return self._token[0]
        code, body = self.send(
            "POST",
            f"{SANDBOX}/v1/oauth2/token",
            {
                "Authorization": f"Basic {self._auth}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            b"grant_type=client_credentials",
            self.timeout,
        )
        if code != 200 or not body or "access_token" not in body:
            raise RuntimeError(f"PayPal sandbox token request failed: {code} {(body or {}).get('error', '')}".rstrip())
        self._token = (body["access_token"], self.clock() + max(0, int(body.get("expires_in", 0)) - 60))
        return self._token[0]

    def _req(self, method: str, path: str, payload: dict | None = None, request_id: str | None = None):
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        body = json.dumps(payload).encode() if payload is not None else None
        code, data = self.send(method, f"{SANDBOX}{path}", headers, body, self.timeout)
        if code == 401:  # token revoked or expired early: fetch a new one once
            self._token = None
            headers["Authorization"] = f"Bearer {self._access_token()}"
            code, data = self.send(method, f"{SANDBOX}{path}", headers, body, self.timeout)
        if code >= 500:
            raise PayPalUnknown(f"{method} {path}: {_error(code, data)}")
        return code, data

    @staticmethod
    def _money_result(code, data) -> RailResult:
        if 200 <= code < 300 and data and data.get("status") not in DEAD:
            return RailResult(True, data.get("id"), data.get("status"))
        if 200 <= code < 300:
            return RailResult(
                False, (data or {}).get("id"), (data or {}).get("status"), f"{code} {(data or {}).get('status')}"
            )
        return RailResult(False, error=_error(code, data))

    # -- Rail interface ------------------------------------------------------------------------------
    def _capture(self, capture_id: str) -> dict | None:
        code, data = self._req("GET", f"/v2/payments/captures/{capture_id}")
        return data if code == 200 else None

    def refund(self, transaction_id, amount, request_id: str | None = None):
        cap = self._capture(transaction_id)
        if cap is None:
            return RailResult(False, error=f"404 RESOURCE_NOT_FOUND capture {transaction_id}")
        payload = {"amount": {"value": str(amount), "currency_code": cap["amount"]["currency_code"]}}
        code, data = self._req(
            "POST",
            f"/v2/payments/captures/{transaction_id}/refund",
            payload,
            request_id or f"cf-refund-{uuid.uuid4().hex}",
        )
        return self._money_result(code, data)

    def void(self, transaction_id):
        code, data = self._req(
            "POST", f"/v2/payments/authorizations/{transaction_id}/void", None, f"cf-void-{uuid.uuid4().hex}"
        )
        if code == 204 or (200 <= code < 300 and not data):
            return RailResult(True, transaction_id, "VOIDED")
        return self._money_result(code, data)

    def charge(self, payment_method_token, amount, order_id):
        """A merchant-initiated order on a vaulted payment method; PayPal captures it in the same call."""
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": order_id[:256],
                    "custom_id": order_id[:127],
                    "amount": {"currency_code": self.currency, "value": str(amount)},
                }
            ],
            "payment_source": {self.vault_source: {"vault_id": payment_method_token}},
        }
        # the request id is the store's charge request id: the same request cannot be charged twice
        code, data = self._req("POST", "/v2/checkout/orders", payload, f"cf-charge-{order_id}"[:108])
        if not (200 <= code < 300) or not data:
            return RailResult(False, error=_error(code, data))
        captures = [c for pu in data.get("purchase_units", []) for c in pu.get("payments", {}).get("captures", [])]
        if not captures:
            return RailResult(
                False, data.get("id"), data.get("status"), f"order {data.get('status')} without a capture"
            )
        return self._money_result(200, captures[0])

    def _refunds(self, cap: dict) -> list[dict]:
        order_id = cap.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        if not order_id:
            return []
        code, order = self._req("GET", f"/v2/checkout/orders/{order_id}")
        if code != 200 or not order:
            return []
        out = []
        for pu in order.get("purchase_units", []):
            for r in pu.get("payments", {}).get("refunds", []):
                ups = [ln["href"] for ln in r.get("links", []) if ln.get("rel") == "up"]
                if not ups or any(h.rstrip("/").endswith(cap["id"]) for h in ups):
                    out.append(r)
        return out

    def refunded_total(self, transaction_id):
        cap = self._capture(transaction_id)
        if cap is None:
            return None
        return sum(
            (Decimal(r["amount"]["value"]) for r in self._refunds(cap) if r.get("status") not in DEAD), Decimal("0.00")
        )

    def find(self, transaction_id):
        cap = self._capture(transaction_id)
        if cap is None:
            return None
        refunds = self._refunds(cap)
        return {
            "id": cap["id"],
            "amount": cap["amount"]["value"],
            "currency": cap["amount"]["currency_code"],
            "status": cap.get("status"),
            "refund_ids": [r["id"] for r in refunds],
            "refunded": str(
                sum((Decimal(r["amount"]["value"]) for r in refunds if r.get("status") not in DEAD), Decimal("0.00"))
            ),
            "payment_instrument_type": "paypal_rest",
        }


class PayPalSandboxRail(PayPalRestRail):
    """PayPal REST sandbox behind the store's fixture ids, like SandboxRail does for Braintree.

    The first time a run touches a fixture transaction, a sandbox order for the order total is created and captured
    with PayPal's published test card (a PayPal wallet order needs a buyer to approve it in a browser), and the
    refunds the store already completed are replayed on it. A fixture vaulted token becomes a vaulted sandbox card
    (setup token → payment token, /v3/vault). Everything after that is a real sandbox call.
    """

    def __init__(self, store, run_tag: str, transport: Transport | None = None):
        super().__init__(transport, currency=None, vault_source="card")
        self.store, self.tag = store, run_tag
        self.orders = {o["braintree_transaction_id"]: o for o in store.orders.values()}
        self.real: dict[str, str] = {}  # fixture id -> capture id / vault id

    def _txn(self, fixture_id: str) -> str | None:
        if fixture_id not in self.real:
            o = self.orders.get(fixture_id)
            if o is None:
                return None
            payload = {
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": o["order_no"],
                        "custom_id": f"{self.tag}:{o['order_no']}"[:127],
                        "amount": {"currency_code": o["currency"], "value": str(o["total"])},
                    }
                ],
                "payment_source": {"card": SANDBOX_CARD},
            }
            code, data = self._req("POST", "/v2/checkout/orders", payload, f"cf-setup-{self.tag}-{o['order_no']}"[:108])
            caps = [
                c for pu in (data or {}).get("purchase_units", []) for c in pu.get("payments", {}).get("captures", [])
            ]
            if not (200 <= code < 300) or not caps:
                raise RuntimeError(f"sandbox setup order for {o['order_no']} failed: {_error(code, data)}")
            self.real[fixture_id] = caps[0]["id"]
            done = self.store.db.execute(
                "SELECT amount FROM refunds WHERE order_no=? AND status='completed'", (o["order_no"],)
            ).fetchall()
            for (amount,) in done:  # history the scenario says already happened
                super().refund(caps[0]["id"], Decimal(str(amount)))
        return self.real[fixture_id]

    def _vault(self, fixture_token: str) -> str:
        if fixture_token not in self.real:
            code, setup = self._req(
                "POST",
                "/v3/vault/setup-tokens",
                {"payment_source": {"card": SANDBOX_CARD}},
                f"cf-setup-token-{self.tag}-{fixture_token}"[:108],
            )
            if not (200 <= code < 300) or not setup:
                raise RuntimeError(f"sandbox vault setup failed: {_error(code, setup)}")
            code, token = self._req(
                "POST",
                "/v3/vault/payment-tokens",
                {"payment_source": {"token": {"id": setup["id"], "type": "SETUP_TOKEN"}}},
                f"cf-payment-token-{self.tag}-{fixture_token}"[:108],
            )
            if not (200 <= code < 300) or not token:
                raise RuntimeError(f"sandbox vault setup failed: {_error(code, token)}")
            self.real[fixture_token] = token["id"]
        return self.real[fixture_token]

    def money_calls(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in ("refund", "void", "charge")]

    def refund(self, transaction_id, amount, request_id=None):
        real = self._txn(transaction_id)
        out = (
            RailResult(False, error="404 RESOURCE_NOT_FOUND not a store transaction")
            if real is None
            else super().refund(real, amount, request_id)
        )
        self.calls.append(("refund", transaction_id, amount, real, out.id))
        return out

    def void(self, transaction_id):
        real = self._txn(transaction_id)
        out = (
            RailResult(False, error="404 RESOURCE_NOT_FOUND not a store transaction")
            if real is None
            else super().void(real)
        )
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
        return None if data is None else {**data, "id": transaction_id, "paypal_capture_id": real}
