"""What a person sees when something they typed is refused.

The client shows the first message in a 422, so it has to be a sentence that
names the field — not "String should have at least 1 character".
"""

import pytest

from app.validation import plain


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


@pytest.mark.parametrize("path", ["/api/offices", "/api/teams"])
def test_a_name_of_spaces_is_refused_and_says_so(client, admin, path):
    """QA-5: "   " passed `min_length=1` and saved a blank card."""
    reply = client.post(path, json={"name": "   "})

    assert reply.status_code == 422
    assert reply.json()["detail"][0]["msg"] == "Name can't be empty."


def test_a_name_is_saved_without_the_spaces_around_it(client, admin):
    created = client.post("/api/offices", json={"name": "  Phoenix  "}).json()

    assert created["name"] == "Phoenix"


def test_a_goal_named_with_spaces_has_no_name(client, db, admin, make_metric):
    """Its title then falls back to whose it is — rather than a blank heading."""
    metric = make_metric()
    created = client.post(
        "/api/goals",
        json={
            "metric_id": metric.id,
            "subject_type": "organization",
            "target_value": "100",
            "period_type": "month",
            "name": "   ",
        },
    ).json()

    assert created["name"] is None


@pytest.mark.parametrize(
    ("error", "said"),
    [
        ({"type": "missing", "loc": ("body", "name"), "msg": "Field required"}, "Name is required."),
        (
            {"type": "string_too_long", "loc": ("body", "name"), "msg": "x", "ctx": {"max_length": 120}},
            "Name can be at most 120 characters.",
        ),
        (
            {"type": "greater_than_equal", "loc": ("body", "row_count"), "msg": "x", "ctx": {"ge": 1}},
            "Row count has to be at least 1.",
        ),
        (
            {"type": "value_error", "loc": ("body",), "msg": "Value error, Pick a metric first."},
            "Pick a metric first.",
        ),
    ],
)
def test_messages_are_sentences(error, said):
    assert plain(error) == said


# ── One name per office, and per metric in use (QA-7, QA-9) ──────────────────


def test_a_second_office_with_the_same_name_is_refused(client, admin):
    client.post("/api/offices", json={"name": "Gotham"})

    reply = client.post("/api/offices", json={"name": "gotham "})

    assert reply.status_code == 409
    assert reply.json()["detail"] == "There is already an office called “gotham”."


def test_renaming_an_office_onto_another_is_refused(client, admin):
    client.post("/api/offices", json={"name": "Gotham"})
    phoenix = client.post("/api/offices", json={"name": "Phoenix"}).json()

    assert client.patch(f"/api/offices/{phoenix['id']}", json={"name": "GOTHAM"}).status_code == 409
    # Its own name, differently cased, is not a clash with itself.
    assert client.patch(f"/api/offices/{phoenix['id']}", json={"name": "PHOENIX"}).status_code == 200


def test_an_archived_office_frees_its_name_but_cannot_come_back_onto_it(client, admin):
    old = client.post("/api/offices", json={"name": "Gotham"}).json()
    client.post(f"/api/offices/{old['id']}/archive")

    assert client.post("/api/offices", json={"name": "Gotham"}).status_code == 201
    assert client.post(f"/api/offices/{old['id']}/restore").status_code == 409


def test_two_metrics_in_use_cannot_share_a_name(client, admin, make_metric):
    make_metric("closed_deals")  # named "Closed Deals"

    reply = client.post(
        "/api/metrics",
        json={
            "key": "qa_closed_deals",
            "name": "closed deals",
            "unit": "count",
            "aggregation": "sum",
            "direction": "higher_is_better",
        },
    )

    assert reply.status_code == 409
    assert "already a metric called" in reply.json()["detail"]
