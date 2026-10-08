"""Turning rows into a CSV file a spreadsheet will open safely.

The interesting part is not the commas.

A cell whose text begins with `=`, `+`, `-`, or `@` is treated by Excel, Google
Sheets, and LibreOffice as a **formula**, not text. A person named
`=cmd|'/c calc'!A1` — or, far more realistically, an imported account name that
someone chose — becomes executable content the moment a colleague opens the
export. That is CSV injection, and it is a real vulnerability class in every
product that exports user-supplied strings.

Quoting does not help: the spreadsheet strips the quotes and evaluates what is
inside. The fix is to make the cell start with something else.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator
from typing import Any

# Characters a spreadsheet treats as the start of a formula. Tab and carriage
# return are here because some versions skip leading whitespace before deciding.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def escape(value: Any) -> str:
    """Make a cell safe to open in a spreadsheet.

    A leading apostrophe is the conventional fix: spreadsheets read it as
    "treat the rest as text" and do not display it. Numbers are passed through
    untouched — they are ours, not the user's, and prefixing them would turn a
    column of figures into a column of text nobody can sum.
    """
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)

    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def rows_to_csv(header: list[str], rows: Iterable[Iterable[Any]]) -> Iterator[str]:
    """Yield a CSV a chunk at a time.

    A generator rather than one big string: an export is the one endpoint that
    can be asked for every row a deployment holds, and building that in memory
    first is how a single request takes the process down.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    def flush() -> str:
        text = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return text

    # A UTF-8 BOM, because Excel on Windows otherwise reads the file as the
    # local codepage and mangles every non-ASCII name in it.
    yield "﻿"

    writer.writerow(header)
    yield flush()

    for row in rows:
        writer.writerow([escape(cell) for cell in row])
        yield flush()


def filename(*parts: str) -> str:
    """A safe download filename built from untrusted pieces.

    Anything that is not a letter, digit, dash, or underscore becomes a dash.
    A board named `../../etc/passwd` or one containing a quote would otherwise
    end up in a `Content-Disposition` header, where it can break the header's
    own quoting.
    """
    slug = "-".join(re.sub(r"[^A-Za-z0-9]+", "-", part).strip("-") for part in parts if part)
    return (slug or "export").lower()[:80] + ".csv"
