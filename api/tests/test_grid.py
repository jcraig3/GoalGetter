"""A grid of cells as records — the transform every spreadsheet connector shares.

Google Sheets and Excel differ in how they sign in and which URL they read. They do
not differ at all in this, so it is tested once here rather than twice badly.

Getting it wrong is never a crash. It is a mapping offered `column 3` instead of
`Amount`, or a row silently missing because its last cell was empty — which is why
each of the three awkward cases below names the real spreadsheet it comes from.
"""

from app.connectors.grid import fields_of, kind_of, rows_from

GRID = [
    ["Deal id", "Owner", "Amount", "Closed"],
    ["OPP-1", "alice@acme.example", 1200.5, "2026-08-20"],
    ["OPP-2", "bob@acme.example", 900, "2026-08-19"],
]


# ── The header row becomes the field names ───────────────────────────────────


def test_the_header_row_names_the_fields():
    """**The one transformation any connector here performs**, and without it the
    mapping would be choosing between `column 3` and `column 4`."""
    assert rows_from(GRID, header_row=1) == [
        {
            "Deal id": "OPP-1",
            "Owner": "alice@acme.example",
            "Amount": 1200.5,
            "Closed": "2026-08-20",
        },
        {
            "Deal id": "OPP-2",
            "Owner": "bob@acme.example",
            "Amount": 900,
            "Closed": "2026-08-19",
        },
    ]


def test_a_header_further_down_is_honoured():
    """A sheet with a title and a blank line above the table, which is most sheets
    anybody has formatted by hand."""
    grid = [["Q3 closed deals"], [], ["Owner", "Amount"], ["a@b.c", 5]]

    assert rows_from(grid, header_row=3) == [{"Owner": "a@b.c", "Amount": 5}]


def test_a_short_row_is_padded_rather_than_dropped():
    """**Google omits trailing empty cells entirely**, so a row whose last column is
    blank comes back shorter than the header. Dropping those would silently lose
    every row with an empty note field."""
    grid = [["Owner", "Amount", "Note"], ["a@b.c", 5]]

    assert rows_from(grid, header_row=1) == [
        {"Owner": "a@b.c", "Amount": 5, "Note": ""}
    ]


def test_a_wholly_empty_row_is_not_a_record():
    """The blank space under a table, which every sheet has."""
    grid = [["Owner", "Amount"], ["a@b.c", 5], ["", ""], []]

    assert len(rows_from(grid, header_row=1)) == 1


def test_a_column_with_no_name_is_dropped():
    """A spare column beside the table. Importing it as `""` gives the mapping a
    field nobody can identify."""
    grid = [["Owner", "", "Amount"], ["a@b.c", "scratch", 5]]

    assert rows_from(grid, header_row=1) == [{"Owner": "a@b.c", "Amount": 5}]


def test_headers_are_trimmed():
    """A header typed as "Owner " with a trailing space would otherwise name a field
    "Owner ", which the mapping shows as a subtly different column and nobody can
    see the difference."""
    grid = [["  Owner ", "Amount  "], ["a@b.c", 5]]

    assert rows_from(grid, header_row=1) == [{"Owner": "a@b.c", "Amount": 5}]


def test_a_header_row_past_the_end_of_the_sheet_is_empty_not_an_error():
    assert rows_from([["Owner"]], header_row=9) == []


def test_a_header_row_of_zero_is_read_as_the_first():
    """Nobody counts rows from zero in a spreadsheet, so this is a typo rather than
    an instruction — and reading row -1 would be worse than assuming row 1."""
    assert rows_from(GRID, header_row=0) == rows_from(GRID, header_row=1)


# ── Kinds ────────────────────────────────────────────────────────────────────


def test_a_boolean_is_not_a_number():
    """`bool` is a subclass of `int` in Python, so an unguarded check calls a
    tick-box column a number and the mapper offers to sum it."""
    assert kind_of(True) == "boolean"
    assert kind_of(1) == "number"


def test_an_unformatted_number_really_is_a_number():
    """Both providers can hand over raw values, which is why this guesses far less
    than the webhook connector has to."""
    assert kind_of(1250.5) == "number"


def test_a_formatted_number_is_still_a_number():
    assert kind_of("1,250.50") == "number"


def test_an_address_is_an_email():
    assert kind_of("sam@example.test") == "email"


def test_a_written_date_is_a_date():
    """Which is the only kind of date a spreadsheet can offer: a *formatted* date
    cell comes back as a serial number indistinguishable from a quantity."""
    assert kind_of("2026-08-21") == "date"


def test_anything_else_is_text():
    assert kind_of("closed by phone") == "string"
    assert kind_of(None) == "string"


def test_a_column_is_typed_from_the_first_row_that_has_a_value():
    found = fields_of([{"Amount": ""}, {"Amount": 1250}])

    assert [(f.name, f.kind) for f in found] == [("Amount", "number")]


def test_columns_keep_the_order_of_the_sheet():
    """Left to right, as somebody laid it out — the alphabet would open the mapping
    on whichever column happens to start with A."""
    found = fields_of([{"Zebra": 1, "Apple": 2}])

    assert [f.name for f in found] == ["Zebra", "Apple"]


def test_a_sample_is_offered_for_a_column_that_has_one():
    found = fields_of([{"Owner": "sam@example.test"}])

    assert found[0].samples == ("sam@example.test",)


def test_no_sample_is_invented_for_an_empty_column():
    found = fields_of([{"Note": ""}])

    assert found[0].samples == ()
