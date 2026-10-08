"""What a count is a count *of*: "48,210 deals", not a bare 48,210 (§8).

A currency figure carries its "$" and a percentage its "%", so a count was
the one number on a wall that did not say what it was. A metric now has an
optional label for that, written as the plural ("deals", "calls", "tickets")
because that is the form nearly every value takes. The same rule is in
`web/src/components/MetricValue.tsx`; the two must agree.
"""

from __future__ import annotations

from decimal import Decimal

#: Long enough for "support tickets", short enough to sit after a number on
#: a wall without wrapping it.
MAX_LABEL = 32


def clean(label: str | None) -> str | None:
    """As stored: trimmed, and nothing rather than an empty string."""
    if label is None:
        return None
    label = " ".join(label.split())
    return label or None


def singular(label: str) -> str:
    """"deals" → "deal", "replies" → "reply", "glasses" → "glass"; "NPS" stays.

    Derived rather than asked for: one field is less to fill in, and these
    cases cover the nouns a sales floor counts. Something irregular reads
    "1 people" at worst, which is the price of not asking twice. An acronym is
    left alone — its S is rarely a plural.
    """
    lower = label.lower()
    if label.isupper():
        return label
    if lower.endswith("ies") and len(label) > 3:
        return label[:-3] + "y"
    if lower.endswith("sses"):
        return label[:-2]
    if lower.endswith("ss") or not lower.endswith("s"):
        return label
    return label[:-1]


def noun(label: str, value: Decimal | float | int) -> str:
    """The label in the form this value takes: "1 deal", "0 deals", "1.5 deals"."""
    return singular(label) if value == 1 else label


def with_noun(text: str, value, unit: str, label: str | None) -> str:
    """A formatted number with its noun, when it has one and is a count."""
    if unit != "count" or not label:
        return text
    return f"{text} {noun(label, value)}"
