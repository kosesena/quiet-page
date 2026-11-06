"""PayPal Agent Toolkit's `create_refund`, routed through the gate.

An agent built on the Toolkit calls `create_refund` with the Toolkit's own parameters
(typescript/src/shared/parameters.ts, createRefundParameters):
    {"capture_id": str, "amount": {"currency_code": str, "value": str}?, "invoice_id": str?, "note_to_payer": str?}
and the Toolkit POSTs that to /v2/payments/captures/{capture_id}/refund with the merchant's credentials. Here the
agent gets this function in its place: the capture id is resolved to the store's order (the order's rail
transaction id is the capture id), the call becomes Counterfoil's `refund` tool, and the gate decides. Only a PASS
(or a human approval) reaches PayPalRestRail, which makes the same REST call. The agent never holds PayPal keys.

A missing `amount` means "refund the full capture" to PayPal; the gate sees exactly that, the order total.
`rma_id` is not a Toolkit parameter; a merchant may add it to the tool schema, and it is passed on when present.
"""

from __future__ import annotations

from .gateway import BLOCK, Context, Finding, Gateway, Outcome


def create_refund(gate: Gateway, ctx: Context, params: dict) -> Outcome:
    capture_id = params.get("capture_id")
    order = next((o for o in gate.store.orders.values() if o["braintree_transaction_id"] == capture_id), None)
    if order is None:
        return Outcome(BLOCK, [Finding(BLOCK, "UNKNOWN_CAPTURE", f"{capture_id!r} is not a capture of this store")])
    amount = params.get("amount") or {"value": order["total"], "currency_code": order["currency"]}
    args = {"order_no": order["order_no"], "amount": amount.get("value"), "currency": amount.get("currency_code")}
    if params.get("rma_id"):
        args["rma_id"] = params["rma_id"]
    return gate.handle(ctx, "refund", args)
