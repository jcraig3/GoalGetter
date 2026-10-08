"""Turning a source row into a fact, or deciding it is not one.

Pure functions over dictionaries, with no database and no connector in sight.
That is deliberate: this is where the fiddly work lives — comparing a string
`"100"` against a number, reading a date that arrived without a timezone — and
none of it should need a Postgres container or a Salesforce account to test.

**The connector's job is to hand over rows. Everything a row goes through
afterwards happens here**, once, so that seven connectors cannot each get filters
subtly wrong in their own private way.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MappingError(ValueError):
    """A row cannot become a fact, and the reason is worth telling somebody.

    Distinct from "this row was filtered out", which is a normal outcome and not
    an error. This is a date that will not parse or a value that is not a number —
    a mapping pointed at the wrong column, which an admin can fix once the sync
    tells them which column and what it contained.
    """


#: What a filter can ask of a column.
#:
#: Deliberately small. These cover "only closed-won deals" and "only this
#: pipeline", which is what filters are for. Anything needing more is asking for an
#: expression language, which `SourceMapping.multiplier` exists to avoid.
#:
#: Defined here rather than on the model: this module is what enforces them, and a
#: list living apart from its implementation is a list that drifts.
FILTER_OPS = ("eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "contains")


# ── Filters ──────────────────────────────────────────────────────────────────


def _as_comparable(left: object, right: object) -> tuple[object, object]:
    """Coerce a pair so comparing them means something.

    Sources are careless about types. A spreadsheet column of amounts arrives as
    strings; a JSON payload sends the same field as a number. A filter written as
    `Amount > 100` must work either way, so a numeric-looking pair is compared as
    numbers and everything else as case-folded strings.

    Case folding is the right default for the string case: `Stage = "closed won"`
    matching `"Closed Won"` is what somebody means every time. A filter that has
    to distinguish case is not a filter anybody has asked for.
    """
    for parse in (_number, None):
        if parse is None:
            break
        pair = (parse(left), parse(right))
        if pair[0] is not None and pair[1] is not None:
            return pair
    return (str(left).strip().casefold(), str(right).strip().casefold())


def _number(value: object) -> Decimal | None:
    """`value` as a Decimal, or None if it is not numeric.

    Via `str()` for floats, always. `Decimal(0.1)` is
    0.1000000000000000055511151231257827, because that is what the float actually
    is; `Decimal("0.1")` is a tenth. Money reaches this function, so the
    difference is not academic.
    """
    if isinstance(value, bool):
        # Python says a bool is an int. A filter comparing True to 1 is a mapping
        # mistake, not an arithmetic one, so refuse rather than agree.
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        # Currency symbols and thousands separators are what a spreadsheet
        # export looks like. Stripping them here beats making every admin clean
        # their data first.
        for symbol in ("$", "£", "€"):
            text = text.replace(symbol, "")
        if text.startswith("(") and text.endswith(")"):
            # Accounting negatives: (1,200) means -1200.
            text = "-" + text[1:-1]
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    return None


def matches(row: dict[str, object], filters: list[dict]) -> bool:
    """Whether this row passes every filter.

    **AND, not a boolean tree.** "Closed-won deals in the enterprise pipeline" is
    every filter anyone has actually described, and OR groups are the first step
    towards the expression language this deliberately is not.

    A filter naming a column the row does not have fails closed — the row is
    excluded. The alternative is importing everything when somebody mistypes a
    column name, which is the more expensive way to be wrong.
    """
    for rule in filters:
        field = rule.get("field")
        op = rule.get("op", "eq")
        wanted = rule.get("value")

        if field not in row:
            return False
        actual = row[field]

        if not _passes(actual, op, wanted):
            return False
    return True


def _passes(actual: object, op: str, wanted: object) -> bool:
    if op in ("in", "not_in"):
        # Membership compares against each candidate with the same coercion the
        # scalar operators use, so `Stage in ["Closed Won"]` behaves like
        # `Stage = "Closed Won"`.
        options = wanted if isinstance(wanted, (list, tuple)) else [wanted]
        hit = any(_passes(actual, "eq", option) for option in options)
        return hit if op == "in" else not hit

    if op == "contains":
        return str(wanted).strip().casefold() in str(actual).strip().casefold()

    left, right = _as_comparable(actual, wanted)

    if op == "eq":
        return left == right
    if op == "ne":
        return left != right

    # Ordering only means something for numbers. Comparing dates as strings
    # happens to work for ISO-8601 and breaks silently for anything else, so
    # ordering operators are numeric-only and say so.
    if not isinstance(left, Decimal) or not isinstance(right, Decimal):
        raise MappingError(
            f"Cannot compare {actual!r} to {wanted!r} with '{op}' — "
            "greater-than and less-than need numbers on both sides."
        )
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right

    raise MappingError(f"Unknown filter operator {op!r}.")


# ── The value ────────────────────────────────────────────────────────────────


def value_of(
    row: dict[str, object],
    value_field: str | None,
    multiplier: Decimal = Decimal(1),
) -> Decimal:
    """What this row measures.

    `value_field` of None means **count the row as one**, which is how a "deals
    won" metric works: the fact that a row exists *is* the measurement. Without
    that, every count metric would need a column of literal 1s in the source.

    An empty cell counts as zero rather than failing. A spreadsheet with gaps in
    an amount column is normal, and refusing the whole sync over one blank cell
    would be the wrong trade — a zero is visible in the totals and a failed sync
    is not.
    """
    if value_field is None:
        return Decimal(1) * multiplier

    if value_field not in row:
        raise MappingError(f"The mapping expects a column named {value_field!r}.")

    raw = row[value_field]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return Decimal(0)

    number = _number(raw)
    if number is None:
        raise MappingError(
            f"{value_field!r} contained {raw!r}, which is not a number."
        )
    return number * multiplier


# ── The date ─────────────────────────────────────────────────────────────────

#: Formats tried in order, after ISO-8601.
#:
#: Deliberately short. Every entry is a real export format; the temptation is to
#: add "just one more" until the parser guesses wrong on an ambiguous date and
#: puts six months of revenue in the wrong quarter.
DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%d %B %Y",
    "%B %d, %Y",
)


def occurred_at(
    row: dict[str, object],
    field: str | None,
    *,
    source_timezone: str | None,
    org_timezone: str,
) -> datetime | None:
    """When this row happened, as an instant — or `None` when the source has no date.

    **`None` is an answer, not a failure.** A mapping with no date column says the
    source cannot tell us when anything happened, and the fact is dated by when its
    number last changed instead. That decision needs the *previous* value, which
    only `sync._upsert` can see, so this function says "no date here" and leaves it
    alone.

    **A bare date is not an instant**, and this is the function where that matters.
    Period boundaries are resolved in the organization's timezone, so a
    spreadsheet exported in Sydney and read in Phoenix would land a deal on the
    wrong day — and for a daily goal, in the wrong period entirely. A value with no
    zone is therefore interpreted in the *source's* timezone, falling back to the
    organization's, and converted to UTC before it is stored.

    A date with no time becomes midnight in that zone. Not noon, not "now":
    midnight is what every other part of this product means by a date, and a
    half-open period window `[start, end)` includes it exactly once.
    """
    if not field:
        return None

    if field not in row:
        raise MappingError(f"The mapping expects a column named {field!r}.")

    raw = row[field]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise MappingError(
            f"{field!r} was empty. A fact with no date cannot be put in a period."
        )

    parsed = _parse_datetime(raw)
    if parsed is None:
        raise MappingError(
            f"{field!r} contained {raw!r}, which is not a date this understands."
        )

    if parsed.tzinfo is not None:
        # The source said which zone it meant. Believe it.
        return parsed.astimezone(timezone.utc)

    zone = _zone(source_timezone) or _zone(org_timezone) or timezone.utc
    return parsed.replace(tzinfo=zone).astimezone(timezone.utc)


def _parse_datetime(raw: object) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        # A `date` is midnight, and carries no zone — the caller applies one.
        return datetime(raw.year, raw.month, raw.day)
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    # ISO first, and `fromisoformat` in 3.11+ handles the trailing Z that every
    # JSON API sends and that older Python refused.
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # A source configured with a typo'd timezone must not stop the sync. It
        # falls through to the organization's, which is the safer wrong answer of
        # the two available.
        return None


# ── The source's own id for the row ──────────────────────────────────────────


def external_id_of(row: dict[str, object], field: str | None) -> str | None:
    """The source's stable identifier for this row, if it has one.

    This is what makes a sync idempotent: re-reading yesterday's deals writes
    nothing new because these ids are already present. Returning None means the
    sync has to fall back to synthesising one — see `app/sync.py` for why that is
    a worse position to be in.
    """
    if field is None or field not in row:
        return None
    raw = row[field]
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None
