"""The competition API: who sees a contest, and who may change one.

The engine's own tests live in test_competitions.py. These are about the two
rules the HTTP layer adds — a visibility rule that deliberately differs from
every other endpoint's, and a lock that comes down the moment a contest starts.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Competition, CompetitionParticipant

#: **Relative, because "a future contest" stopped being one.** These were
#: literals — 1 to 15 September — which read correctly while they were written
#: and became a *finished* contest on the sixteenth. `test_publishing_a_future_
#: contest_schedules_it` then asserted `scheduled` against a competition the
#: engine had quite rightly closed. What the tests mean is "ahead of now" and
#: "well behind now", so that is what they say.
_MIDNIGHT = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

STARTS = _MIDNIGHT + timedelta(days=7)
ENDS = STARTS + timedelta(days=14)
PAST_START = _MIDNIGHT - timedelta(days=60)
PAST_END = PAST_START + timedelta(days=14)
DURING_PAST = PAST_START + timedelta(days=6, hours=12)


@pytest.fixture
def world(make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "teammate": make_user("agent", enterprise, name="Teammate"),
        "colleague": make_user("agent", enterprise, name="Colleague"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "outsider": make_user("agent", smb, name="Outsider"),
        "metric": make_metric("calls_made"),
    }


def body(world, **overrides):
    payload = {
        "name": "September sprint",
        "metric_id": world["metric"].id,
        "entity_type": "user",
        "starts_at": STARTS.isoformat(),
        "ends_at": ENDS.isoformat(),
        "entity_ids": [world["teammate"].id, world["colleague"].id],
    }
    return {**payload, **overrides}


def audit_count(db) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0


def seed(db, org, world, *, entrants, entity_type="user", state="active", **overrides):
    """A competition placed straight into the database, for read-path tests."""
    fields = {
        "organization_id": org.id,
        "name": "Seeded",
        "metric_definition_id": world["metric"].id,
        "entity_type": entity_type,
        "starts_at": PAST_START,
        "ends_at": PAST_END,
        "state": state,
    }
    fields.update(overrides)
    competition = Competition(**fields)
    db.add(competition)
    db.flush()
    for entrant in entrants:
        db.add(
            CompetitionParticipant(
                competition_id=competition.id,
                user_id=entrant.id if entity_type == "user" else None,
                team_id=entrant.id if entity_type == "team" else None,
            )
        )
    db.flush()
    return competition


# ── Creating ─────────────────────────────────────────────────────────────────


def test_an_admin_creates_a_draft_with_entrants(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post("/api/competitions", json=body(world))

    assert response.status_code == 201
    data = response.json()
    assert data["state"] == "draft"
    assert data["entrant_count"] == 2
    assert data["head_to_head"] is True
    assert data["rules_editable"] is True


def test_settles_at_is_computed_for_the_client(client, db, world, sign_in):
    """The one date that changes what the page means. A client doing this
    arithmetic itself would be a second place for the settlement window to be
    wrong."""
    sign_in(world["admin"])
    data = client.post("/api/competitions", json=body(world, settlement_hours=6)).json()

    assert datetime.fromisoformat(data["settles_at"]) == ENDS + timedelta(hours=6)


def test_a_competition_may_start_with_no_entrants(client, db, world, sign_in):
    """"Make the thing, then choose who is in it" is a real flow. An empty draft
    is a normal intermediate state; publishing one is not."""
    sign_in(world["admin"])
    response = client.post("/api/competitions", json=body(world, entity_ids=[]))

    assert response.status_code == 201
    assert response.json()["entrant_count"] == 0


def test_the_person_building_a_draft_can_open_it(client, db, world, sign_in):
    """The creation flow is "make it, then choose who is in it", so the gap where
    it has no entrants is a state a manager is standing in — not one to 404 them
    out of.

    Found by mutation testing: the empty-entrant branch returned a flat False,
    which is right for everybody except the one person who just created it.
    """
    sign_in(world["manager"])
    created = client.post("/api/competitions", json=body(world, entity_ids=[])).json()

    assert client.get(f"/api/competitions/{created['id']}").status_code == 200
    assert len(client.get("/api/competitions").json()) == 1


def test_another_managers_empty_draft_stays_private(
    client, db, world, sign_in, make_team, make_user
):
    """Somebody else's half-built plan, which is what a draft is."""
    sign_in(world["admin"])
    created = client.post("/api/competitions", json=body(world, entity_ids=[])).json()

    other = make_user("manager", make_team("Support"), name="Other Manager")
    sign_in(other)
    assert client.get(f"/api/competitions/{created['id']}").status_code == 404


