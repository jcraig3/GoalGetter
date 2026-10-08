"""A grid of cells as records. Shared by every spreadsheet connector.

Google Sheets and Excel differ in how they authenticate and which URL they read.
They do not differ at all in what they hand back: a rectangle of cells whose first
useful row names the columns. So that part lives here once.

**This is the only transformation any connector in this codebase performs**, and it
is barely one: a spreadsheet's header row *is* its field names, where every other
source hands over named fields already. Without it the mapping step would be asking
somebody to choose between `column 3` and `column 4`.

Three details in it each exist because of a real spreadsheet rather than a
hypothetical one, and all three are tested.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.connectors import SourceField


def rows_from(values: list[list[Any]], *, header_row: int) -> list[dict[str, Any]]:
    """A rectangle of cells as records, using one row as the column names.

    **Short rows are padded, not skipped.** Both providers omit trailing empty
    cells entirely, so a row whose last two columns are blank comes back shorter
    than the header — and dropping those would silently lose every record with an
    empty note field.

    **Wholly empty rows are skipped.** That is the blank space under a table, which
    every hand-made spreadsheet has.

    **Columns with no name are dropped.** A blank header is a spare column somebody
    left beside the table; importing it as `""` gives the mapping a field nobody can
    identify.
    """
    index = max(header_row, 1) - 1
    if len(values) <= index:
        return []

    headers = [str(cell).strip() for cell in values[index]]
    out: list[dict[str, Any]] = []
    for row in values[index + 1 :]:
        record = {}
        for position, name in enumerate(headers):
            if not name:
                continue
            record[name] = row[position] if position < len(row) else ""
        if any(str(value).strip() for value in record.values()):
            out.append(record)
    return out


#: How many rows discovery looks at when deciding what a column holds.
#:
#: Five was enough to guess a *kind* and is nowhere near enough to know whether a
#: column holds three values or three hundred. Nothing extra is fetched for this —
#: a sheet arrives whole and is then thrown away — so the only cost is the scan.
SCAN_ROWS = 500

#: Past this many distinct values, a column is data rather than a choice.
#:
#: Twelve because the things worth filtering on — a pipeline stage, a region, a
#: product line, a disposition code — are all small by nature, and because a
#: dropdown longer than this is a search box somebody has to read. A column of
#: names or amounts blows past it on the first few rows and costs nothing.
MAX_CHOICES = 12


def fields_of(records: list[dict[str, Any]]) -> list[SourceField]:
    """Each column's kind, and — where there are few enough — its distinct values.

    Order is the sheet's own, left to right, because that is how somebody laid it
    out — the alphabet would open the mapping on whichever column happens to start
    with A.

    **Distinct values are collected across everything passed in**, while the kind
    and the sample still come from the first row that has one. Callers therefore
    hand this more rows than they used to: five is plenty to recognise a column
    by and nowhere near enough to know whether it holds three values or three
    hundred. Nothing extra is fetched — a sheet arrives whole.
    """
    fields: dict[str, SourceField] = {}
    # Insertion-ordered, so a dropdown lists values the way the sheet does. One
    # over the cap is kept deliberately: it is how "too many" is detected without
    # holding the whole column.
    choices: dict[str, dict[str, None]] = {}

    for record in records:
        for name, value in record.items():
            text = "" if value is None else str(value).strip()
            seen = choices.setdefault(name, {})
            if text and len(seen) <= MAX_CHOICES:
                seen[text] = None

            existing = fields.get(name)
            if existing is not None and (existing.kind != "string" or not text):
                continue
            fields[name] = SourceField(
                name=name,
                kind=kind_of(value),
                samples=() if not text else (text[:60],),
            )

    return [
        replace(
            field,
            values=(
                tuple(choices[name])
                if 0 < len(choices.get(name, {})) <= MAX_CHOICES
                else ()
            ),
        )
        for name, field in fields.items()
    ]


def kind_of(value: object) -> str:
    """What a cell looks like.

    Both providers can hand over unformatted values, so a number really is a
    number and this guesses far less than the webhook connector has to.

    **Dates are the exception, in both products.** A date cell comes back as a
    serial number indistinguishable from a quantity, so a date column in a
    spreadsheet has to hold text — `2026-08-21` rather than a date-formatted cell.
    No connector can fix that, and the field hints say so.
    """
    if isinstance(value, bool):
        # Before `int`, because `bool` is a subclass of it and a tick-box column
        # reported as a number is one the mapper offers to sum.
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        if "@" in value:
            return "email"
        from app.mapping import _number, _parse_datetime

        if _parse_datetime(value) is not None:
            return "date"
        if _number(value) is not None:
            return "number"
    return "string"
