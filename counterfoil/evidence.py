"""A tamper-evident receipt for one run: every step (email in, sandbox result, hand-off, gate decision, payment)
is appended as an entry whose hash covers its own content and the previous entry's hash. Changing any earlier
entry breaks every hash after it, so `verify()` on a downloaded receipt shows whether it was edited.

This is a hash chain, not a signature: it proves the receipt is internally consistent, not who wrote it.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field

GENESIS = "0" * 64


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


@dataclass
class Receipt:
    run_id: str
    entries: list[dict] = field(default_factory=list)

    @property
    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def add(self, step: str, data: dict) -> dict:
        body = {"i": len(self.entries), "step": step, "at": round(time.time(), 3), "data": data, "prev": self.head}
        entry = {**body, "hash": hashlib.sha256(_canonical(body)).hexdigest()}
        self.entries.append(entry)
        return entry

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, "algorithm": "sha256-chain", "head": self.head, "entries": self.entries}


def verify(receipt: dict) -> tuple[bool, int | None]:
    """→ (intact, index of the first broken entry or None)."""
    prev = GENESIS
    for i, e in enumerate(receipt.get("entries", [])):
        body = {k: e[k] for k in ("i", "step", "at", "data", "prev") if k in e}
        if e.get("prev") != prev or e.get("i") != i:
            return False, i
        if hashlib.sha256(_canonical(body)).hexdigest() != e.get("hash"):
            return False, i
        prev = e["hash"]
    return receipt.get("head", GENESIS) == prev, None if receipt.get("head", GENESIS) == prev else len(receipt["entries"])
