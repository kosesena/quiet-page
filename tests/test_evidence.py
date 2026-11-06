import copy

from counterfoil.evidence import Receipt, verify


def _receipt():
    r = Receipt("run-1")
    r.add("email", {"from": "reader@example.com", "sha256": "ab" * 32})
    r.add("sandbox", {"events": ["network_denied"]})
    r.add("gate", {"decision": "APPROVAL", "field": "amount", "asked": "490.00", "record": "49.00"})
    return r.to_dict()


def test_an_untouched_receipt_verifies():
    assert verify(_receipt()) == (True, None)


def test_editing_an_earlier_entry_is_detected_at_that_entry():
    r = _receipt()
    r["entries"][1]["data"]["events"] = []
    assert verify(r) == (False, 1)


def test_dropping_the_last_entry_is_detected():
    r = _receipt()
    cut = copy.deepcopy(r)
    cut["entries"].pop()
    assert verify(cut)[0] is False


def test_reordering_is_detected():
    r = _receipt()
    r["entries"][0], r["entries"][1] = r["entries"][1], r["entries"][0]
    assert verify(r)[0] is False
