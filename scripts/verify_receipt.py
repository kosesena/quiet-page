#!/usr/bin/env python3
"""Check a downloaded receipt offline: the hash chain, and the Ed25519 signature against the server's public key.

    python scripts/verify_receipt.py run.receipt.json --public-key <hex from /api/public-key>
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from counterfoil.evidence import verify, verify_signature  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("receipt")
    ap.add_argument("--public-key", help="hex key from /api/public-key; without it the signature is only checked against the key the receipt carries")
    a = ap.parse_args()
    receipt = json.loads(Path(a.receipt).read_text(encoding="utf-8"))
    intact, broken = verify(receipt)
    print("chain:    ", "intact" if intact else f"BROKEN at entry {broken}")
    signed = verify_signature(receipt, a.public_key)
    print("signature:", {True: "valid", False: "INVALID", None: "none on this receipt"}[signed])
    return 0 if intact and signed is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
