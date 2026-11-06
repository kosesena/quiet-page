"""Money and quantity parsing. Values are validated, never coerced."""

from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("100000.00")


class BadAmount(ValueError):
    pass


def parse_amount(value) -> Decimal:
    """Strict: '30', '30.00' and 30 are fine; '30,00', '1e3', NaN, negatives, zero, sub-cent values,
    floats and absurdly large values are not."""
    if isinstance(value, bool) or value is None:
        raise BadAmount(f"not an amount: {value!r}")
    if isinstance(value, float):
        raise BadAmount("floats are not accepted for money; pass a string")
    text = str(value).strip()
    if not text or len(text) > 12 or any(c not in "0123456789." for c in text) or text.count(".") > 1:
        raise BadAmount(f"not a plain decimal amount: {value!r}")
    try:
        amount = Decimal(text)
        if amount <= 0:
            raise BadAmount(f"amount must be positive: {value!r}")
        if amount > MAX_AMOUNT:
            raise BadAmount(f"amount above {MAX_AMOUNT}: {value!r}")
        if amount != amount.quantize(CENT):
            raise BadAmount(f"more than two decimal places: {value!r}")
        return amount.quantize(CENT)
    except (InvalidOperation, ArithmeticError) as exc:
        raise BadAmount(f"not an amount: {value!r}") from exc


def parse_qty(value) -> int:
    """A quantity is a positive int. Not a bool, not a float, not '3'."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 1000:
        raise BadAmount(f"not a valid quantity: {value!r}")
    return value
