"""Turning a source row into a fact.

Pure functions, no database. This is where the fiddly work lives — comparing a
string `"100"` to a number, reading a date that arrived without a timezone — and
most of the tests below are about a source being careless in a way a person would
not notice until a leaderboard was wrong.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app import mapping
from app.mapping import MappingError

PHOENIX = "America/Phoenix"
SYDNEY = "Australia/Sydney"


# ── Filters ──────────────────────────────────────────────────────────────────


def test_no_filters_lets_everything_through():
    assert mapping.matches({"Stage": "Open"}, []) is True


def test_equality_ignores_case_and_padding():
    """`Stage = "closed won"` matching `"Closed Won"` is what somebody means every
    single time. A filter that has to distinguish case is not one anybody has
    asked for."""
    row = {"Stage": "  Closed Won  "}
    assert mapping.matches(row, [{"field": "Stage", "op": "eq", "value": "closed won"}])


def test_a_string_and_a_number_compare_as_numbers():
    """The same field arrives as `"100"` from a spreadsheet and `100` from JSON. A
    filter must not care which."""
    assert mapping.matches({"Amount": "100"}, [{"field": "Amount", "op": "eq", "value": 100}])
    assert mapping.matches({"Amount": 100}, [{"field": "Amount", "op": "eq", "value": "100"}])


def test_ordering_operators():
    row = {"Amount": "250.50"}
    assert mapping.matches(row, [{"field": "Amount", "op": "gt", "value": 250}])
    assert mapping.matches(row, [{"field": "Amount", "op": "gte", "value": "250.50"}])
    assert mapping.matches(row, [{"field": "Amount", "op": "lt", "value": 300}])
    assert not mapping.matches(row, [{"field": "Amount", "op": "lt", "value": 200}])


def test_ordering_on_non_numbers_is_refused_rather_than_guessed():
    """Comparing dates as strings happens to work for ISO-8601 and breaks silently
    for everything else. Better to say so than to be right by luck."""
    with pytest.raises(MappingError, match="need numbers"):
        mapping.matches(
            {"Stage": "Open"}, [{"field": "Stage", "op": "gt", "value": "Closed"}]
        )


def test_in_and_not_in():
    row = {"Stage": "Closed Won"}
    assert mapping.matches(row, [{"field": "Stage", "op": "in", "value": ["Closed Won", "Won"]}])
    assert not mapping.matches(row, [{"field": "Stage", "op": "not_in", "value": ["Closed Won"]}])
    # And membership folds case the same way equality does, rather than being a
    # second, stricter comparison.
    assert mapping.matches(row, [{"field": "Stage", "op": "in", "value": ["closed won"]}])


def test_in_accepts_a_bare_value_not_only_a_list():
    """A UI that sends a single selection as a scalar should not produce a filter
    that silently matches nothing."""
    assert mapping.matches({"Stage": "Won"}, [{"field": "Stage", "op": "in", "value": "Won"}])


def test_contains():
    row = {"Name": "Acme Corporation"}
    assert mapping.matches(row, [{"field": "Name", "op": "contains", "value": "corp"}])
    assert not mapping.matches(row, [{"field": "Name", "op": "contains", "value": "zzz"}])


def test_every_filter_must_pass():
    row = {"Stage": "Closed Won", "Amount": 50}
    rules = [
        {"field": "Stage", "op": "eq", "value": "Closed Won"},
        {"field": "Amount", "op": "gte", "value": 100},
    ]
    assert not mapping.matches(row, rules)


def test_a_missing_column_fails_closed():
    """The alternative is importing everything when somebody mistypes a column
    name, which is the more expensive way to be wrong."""
    assert not mapping.matches({"Stage": "Won"}, [{"field": "Stge", "op": "eq", "value": "Won"}])


def test_an_unknown_operator_is_an_error_not_a_pass():
    with pytest.raises(MappingError, match="Unknown filter operator"):
        mapping.matches({"A": 1}, [{"field": "A", "op": "approximately", "value": 1}])


def test_a_boolean_is_not_a_number():
    """Python says `True == 1`. A filter comparing them is a mapping mistake, so
    it compares as strings and fails rather than agreeing."""
    assert not mapping.matches({"Won": True}, [{"field": "Won", "op": "eq", "value": 1}])


# ── Money as a source actually sends it ──────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1200", Decimal(1200)),
        ("1,200", Decimal(1200)),
        ("$1,200.50", Decimal("1200.50")),
        ("£99", Decimal(99)),
        ("€1.500", Decimal("1.500")),
        ("(1,200)", Decimal(-1200)),  # accounting negative
        ("  42  ", Decimal(42)),
        (1200, Decimal(1200)),
        (Decimal("7.25"), Decimal("7.25")),
    ],
)
def test_amounts_a_spreadsheet_export_produces(raw, expected):
    """Stripping symbols and separators here beats asking every admin to clean
    their data first."""
    assert mapping.value_of({"Amount": raw}, "Amount") == expected


def test_a_float_does_not_pick_up_binary_noise():
    """`Decimal(0.1)` is 0.1000000000000000055…, because that is what the float
    is. Money reaches this function, so it goes through `str()` first."""
    assert mapping.value_of({"Amount": 0.1}, "Amount") == Decimal("0.1")


# ── The value ────────────────────────────────────────────────────────────────


def test_no_value_field_counts_the_row_as_one():
    """How a "deals won" metric works: the fact that a row exists *is* the
    measurement. Without this, every count metric needs a column of literal 1s."""
    assert mapping.value_of({"anything": "at all"}, None) == Decimal(1)


def test_the_multiplier_scales_it():
    """Money stored in cents, or a commission share — the two real cases, and the
    reason there is no expression language."""
    assert mapping.value_of({"Cents": 12345}, "Cents", Decimal("0.01")) == Decimal("123.45")
    assert mapping.value_of({"Amount": 1000}, "Amount", Decimal("0.7")) == Decimal(700)


def test_the_multiplier_applies_to_a_counted_row_too():
    assert mapping.value_of({}, None, Decimal(5)) == Decimal(5)


def test_an_empty_cell_is_zero_not_a_failure():
    """A spreadsheet with gaps in an amount column is normal. A zero is visible in
    the totals; a failed sync is not."""
    assert mapping.value_of({"Amount": ""}, "Amount") == Decimal(0)
    assert mapping.value_of({"Amount": None}, "Amount") == Decimal(0)


def test_a_non_numeric_value_says_what_it_found():
    with pytest.raises(MappingError, match="not a number"):
        mapping.value_of({"Amount": "roughly ten"}, "Amount")


def test_a_missing_value_column_names_itself():
    with pytest.raises(MappingError, match="Amount"):
        mapping.value_of({"Other": 1}, "Amount")


# ── The date ─────────────────────────────────────────────────────────────────


def test_an_iso_instant_is_believed():
    got = mapping.occurred_at(
        {"When": "2026-08-07T15:30:00+00:00"}, "When",
        source_timezone=SYDNEY, org_timezone=PHOENIX,
    )
    assert got == datetime(2026, 8, 7, 15, 30, tzinfo=UTC)


def test_a_trailing_z_is_accepted():
    """Every JSON API sends it."""
    got = mapping.occurred_at(
        {"When": "2026-08-07T15:30:00Z"}, "When",
        source_timezone=None, org_timezone=PHOENIX,
    )
    assert got == datetime(2026, 8, 7, 15, 30, tzinfo=UTC)


def test_a_bare_date_uses_the_source_timezone():
    """**The reason this function exists.**

    A spreadsheet exported in Sydney and read in Phoenix would otherwise land a
    deal on the wrong day — and for a daily goal, in the wrong period entirely.
    """
    got = mapping.occurred_at(
        {"When": "2026-08-07"}, "When",
        source_timezone=SYDNEY, org_timezone=PHOENIX,
    )

    # Midnight in Sydney is the previous afternoon in UTC.
    assert got == datetime(2026, 8, 6, 14, 0, tzinfo=UTC)
    assert got.astimezone(ZoneInfo(SYDNEY)).date() == date(2026, 8, 7)


def test_without_a_source_timezone_the_organization_decides():
    got = mapping.occurred_at(
        {"When": "2026-08-07"}, "When",
        source_timezone=None, org_timezone=PHOENIX,
    )
    assert got == datetime(2026, 8, 7, 7, 0, tzinfo=UTC)  # Phoenix is UTC-7
    assert got.astimezone(ZoneInfo(PHOENIX)).date() == date(2026, 8, 7)


def test_a_bare_date_becomes_midnight_not_noon():
    """Midnight is what every other part of this product means by a date, and a
    half-open window `[start, end)` includes it exactly once."""
    got = mapping.occurred_at(
        {"When": "2026-08-07"}, "When",
        source_timezone="UTC", org_timezone="UTC",
    )
    assert got == datetime(2026, 8, 7, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "bad",
    [
        # Raises ZoneInfoNotFoundError.
        "Mars/Olympus_Mons",
        "UTC ",
        # Raises ValueError instead, which is a different except clause — and
        # both are reachable by a plausible paste. An earlier version of this test
        # only covered the first kind, so a mutation narrowing the catch survived.
        "/etc/localtime",
        "../../etc/passwd",
    ],
)
def test_a_bad_source_timezone_falls_back_rather_than_failing(bad):
    """A configuration mistake must not stop a sync. Falling through to the
    organization's zone is the safer of the two available wrong answers."""
    got = mapping.occurred_at(
        {"When": "2026-08-07"}, "When",
        source_timezone=bad, org_timezone=PHOENIX,
    )
    assert got == datetime(2026, 8, 7, 7, 0, tzinfo=UTC)


