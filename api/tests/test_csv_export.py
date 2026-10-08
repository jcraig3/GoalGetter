"""CSV export, and the formula-injection defence that makes it safe to open."""

from datetime import UTC, datetime

import pytest

from app.csv_export import escape, filename, rows_to_csv

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def world(make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "teammate": make_user("agent", enterprise, name="Teammate"),
        "stranger": make_user("agent", make_team("SMB"), name="Stranger"),
        "metric": make_metric("calls_made"),
    }


def make_board(client, world, sign_in, **overrides):
    sign_in(world["admin"])
    response = client.post(
        "/api/leaderboards",
        json={
            "name": "Board",
            "metric_id": world["metric"].id,
            "period_type": "month",
            "visibility": "org",
            **overrides,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


# ── Formula injection ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "dangerous",
    [
        "=1+1",
        "+1234",
        "-1+1",
        "@SUM(A1)",
        "=cmd|'/c calc'!A1",
        "\t=1+1",
        "\r=1+1",
    ],
)
def test_a_cell_that_would_run_as_a_formula_is_neutralised(dangerous):
    """Excel, Sheets and LibreOffice all treat a cell starting with these as a
    formula rather than text. A person's name is user-supplied, so an export
    of one is executable content the moment a colleague opens it.

    Quoting does not help — the spreadsheet strips quotes and evaluates what is
    inside. Prefixing an apostrophe is what makes it text.
    """
    assert escape(dangerous).startswith("'")


@pytest.mark.parametrize("safe", ["Teammate", "O'Brien", "Banner, Bruce", 'A "quoted" name'])
def test_ordinary_names_are_left_alone(safe):
    """The other direction — a defence that mangles every name is worse than
    the problem."""
    assert escape(safe) == safe


def test_numbers_are_not_prefixed():
    """A negative number starts with `-`, which is a formula prefix. Prefixing
    it would turn a column of figures into a column of text nobody can sum,
    and the value is ours rather than the user's."""
    assert escape(-5) == "-5"
    assert escape(12.5) == "12.5"


def test_none_becomes_an_empty_cell():
    assert escape(None) == ""


# ── The file itself ──────────────────────────────────────────────────────────


def test_the_file_starts_with_a_byte_order_mark():
    """Without it, Excel on Windows reads the file as the local codepage and
    mangles every non-ASCII name."""
    assert "".join(rows_to_csv(["a"], [])).startswith("﻿")


def test_rows_are_yielded_progressively():
    """A generator, not one string: an export is the one endpoint that can be
    asked for every row a deployment holds."""
    chunks = list(rows_to_csv(["a", "b"], [[1, 2], [3, 4]]))
    assert len(chunks) > 2


def test_commas_and_quotes_are_escaped_by_the_csv_writer():
    output = "".join(rows_to_csv(["name"], [['Banner, Bruce'], ['A "quote"']]))
    assert '"Banner, Bruce"' in output
    assert '"A ""quote"""' in output


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Calls this month", "August 2026"), "calls-this-month-august-2026.csv"),
        (("../../etc/passwd",), "etc-passwd.csv"),
        (('a"quote', "x"), "a-quote-x.csv"),
        (("",), "export.csv"),
    ],
)
def test_the_download_filename_is_safe(parts, expected):
    """It goes into a Content-Disposition header, where a quote can break the
    header's own quoting."""
    assert filename(*parts) == expected


# ── The endpoint ─────────────────────────────────────────────────────────────


def test_exporting_a_board(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    board_id = make_board(client, world, sign_in)

    response = client.get(f"/api/leaderboards/{board_id}/results.csv?anchor=2026-08-12")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    body = response.text
    assert "Rank" in body and "Teammate" in body


def test_the_export_ignores_the_display_limit(client, db, world, make_user, make_fact, sign_in):
    """`display_limit` is a drawing decision. A truncated spreadsheet is the
    kind of thing that gets pasted into a report without anyone noticing what
    is missing."""
    for index in range(5):
        make_fact(world["metric"], make_user("agent", name=f"P{index}"), index + 1, WHEN)

    board_id = make_board(client, world, sign_in, display_limit=2)
    on_screen = client.get(
        f"/api/leaderboards/{board_id}/results?anchor=2026-08-12"
    ).json()
    exported = client.get(
        f"/api/leaderboards/{board_id}/results.csv?anchor=2026-08-12"
    ).text

    assert len(on_screen["entries"]) == 2
    # Header + 5 data rows.
    assert len([line for line in exported.strip().splitlines() if line]) == 6


def test_a_name_that_would_run_as_a_formula_is_neutralised_end_to_end(
    client, db, world, make_user, make_fact, sign_in
):
    """The whole point, through the real endpoint: a user-supplied name reaches
    the file, so the defence has to be in the path the file actually takes."""
    attacker = make_user("agent", name="=cmd|'/c calc'!A1")
    make_fact(world["metric"], attacker, 10, WHEN)

    board_id = make_board(client, world, sign_in)
    body = client.get(f"/api/leaderboards/{board_id}/results.csv?anchor=2026-08-12").text
    assert "'=cmd" in body
    assert ",=cmd" not in body


def test_the_export_obeys_the_same_visibility_rules(client, db, world, sign_in):
    """A different rendering of data they can already see, never a way around
    who may see it."""
    board_id = make_board(client, world, sign_in, visibility="private")
    sign_in(world["teammate"])
    assert client.get(f"/api/leaderboards/{board_id}/results.csv").status_code == 404


def test_an_agent_can_export_a_board_they_can_read(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["stranger"], 10, WHEN)
    board_id = make_board(client, world, sign_in)
    sign_in(world["teammate"])
    response = client.get(f"/api/leaderboards/{board_id}/results.csv?anchor=2026-08-12")
    assert response.status_code == 200
    # Every entrant, exactly as the board shows them.
    assert "Stranger" in response.text


def test_exporting_an_empty_board_gives_a_header_only(client, db, world, sign_in):
    board_id = make_board(client, world, sign_in)
    body = client.get(f"/api/leaderboards/{board_id}/results.csv").text
    assert "Rank" in body
    assert len([line for line in body.strip().splitlines() if line]) == 1