def test_the_same_person_twice_is_entered_once(client, db, world, sign_in):
    """A client bug, not something to make a person resolve."""
    sign_in(world["admin"])
    ids = [world["teammate"].id, world["teammate"].id, world["colleague"].id]
    response = client.post("/api/competitions", json=body(world, entity_ids=ids))

    assert response.json()["entrant_count"] == 2


def test_a_backwards_window_is_refused(client, world, sign_in):
    sign_in(world["admin"])
    response = client.post(
        "/api/competitions",
        json=body(world, starts_at=ENDS.isoformat(), ends_at=STARTS.isoformat()),
    )
    assert response.status_code == 422


def test_an_archived_metric_is_refused_by_name(client, db, world, sign_in, make_metric):
    """The message names the metric, because the person picked it from a list
    that should not have offered it."""
    dead = make_metric("retired_metric")
    dead.archived_at = datetime.now(UTC)
    db.flush()
    sign_in(world["admin"])

    response = client.post("/api/competitions", json=body(world, metric_id=dead.id))

    assert response.status_code == 409
    assert "retired_metric" in response.json()["detail"] or "Retired" in response.json()["detail"]


def test_an_agent_cannot_create_one(client, world, sign_in):
    sign_in(world["teammate"])
    assert client.post("/api/competitions", json=body(world)).status_code == 403


def test_a_manager_cannot_enter_somebody_elses_team_member(client, world, sign_in):
    sign_in(world["manager"])
    response = client.post(
        "/api/competitions", json=body(world, entity_ids=[world["stranger"].id])
    )
    assert response.status_code == 404


def test_creating_is_audited(client, db, world, sign_in):
    sign_in(world["admin"])
    before = audit_count(db)
    client.post("/api/competitions", json=body(world))

    assert audit_count(db) == before + 1
    entry = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert entry.action == "competition.created"
    assert entry.details["entrants"] == 2


# ── Who sees it ──────────────────────────────────────────────────────────────


def test_an_entrant_sees_the_whole_table(client, db, org, world, sign_in, make_fact):
    """The deliberate break from every other endpoint's scope rule.

    A competition whose entrants cannot see each other's positions is not a
    competition. Entering is consent to be ranked in it.
    """
    make_fact(world["metric"], world["teammate"], 50, DURING_PAST)
    make_fact(world["metric"], world["colleague"], 90, DURING_PAST)
    competition = seed(db, org, world, entrants=[world["teammate"], world["colleague"]])

    sign_in(world["teammate"])
    data = client.get(f"/api/competitions/{competition.id}").json()

    assert [row["entity_name"] for row in data["standings"]] == ["Colleague", "Teammate"]
    assert data["you"]["entity_name"] == "Teammate"
    assert data["you"]["rank"] == 2