def test_a_bad_organization_timezone_falls_back_to_utc():
    """Both zones unusable is not a reason to lose the row."""
    got = mapping.occurred_at(
        {"When": "2026-08-07"}, "When",
        source_timezone="/etc/localtime", org_timezone="Nowhere/Fictional",
    )
    assert got == datetime(2026, 8, 7, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw",
    [
        "2026-08-07 15:30:00",
        "2026-08-07 15:30",
        "2026/08/07",
        "08/07/2026",
        "7 August 2026",
        "August 7, 2026",
    ],
)
def test_formats_real_exports_produce(raw):
    got = mapping.occurred_at(
        {"When": raw}, "When", source_timezone="UTC", org_timezone="UTC"
    )
    assert got.date() == date(2026, 8, 7)


def test_a_python_date_or_datetime_is_accepted():
    """A connector reading a typed source — a database, a parsed spreadsheet —
    hands over real objects rather than strings."""
    assert mapping.occurred_at(
        {"When": date(2026, 8, 7)}, "When", source_timezone="UTC", org_timezone="UTC"
    ) == datetime(2026, 8, 7, tzinfo=UTC)

    aware = datetime(2026, 8, 7, 12, tzinfo=ZoneInfo(SYDNEY))
    assert mapping.occurred_at(
        {"When": aware}, "When", source_timezone=None, org_timezone="UTC"
    ) == aware.astimezone(UTC)


