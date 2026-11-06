"""What a lookup returns to the transaction agent. Shared by every condition (Counterfoil and baselines), so the
agent gets the same information everywhere; only whether the lookup is allowed differs."""

from __future__ import annotations


def order_view(store, rail, order_no: str) -> dict:
    o = store.orders[order_no]
    returns = []
    for r in o.get("returns", []):
        returns.append(
            {
                "rma_id": r["rma_id"],
                "items": r["items"],
                "approved_refund_amount": r["approved_refund_amount"],
                "status": r["status"],
            }
        )
    customer = store.customers.get(o["customer_id"], {})
    return {
        "order_no": o["order_no"],
        "braintree_transaction_id": o["braintree_transaction_id"],
        "items": o["items"],
        "total": o["total"],
        "currency": o["currency"],
        "payment_method_type": o["payment_method_type"],
        "status": o["status"],
        "returns": returns,
        "refunds": [
            {"amount": a, "status": s, "rma_id": rma}
            for a, s, rma in store.sql("SELECT amount, status, rma_id FROM refunds WHERE order_no=?", (order_no,))
        ],
        "vaulted_payment_methods": [
            {"token": m["token"], "type": m["type"]} for m in customer.get("vaulted_payment_methods", [])
        ],
        "rail": rail.find(o["braintree_transaction_id"]),
    }