def test_an_agent_cannot_see_a_contest_they_are_not_in(client, db, org, world, sign_in):
    """A manager-versus-manager contest in another office. No stake in it, and
    nothing to learn from it but other people's numbers."""
    competition = seed(db, org, world, entrants=[world["stranger"], world["outsider"]])

    sign_in(world["teammate"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404
    assert client.get("/api/competitions").json() == []


def test_one_visible_entrant_does_not_reveal_the_rest(client, db, org, world, sign_in):
    """"Every", not "any". A contest of one person you can see and two you cannot
    must not hand over the whole entrant list.

    **The actor has to be a manager.** The first version signed in an agent, who
    can see nobody but themselves — so "any entrant visible" and "every entrant
    visible" were both false and the test passed under a mutation that turned
    `all` into `any`. A manager is the only role with a set that spans some
    people and not others, which is the only fixture that can tell the two
    apart.
    """
    competition = seed(
        db, org, world, entrants=[world["colleague"], world["stranger"], world["outsider"]]
    )

    sign_in(world["manager"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404
    assert client.get("/api/competitions").json() == []


def test_an_agent_sees_nothing_they_are_not_in(client, db, org, world, sign_in):
    """The agent-shaped version of the rule above: they see only themselves, so
    only contests they are entered in."""
    competition = seed(db, org, world, entrants=[world["colleague"], world["stranger"]])

    sign_in(world["teammate"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404


def test_a_contest_between_empty_teams_is_not_public(
    client, db, org, world, sign_in, make_team
):
    """A leak found by mutation testing, not by a failing test.

    The team rule used to check that every member of every entrant team was
    visible. For two empty teams that is `all()` over nothing — vacuously true —
    which showed the contest to everybody in the organization. The rule is now
    "your team is in it", which has no empty case to be wrong about.
    """
    competition = seed(
        db, org, world,
        entrants=[make_team("Ghost A"), make_team("Ghost B")],
        entity_type="team",
    )

    sign_in(world["teammate"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404

    sign_in(world["manager"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404


def test_somebody_on_no_team_sees_no_team_contest(client, db, org, world, sign_in, make_user):
    """`team_id IS NULL` is not a wildcard.

    A newly invited agent has no team yet. Writing the rule as "your team is in
    it" makes `None in ids` the whole guard, and `None` is never in a list of
    team ids — but the guard has to be explicit, because a version that read
    `actor.team_id in ids or actor.team_id is None` survived the rest of this
    suite and showed every team contest in the organization to anybody waiting
    to be placed.
    """
    competition = seed(
        db, org, world,
        entrants=[world["enterprise"], world["smb"]],
        entity_type="team",
    )

    sign_in(make_user("agent", None, name="Unplaced"))
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404


def test_a_manager_does_not_see_a_team_contest_they_are_out_of(
    client, db, org, world, sign_in, make_team
):
    competition = seed(
        db, org, world,
        entrants=[world["smb"], make_team("Partners")],
        entity_type="team",
    )

    sign_in(world["manager"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404


def test_a_manager_sees_a_contest_among_their_own_people(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"], world["colleague"]])

    sign_in(world["manager"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 200


def test_a_manager_does_not_see_another_teams_contest(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["stranger"], world["outsider"]])

    sign_in(world["manager"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404


def test_a_team_contest_is_visible_to_its_members(client, db, org, world, sign_in):
    competition = seed(
        db, org, world,
        entrants=[world["enterprise"], world["smb"]],
        entity_type="team",
    )

    sign_in(world["teammate"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 200


def test_another_organizations_competition_is_invisible(
    client, db, world, sign_in, make_user
):
    """The cross-org check. A mutation removing it survived a whole suite earlier
    this session because every test used one organization."""
    from app.models import Organization

    other = Organization(name="Rival Corp", timezone="UTC")
    db.add(other)
    db.flush()
    competition = Competition(
        organization_id=other.id,
        name="Their sprint",
        metric_definition_id=world["metric"].id,
        entity_type="user",
        starts_at=PAST_START,
        ends_at=PAST_END,
        state="active",
    )
    db.add(competition)
    db.flush()

    sign_in(world["admin"])
    assert client.get(f"/api/competitions/{competition.id}").status_code == 404
    assert client.get("/api/competitions").json() == []


def test_an_agent_does_not_see_drafts(client, db, org, world, sign_in):
    """A draft is a plan, not an announcement."""
    seed(db, org, world, entrants=[world["teammate"], world["colleague"]], state="draft")

    sign_in(world["teammate"])
    assert client.get("/api/competitions").json() == []

    sign_in(world["admin"])
    assert len(client.get("/api/competitions").json()) == 1


def test_mine_filters_to_contests_you_are_in(client, db, org, world, sign_in):
    seed(db, org, world, entrants=[world["teammate"], world["colleague"]])
    seed(db, org, world, entrants=[world["stranger"], world["outsider"]])

    sign_in(world["admin"])
    assert len(client.get("/api/competitions").json()) == 2
    assert client.get("/api/competitions?mine=true").json() == []

    sign_in(world["colleague"])
    assert len(client.get("/api/competitions?mine=true").json()) == 1


def test_the_pinned_row_is_absent_for_a_non_entrant(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"], world["colleague"]])

    sign_in(world["admin"])
    assert client.get(f"/api/competitions/{competition.id}").json()["you"] is None


def test_provisional_is_true_only_between_ending_and_settling(
    client, db, org, world, sign_in
):
    sign_in(world["admin"])
    running = seed(db, org, world, entrants=[world["teammate"]], state="active")
    ended = seed(db, org, world, entrants=[world["teammate"]], state="ended")
    closed = seed(db, org, world, entrants=[world["teammate"]], state="closed")

    def provisional(competition):
        return client.get(f"/api/competitions/{competition.id}").json()["competition"][
            "provisional"
        ]

    assert provisional(running) is False
    assert provisional(ended) is True
    assert provisional(closed) is False


# ── Editing ──────────────────────────────────────────────────────────────────


def test_a_draft_can_change_anything(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    sign_in(world["admin"])

    response = client.patch(
        f"/api/competitions/{competition.id}",
        json={"name": "Renamed", "tie_break": "shared_rank", "min_participation": 3},
    )

    assert response.status_code == 200
    assert response.json()["tie_break"] == "shared_rank"


def test_a_scheduled_competition_can_still_change_its_rules(
    client, db, org, world, sign_in
):
    """Published and visible, but nobody has competed under the old rules yet."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="scheduled")
    sign_in(world["admin"])

    response = client.patch(
        f"/api/competitions/{competition.id}", json={"tie_break": "shared_rank"}
    )
    assert response.status_code == 200


def test_a_running_competition_cannot_change_its_rules(client, db, org, world, sign_in):
    """Changing the rules mid-contest destroys the result, and the result is the
    only thing anybody will remember."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="active")
    sign_in(world["admin"])

    response = client.patch(
        f"/api/competitions/{competition.id}", json={"tie_break": "shared_rank"}
    )

    assert response.status_code == 409
    # The refusal names the field, because the person is mid-edit and needs to
    # know which part to undo.
    assert "tie_break" in response.json()["detail"]


def test_a_running_competition_can_still_be_renamed(client, db, org, world, sign_in):
    """The name describes the contest; it does not decide it. The prize can
    change too, with a reason everybody in it can read (6.14)."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="active")
    sign_in(world["admin"])

    response = client.patch(
        f"/api/competitions/{competition.id}",
        json={"name": "Renamed mid-flight", "prize": "Two steak dinners",
              "note": "The sponsor doubled it"},
    )

    assert response.status_code == 200
    assert response.json()["prize"] == "Two steak dinners"


def test_a_new_end_date_is_checked_against_the_stored_start(
    client, db, org, world, sign_in
):
    """The payload alone cannot tell you the window is backwards. Sending only
    `ends_at` can invert a window whose `starts_at` was already stored."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    sign_in(world["admin"])

    response = client.patch(
        f"/api/competitions/{competition.id}",
        json={"ends_at": (PAST_START - timedelta(days=1)).isoformat()},
    )

    assert response.status_code == 400


def test_a_closed_competition_cannot_be_edited_at_all(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="closed")
    sign_in(world["admin"])

    response = client.patch(f"/api/competitions/{competition.id}", json={"name": "No"})
    assert response.status_code == 409


# ── Publishing ───────────────────────────────────────────────────────────────


def test_publishing_a_future_contest_schedules_it(client, db, org, world, sign_in):
    """Starts later, so it waits — which is what builds the anticipation."""
    competition = seed(
        db, org, world,
        entrants=[world["teammate"], world["colleague"]],
        state="draft",
        starts_at=STARTS,
        ends_at=ENDS,
    )
    sign_in(world["admin"])

    assert client.post(f"/api/competitions/{competition.id}/publish").json()["state"] == (
        "scheduled"
    )


def test_publishing_a_contest_that_has_already_begun_starts_it(
    client, db, org, world, sign_in
):
    """The bug this fixes.

    Publish a contest whose start date has passed and it used to sit under
    *Upcoming* saying "starts in now" until the lifecycle job's next pass. Publish
    runs the same state machine the job runs, so it lands where the clock actually
    puts it.
    """
    now = datetime.now(UTC)
    competition = seed(
        db, org, world,
        entrants=[world["teammate"], world["colleague"]],
        state="draft",
        starts_at=now - timedelta(hours=2),
        ends_at=now + timedelta(days=7),
    )
    sign_in(world["admin"])

    data = client.post(f"/api/competitions/{competition.id}/publish").json()

    assert data["state"] == "active"
    assert data["provisional"] is False


def test_publishing_an_already_begun_contest_tells_the_entrants(
    client, db, org, world, sign_in
):
    """Starting is what announces, so a contest that starts on publish announces
    on publish — not whenever the job next runs."""
    from app.models import Notification

    now = datetime.now(UTC)
    competition = seed(
        db, org, world,
        entrants=[world["teammate"], world["colleague"]],
        state="draft",
        starts_at=now - timedelta(hours=2),
        ends_at=now + timedelta(days=7),
    )
    sign_in(world["admin"])

    client.post(f"/api/competitions/{competition.id}/publish")

    told = db.scalars(
        select(Notification).where(Notification.event_key == "competition.started")
    ).all()
    assert {n.user_id for n in told} == {
        world["teammate"].id,
        world["colleague"].id,
    }


def test_publishing_a_wholly_past_contest_runs_it_to_the_end(
    client, db, org, world, sign_in, make_fact
):
    """An odd thing to do, but the state machine should not stop halfway. Its
    window and its settlement window are both over, so it settles."""
    make_fact(world["metric"], world["teammate"], 100, DURING_PAST)
    competition = seed(
        db, org, world,
        entrants=[world["teammate"], world["colleague"]],
        state="draft",
        starts_at=PAST_START,
        ends_at=PAST_END,
        settlement_hours=0,
    )
    sign_in(world["admin"])

    data = client.post(f"/api/competitions/{competition.id}/publish").json()

    assert data["state"] == "closed"


def test_a_one_horse_race_cannot_be_published(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    sign_in(world["admin"])

    response = client.post(f"/api/competitions/{competition.id}/publish")

    assert response.status_code == 409
    # Singular, because "1 entrants" is the kind of detail that makes a product
    # feel unfinished — and the same bug I shipped in the channel message.
    assert "1 entrant." in response.json()["detail"]


def test_an_empty_draft_cannot_be_published(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[], state="draft")
    sign_in(world["admin"])

    response = client.post(f"/api/competitions/{competition.id}/publish")
    assert response.status_code == 409
    assert "0 entrants." in response.json()["detail"]


def test_publishing_twice_is_refused(client, db, org, world, sign_in):
    competition = seed(
        db, org, world, entrants=[world["teammate"], world["colleague"]], state="scheduled"
    )
    sign_in(world["admin"])

    assert client.post(f"/api/competitions/{competition.id}/publish").status_code == 409


# ── Entrants ─────────────────────────────────────────────────────────────────


def test_an_entrant_can_be_added_to_a_draft(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    sign_in(world["admin"])

    response = client.post(
        f"/api/competitions/{competition.id}/participants",
        json={"entity_id": world["colleague"].id},
    )

    assert response.status_code == 201
    assert response.json()["entity_name"] == "Colleague"


def test_nobody_joins_a_contest_that_has_started_without_a_reason(
    client, db, org, world, sign_in
):
    """A late entrant is allowed (6.14), but not quietly: everybody in it sees
    who joined and why."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="active")
    sign_in(world["admin"])

    response = client.post(
        f"/api/competitions/{competition.id}/participants",
        json={"entity_id": world["colleague"].id},
    )
    assert response.status_code == 400


def test_entering_the_same_person_twice_is_refused_by_name(
    client, db, org, world, sign_in
):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    sign_in(world["admin"])

    response = client.post(
        f"/api/competitions/{competition.id}/participants",
        json={"entity_id": world["teammate"].id},
    )

    assert response.status_code == 409
    assert "Teammate" in response.json()["detail"]


def test_an_entrant_can_be_removed_from_a_draft(client, db, org, world, sign_in):
    competition = seed(
        db, org, world, entrants=[world["teammate"], world["colleague"]], state="draft"
    )
    sign_in(world["admin"])
    participants = client.get(f"/api/competitions/{competition.id}/participants").json()

    response = client.delete(
        f"/api/competitions/{competition.id}/participants/{participants[0]['id']}"
    )

    assert response.status_code == 204
    assert len(client.get(f"/api/competitions/{competition.id}/participants").json()) == 1


def test_nobody_is_removed_from_a_running_contest(client, db, org, world, sign_in):
    """Taking somebody out of a contest they have been competing in rewrites what
    everyone else saw."""
    competition = seed(
        db, org, world, entrants=[world["teammate"], world["colleague"]], state="active"
    )
    sign_in(world["admin"])
    participants = client.get(f"/api/competitions/{competition.id}/participants").json()

    response = client.delete(
        f"/api/competitions/{competition.id}/participants/{participants[0]['id']}"
    )

    assert response.status_code == 409
    assert "Cancel it instead" in response.json()["detail"]


def test_an_entrant_id_from_another_competition_is_not_found(
    client, db, org, world, sign_in
):
    """The path names two things, and only checking the second would let one
    competition delete another's entrants."""
    mine = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    theirs = seed(db, org, world, entrants=[world["colleague"]], state="draft")
    sign_in(world["admin"])
    other = client.get(f"/api/competitions/{theirs.id}/participants").json()[0]

    response = client.delete(f"/api/competitions/{mine.id}/participants/{other['id']}")
    assert response.status_code == 404


# ── Cancelling and closing early ─────────────────────────────────────────────


def test_cancelling_leaves_no_result(client, db, org, world, sign_in):
    """The honest option when a contest was set up wrongly: nothing to be quoted
    later."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="active")
    sign_in(world["admin"])

    assert client.post(f"/api/competitions/{competition.id}/cancel").json()["state"] == (
        "cancelled"
    )
    assert db.scalar(
        select(CompetitionParticipant.final_rank).where(
            CompetitionParticipant.competition_id == competition.id
        )
    ) is None


def test_a_settled_competition_cannot_be_cancelled(client, db, org, world, sign_in):
    """Cancelling it now would remove a result people have seen."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="closed")
    sign_in(world["admin"])

    response = client.post(f"/api/competitions/{competition.id}/cancel")
    assert response.status_code == 409


def test_an_admin_can_settle_early(client, db, org, world, sign_in, make_fact):
    """For the case the settlement window exists to handle going wrong."""
    make_fact(world["metric"], world["teammate"], 100, DURING_PAST)
    make_fact(world["metric"], world["colleague"], 40, DURING_PAST)
    competition = seed(
        db, org, world, entrants=[world["teammate"], world["colleague"]], state="ended"
    )
    sign_in(world["admin"])

    data = client.post(f"/api/competitions/{competition.id}/close").json()

    assert data["competition"]["state"] == "closed"
    assert data["standings"][0]["entity_name"] == "Teammate"
    assert data["standings"][0]["final"] is True


def test_a_manager_cannot_settle_early(client, db, org, world, sign_in):
    """The one action here that cannot be undone and that somebody will be asked
    to justify."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="ended")
    sign_in(world["manager"])

    assert client.post(f"/api/competitions/{competition.id}/close").status_code == 403


def test_a_competition_that_has_not_started_has_nothing_to_settle(
    client, db, org, world, sign_in
):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="scheduled")
    sign_in(world["admin"])

    response = client.post(f"/api/competitions/{competition.id}/close")
    assert response.status_code == 409
    assert "no result to settle" in response.json()["detail"]


def test_closing_early_is_audited(client, db, org, world, sign_in, make_fact):
    make_fact(world["metric"], world["teammate"], 100, DURING_PAST)
    competition = seed(db, org, world, entrants=[world["teammate"]], state="ended")
    sign_in(world["admin"])

    client.post(f"/api/competitions/{competition.id}/close")

    entry = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert entry.action == "competition.closed_early"
    assert entry.details["ranked"] == 1


# ── The historical preview ───────────────────────────────────────────────────


#: Inside the window a preview of a future contest actually measures.
#:
#: The preview looks back from *now* when the contest starts later, so a fact
#: dated relative to STARTS lands outside it. Getting this wrong is what the
#: anchor bug looked like from the test side.
RECENT = datetime.now(UTC) - timedelta(days=2)


def preview_body(world, **overrides):
    payload = {
        "metric_id": world["metric"].id,
        "entity_type": "user",
        "entity_ids": [world["teammate"].id, world["colleague"].id],
        "starts_at": STARTS.isoformat(),
        "ends_at": ENDS.isoformat(),
    }
    return {**payload, **overrides}


def test_the_preview_window_is_the_same_length_as_the_contest(
    client, db, world, sign_in
):
    """Not "last month". A two-week sprint compared against a calendar month is
    comparing a number to a bigger one."""
    sign_in(world["admin"])

    data = client.post("/api/competitions/preview", json=preview_body(world)).json()

    measured = datetime.fromisoformat(data["ends_at"]) - datetime.fromisoformat(
        data["starts_at"]
    )
    assert measured == ENDS - STARTS


def test_the_preview_window_is_always_in_the_past(client, db, world, sign_in):
    """The bug that only showed up against real data.

    The first version measured backwards from `starts_at`, which is history only
    if the contest begins today. A contest scheduled for next month got a
    "history" reaching a fortnight into the future, where every number is
    necessarily zero — and the original test passed, because it asserted exactly
    what the code did.

    STARTS is in the future here, which is the normal case when somebody is
    planning a contest.
    """
    sign_in(world["admin"])

    data = client.post("/api/competitions/preview", json=preview_body(world)).json()

    assert datetime.fromisoformat(data["ends_at"]) <= datetime.now(UTC)


def test_a_contest_already_underway_is_previewed_from_its_own_start(
    client, db, world, sign_in
):
    """The other side of the anchor: when the start *is* in the past, that is the
    honest thing to measure back from, not today — otherwise the window overlaps
    the contest it is meant to be a rehearsal for."""
    sign_in(world["admin"])

    data = client.post(
        "/api/competitions/preview",
        json=preview_body(
            world,
            starts_at=PAST_START.isoformat(),
            ends_at=PAST_END.isoformat(),
        ),
    ).json()

    assert datetime.fromisoformat(data["ends_at"]) == PAST_START


def test_the_preview_ranks_the_entrants_it_was_given(
    client, db, world, sign_in, make_fact
):
    make_fact(world["metric"], world["teammate"], 40, RECENT)
    make_fact(world["metric"], world["colleague"], 90, RECENT)
    # Not an entrant, and outscoring both.
    make_fact(world["metric"], world["stranger"], 500, RECENT)
    sign_in(world["admin"])

    data = client.post("/api/competitions/preview", json=preview_body(world)).json()

    assert [row["entity_name"] for row in data["standings"]] == ["Colleague", "Teammate"]


def test_the_preview_reports_the_spread(client, db, world, sign_in, make_fact):
    """One number for "is this a contest or a coronation", so nobody has to read
    the table and work it out in their head."""
    make_fact(world["metric"], world["teammate"], 25, RECENT)
    make_fact(world["metric"], world["colleague"], 100, RECENT)
    sign_in(world["admin"])

    data = client.post("/api/competitions/preview", json=preview_body(world)).json()

    assert data["spread"] == 4.0


def test_the_spread_is_absent_when_the_field_recorded_nothing(
    client, db, world, sign_in, make_fact
):
    """A ratio against zero has no meaning, and "Infinity" on a form is worse
    than a blank."""
    make_fact(world["metric"], world["colleague"], 100, RECENT)
    sign_in(world["admin"])

    data = client.post("/api/competitions/preview", json=preview_body(world)).json()

    assert data["spread"] is None


def test_the_preview_ignores_facts_inside_the_planned_window(
    client, db, world, sign_in, make_fact
):
    """The window being previewed has not happened yet. Anything dated inside it
    is not evidence about it."""
    make_fact(world["metric"], world["teammate"], 999, STARTS + timedelta(days=2))
    sign_in(world["admin"])

    data = client.post("/api/competitions/preview", json=preview_body(world)).json()

    assert [Decimal(row["value"]) for row in data["standings"]] == [Decimal(0), Decimal(0)]


def test_the_preview_needs_at_least_one_entrant(client, world, sign_in):
    sign_in(world["admin"])
    response = client.post("/api/competitions/preview", json=preview_body(world, entity_ids=[]))
    assert response.status_code == 422


def test_a_manager_cannot_preview_somebody_elses_team(client, world, sign_in):
    """The preview reports numbers. It has to be scoped exactly as tightly as the
    contest itself — a preview endpoint that skipped the check would be a way to
    read any colleague's totals."""
    sign_in(world["manager"])
    response = client.post(
        "/api/competitions/preview", json=preview_body(world, entity_ids=[world["stranger"].id])
    )
    assert response.status_code == 404


def test_an_agent_cannot_preview_at_all(client, world, sign_in):
    sign_in(world["teammate"])
    assert client.post("/api/competitions/preview", json=preview_body(world)).status_code == 403


def test_preview_is_not_swallowed_by_the_detail_route(client, world, sign_in):
    """`/competitions/preview` sits above `/competitions/{id}`. This test exists
    so that reordering the routes fails here rather than in the browser."""
    sign_in(world["admin"])
    assert client.post("/api/competitions/preview", json=preview_body(world)).status_code == 200


# ── Back to draft, and deleting ──────────────────────────────────────────────


def test_a_scheduled_competition_can_go_back_to_draft(client, db, org, world, sign_in):
    """Publishing used to be a one-way door: a contest with the wrong metric
    could only be cancelled, which left it in Finished for good."""
    competition = seed(
        db, org, world, entrants=[world["teammate"]], state="scheduled"
    )
    sign_in(world["admin"])

    response = client.post(f"/api/competitions/{competition.id}/unpublish")

    assert response.status_code == 200
    assert response.json()["state"] == "draft"
    assert response.json()["rules_editable"] is True


def test_a_running_competition_can_go_back_to_draft(client, db, org, world, sign_in):
    """Nothing irreversible has happened yet — no result is frozen — so somebody
    who has spotted a mistake can pull it back and fix it."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="active")
    sign_in(world["admin"])

    assert (
        client.post(f"/api/competitions/{competition.id}/unpublish").json()["state"]
        == "draft"
    )


def test_a_cancelled_competition_can_be_revived(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="cancelled")
    sign_in(world["admin"])

    assert (
        client.post(f"/api/competitions/{competition.id}/unpublish").json()["state"]
        == "draft"
    )


def test_a_settled_competition_cannot_be_reopened(client, db, org, world, sign_in):
    """The one refusal. Its result has been announced; reopening it would make a
    winner provisional after the fact."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="closed")
    sign_in(world["admin"])

    response = client.post(f"/api/competitions/{competition.id}/unpublish")

    assert response.status_code == 409
    assert "cannot be reopened" in response.json()["detail"]


def test_a_draft_is_already_a_draft(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    sign_in(world["admin"])

    assert client.post(f"/api/competitions/{competition.id}/unpublish").status_code == 409


def test_going_back_to_draft_records_where_it_came_from(client, db, org, world, sign_in):
    """`was` is captured before the assignment. Read after, it logged every
    transition as coming from `draft` — the same bug the cancel endpoint had."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="active")
    sign_in(world["admin"])

    client.post(f"/api/competitions/{competition.id}/unpublish")

    entry = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert entry.action == "competition.unpublished"
    assert entry.details["was"] == "active"


def test_cancelling_records_where_it_came_from(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="scheduled")
    sign_in(world["admin"])

    client.post(f"/api/competitions/{competition.id}/cancel")

    entry = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert entry.details["was"] == "scheduled"


def test_a_draft_can_be_deleted(client, db, org, world, sign_in):
    competition = seed(
        db, org, world, entrants=[world["teammate"], world["colleague"]], state="draft"
    )
    sign_in(world["admin"])

    assert client.delete(f"/api/competitions/{competition.id}").status_code == 204
    assert db.get(Competition, competition.id) is None
    # Entrant rows go with it through the cascade.
    assert db.scalars(
        select(CompetitionParticipant).where(
            CompetitionParticipant.competition_id == competition.id
        )
    ).all() == []


def test_a_cancelled_competition_can_be_deleted(client, db, org, world, sign_in):
    """Both deletable states mean "nothing came of this", so there is no record
    to protect."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="cancelled")
    sign_in(world["admin"])

    assert client.delete(f"/api/competitions/{competition.id}").status_code == 204


def test_a_settled_competition_cannot_be_deleted(client, db, org, world, sign_in):
    """It is the record of a prize somebody received, which is the whole reason
    its numbers are stored instead of derived."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="closed")
    sign_in(world["admin"])

    response = client.delete(f"/api/competitions/{competition.id}")

    assert response.status_code == 409
    assert "record of a result" in response.json()["detail"]
    assert db.get(Competition, competition.id) is not None


def test_a_running_competition_must_be_cancelled_first(client, db, org, world, sign_in):
    """So its entrants see a decision rather than a disappearance."""
    competition = seed(db, org, world, entrants=[world["teammate"]], state="active")
    sign_in(world["admin"])

    response = client.delete(f"/api/competitions/{competition.id}")

    assert response.status_code == 409
    assert "Cancel it first" in response.json()["detail"]


def test_deleting_is_audited_with_the_state_it_was_in(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="cancelled")
    sign_in(world["admin"])

    client.delete(f"/api/competitions/{competition.id}")

    entry = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert entry.action == "competition.deleted"
    # Read before the delete: attributes survive on a deleted instance right up
    # until the session expires it.
    assert entry.details["was"] == "cancelled"


def test_an_agent_cannot_delete_a_competition(client, db, org, world, sign_in):
    competition = seed(db, org, world, entrants=[world["teammate"]], state="draft")
    sign_in(world["teammate"])

    assert client.delete(f"/api/competitions/{competition.id}").status_code == 403


def test_a_refused_window_is_said_without_the_libraries_label(client, world, sign_in):
    """QA-13: it read "Value error, A competition has to end after it starts.\""""
    sign_in(world["admin"])

    reply = client.post(
        "/api/competitions",
        json=body(world, starts_at=ENDS.isoformat(), ends_at=STARTS.isoformat()),
    )

    assert reply.status_code == 422
    message = reply.json()["detail"][0]["msg"]
    assert not message.startswith("Value error")
    assert "end after it starts" in message


def test_a_head_to_head_brings_both_faces(client, db, org, world, sign_in, make_fact):
    """8.5: the two panels facing each other show who they are."""
    import io

    from PIL import Image

    from app import photos

    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (0, 0, 255)).save(buffer, format="PNG")
    stored = photos.set_custom(db, world["teammate"], buffer.getvalue())
    competition = seed(db, org, world, entrants=[world["teammate"], world["colleague"]])
    make_fact(world["metric"], world["teammate"], 5, DURING_PAST)
    make_fact(world["metric"], world["colleague"], 3, DURING_PAST)
    db.commit()
    sign_in(world["admin"])

    standings = client.get(f"/api/competitions/{competition.id}").json()["standings"]

    faces = {s["entity_name"]: s["photo_digest"] for s in standings}
    assert faces == {"Teammate": stored.sha256, "Colleague": None}