def test_an_empty_date_is_refused():
    """A fact with no date cannot be put in a period, so there is nothing sensible
    to do but say so."""
    with pytest.raises(MappingError, match="empty"):
        mapping.occurred_at(
            {"When": ""}, "When", source_timezone="UTC", org_timezone="UTC"
        )


def test_an_unparseable_date_says_what_it_found():
    with pytest.raises(MappingError, match="last tuesday"):
        mapping.occurred_at(
            {"When": "last tuesday"}, "When", source_timezone="UTC", org_timezone="UTC"
        )


def test_a_missing_date_column_names_itself():
    with pytest.raises(MappingError, match="Closed"):
        mapping.occurred_at(
            {"Other": 1}, "Closed", source_timezone="UTC", org_timezone="UTC"
        )


# ── The source's own row id ──────────────────────────────────────────────────


def test_the_external_id_is_read_as_text():
    """Stored as text because sources disagree about whether an id is a number —
    and `1042` and `"1042"` must be the same row on the next sync."""
    assert mapping.external_id_of({"Id": 1042}, "Id") == "1042"
    assert mapping.external_id_of({"Id": "  abc-9 "}, "Id") == "abc-9"


def test_no_id_field_means_none():
    assert mapping.external_id_of({"Id": 1}, None) is None
    assert mapping.external_id_of({"Other": 1}, "Id") is None
    assert mapping.external_id_of({"Id": None}, "Id") is None
    assert mapping.external_id_of({"Id": "   "}, "Id") is None
