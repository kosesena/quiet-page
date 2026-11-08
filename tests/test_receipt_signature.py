import copy

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from counterfoil.evidence import Receipt, public_key_hex, sign, verify, verify_signature


def _signed():
    key = Ed25519PrivateKey.generate()
    r = Receipt("run-1")
    r.add("gate", {"decision": "APPROVAL", "amount": "40.00"})
    r.add("human", {"decision": "refuse"})
    return sign(r.to_dict(), key), key


def test_signed_receipt_verifies():
    d, key = _signed()
    assert verify(d) == (True, None)
    assert verify_signature(d, public_key_hex(key)) is True


def test_recomputed_chain_fails_signature():
    d, key = _signed()
    forged = Receipt("run-1")
    forged.add("gate", {"decision": "PASS", "amount": "40.00"})
    forged.add("human", {"decision": "approve"})
    out = forged.to_dict()
    out["signature"] = copy.deepcopy(d["signature"])
    assert verify(out)[0] is True  # the chain alone can't catch this
    assert verify_signature(out, public_key_hex(key)) is False


def test_other_key_is_rejected():
    d, _ = _signed()
    assert verify_signature(d, public_key_hex(Ed25519PrivateKey.generate())) is False


def test_unsigned_is_none():
    assert verify_signature(Receipt("x").to_dict()) is None
