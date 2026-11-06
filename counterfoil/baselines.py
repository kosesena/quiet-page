"""Comparison conditions for the evaluation. Same interface as Gateway.handle, but no Counterfoil logic at all:
no store state, no reservations, no duplicate-charge memory. The call goes to the rail as the agent made it.

- NoGate: nothing between agent and rail (the rail's own rules still apply).
- CapGate: a tool allowlist plus a per-transaction cap, the kind of guard most agent-payment projects ship
  (see docs/arastirma/2026-10-23-rakipler.md). Above the cap → held for a human.
"""

from __future__ import annotations

from decimal import Decimal

from .gateway import APPROVAL, BLOCK, PASS, Context, Finding, Gateway, Outcome
from .money import BadAmount, parse_amount
from .views import order_view

RAIL_TOOLS = {"refund", "charge", "void", "lookup_transaction"}


class NoGate(Gateway):
    def check(self, ctx: Context, tool: str, args: dict) -> list[Finding]:
        if tool not in RAIL_TOOLS:
            return [Finding(BLOCK, "NO_SUCH_TOOL", f"the rail has no '{tool}' endpoint")]
        try:
            if tool in ("refund", "charge"):
                parse_amount(args.get("amount"))  # the rail would reject a malformed amount too
        except BadAmount as exc:
            return [Finding(BLOCK, "BAD_AMOUNT", str(exc))]
        return []

    def _execute(self, ctx, tool, args, findings, approved=None) -> Outcome:
        decision = APPROVAL if approved else PASS
        order = self.store.orders.get(str(args.get("order_no", "")), {})
        txn = args.get("braintree_transaction_id") or order.get("braintree_transaction_id")
        if tool == "lookup_transaction":
            if order:
                return Outcome(
                    decision, findings, "succeeded", data=order_view(self.store, self.rail, order["order_no"])
                )
            data = self.rail.find(txn)
            return Outcome(decision, findings, "succeeded" if data else "failed", data=data)
        if tool == "refund":
            return self._call(decision, findings, lambda: self.rail.refund(txn, parse_amount(args["amount"])))
        if tool == "void":
            return self._call(decision, findings, lambda: self.rail.void(txn))
        return self._call(
            decision,
            findings,
            lambda: self.rail.charge(
                args.get("vaulted_payment_method_token"), parse_amount(args["amount"]), f"{ctx.session_id}:charge"
            ),
        )


class CapGate(NoGate):
    def __init__(self, store, rail, cap: Decimal = Decimal("200.00"), **kw):
        super().__init__(store, rail, **kw)
        self.cap = cap

    def check(self, ctx: Context, tool: str, args: dict) -> list[Finding]:
        if tool not in ctx.allowed_tools:
            return [Finding(BLOCK, "TOOL_NOT_ALLOWED", tool)]
        findings = super().check(ctx, tool, args)
        if findings:
            return findings
        if tool in ("refund", "charge") and parse_amount(args.get("amount")) > self.cap:
            return [Finding(APPROVAL, "OVER_CAP", f"{args.get('amount')} > {self.cap}")]
        return []


__all__ = ["NoGate", "CapGate", "PASS", "APPROVAL", "BLOCK"]
