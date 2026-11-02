"""Local redaction. Runs on text before it is stored or sent to a model for extraction.

Limits, stated plainly: raw audio and images are sent to Meta's speech and vision endpoints
to be turned into text, so this cannot redact them first. It only stops identifiers in the
derived text from being stored or forwarded again.
"""
import re

_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]?\d{4}(?!\d)")


def _luhn(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        flip = not flip
    return total % 10 == 0


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Returns the redacted text and a count per category (counts only, never the values)."""
    counts = {"card": 0, "email": 0, "phone": 0}

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            counts["card"] += 1
            return "[card]"
        return m.group()

    text = _CARD.sub(card, text)

    def simple(key: str, label: str):
        def repl(_: re.Match) -> str:
            counts[key] += 1
            return label
        return repl

    text = _EMAIL.sub(simple("email", "[email]"), text)
    text = _PHONE.sub(simple("phone", "[phone]"), text)
    return text, counts
