"""Microsoft Teams and channels as GoalGetter teams and offices.

The properties worth guarding are the ones that move people or would surprise
an admin: nobody moves until it is applied, a channel beats the Team it is in,
two answers is a conflict left for a person, a role is never touched — and
**the mirror only undoes its own work**, so somebody moved by hand stays where
they were put.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.connectors.rest import RestProblem
from app.crypto import encrypt
from app.directory import microsoft, mirror, structure
from app.directory import sync as directory_sync
from app.models import (
    AuditLog,
    DirectoryPerson,
    M365Link,
    M365Member,
    M365Source,
    MirrorPlacement,
    OauthClient,
    Office,
    Team,
)

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


@pytest.fixture
def connection(db, org):
    row = OauthClient(
        organization_id=org.id, provider="microsoft", client_id="client",
        client_secret_encrypted=encrypt("s"), tenant_id="contoso.onmicrosoft.com",
        directory_sync_enabled=True,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def world(db, org, connection, make_team, make_user):
    smb = make_team("SMB")
    return {
        "smb": smb,
        "admin": make_user("admin", name="Bruce Wayne"),
        "peter": make_user("agent", name="Peter Parker"),
        "clark": make_user("agent", smb, name="Clark Kent"),
        "diana": make_user("manager", name="Diana Prince"),
    }


def in_directory(db, org, person, *, office=""):
    db.add(
        DirectoryPerson(
            organization_id=org.id, provider="microsoft",
            external_id=f"ext-{person.id}", email=person.email,
            display_name=person.full_name, status="approved",
            user_account_id=person.id, office_location=office,
        )
    )
    db.flush()
    return f"ext-{person.id}"


_ids = iter(range(1, 100_000))


def source(db, org, name, *, members=(), kind="team", parent=None, membership=None):
    row = M365Source(
        organization_id=org.id, kind=kind, external_id=f"src-{next(_ids)}",
        name=name, parent_id=parent.id if parent else None,
        membership=membership if kind == "channel" else None, last_seen_at=NOW,
    )
    db.add(row)
    db.flush()
    for person in members:
        db.add(M365Member(source_id=row.id, person_external_id=f"ext-{person.id}"))
    db.flush()
    return row


def link(db, org, src, target):
    if isinstance(target, Team):
        row = M365Link(organization_id=org.id, source_id=src.id, target="team", team_id=target.id)
    else:
        row = M365Link(organization_id=org.id, source_id=src.id, target="office", office_id=target.id)
    db.add(row)
    db.flush()
    return row


def status_of(db, org, person):
    return next(p for p in mirror.picture(db, org.id).people if p.user_id == person.id)


# ── Where people belong ─────────────────────────────────────────────────────


def test_somebody_in_a_linked_team_would_join_it(db, org, world, make_team):
    phoenix = make_team("Phoenix Sales")
    in_directory(db, org, world["peter"])
    link(db, org, source(db, org, "Phoenix Sales", members=[world["peter"]]), phoenix)

    found = status_of(db, org, world["peter"])

    assert found.status == "would_move"
    assert found.teams_team_id == phoenix.id
    assert world["peter"].team_id is None, "nothing moves until it is applied"


def test_applying_moves_them_and_remembers_it(db, org, world, make_team):
    phoenix = make_team("Phoenix Sales")
    in_directory(db, org, world["peter"])
    link(db, org, source(db, org, "Phoenix Sales", members=[world["peter"]]), phoenix)

    mirror.apply(db, org.id)

    assert world["peter"].team_id == phoenix.id
    assert db.get(MirrorPlacement, world["peter"].id).team_id == phoenix.id
    assert status_of(db, org, world["peter"]).status == "in_step"


def test_a_channel_beats_the_team_it_is_in(db, org, world, make_team):
    """The channel is the finer grain: "Phoenix" is the office's Team, "Phoenix
    Closers" the private channel that is one pod of it."""
    phoenix = make_team("Phoenix")
    closers = make_team("Closers")
    in_directory(db, org, world["peter"])
    parent = source(db, org, "Phoenix", members=[world["peter"]])
    channel = source(
        db, org, "Closers", members=[world["peter"]], kind="channel",
        parent=parent, membership="private",
    )
    link(db, org, parent, phoenix)
    link(db, org, channel, closers)

    assert status_of(db, org, world["peter"]).teams_team_id == closers.id


def test_two_answers_is_a_conflict_nobody_resolves_for_them(db, org, world, make_team):
    a, b = make_team("Phoenix"), make_team("Tempe")
    in_directory(db, org, world["peter"])
    link(db, org, source(db, org, "Phoenix", members=[world["peter"]]), a)
    link(db, org, source(db, org, "Tempe", members=[world["peter"]]), b)

    assert status_of(db, org, world["peter"]).status == "conflict"
    mirror.apply(db, org.id)
    assert world["peter"].team_id is None


def test_keep_here_settles_a_conflict(db, org, world, make_team):
    a, b = make_team("Phoenix"), make_team("Tempe")
    in_directory(db, org, world["clark"])
    link(db, org, source(db, org, "Phoenix", members=[world["clark"]]), a)
    link(db, org, source(db, org, "Tempe", members=[world["clark"]]), b)

    mirror.keep(db, world["clark"])

    found = status_of(db, org, world["clark"])
    assert found.status == "kept"
    assert mirror.follow(db, org.id, world["clark"].id) is None, "following would pick a side"


def test_a_role_is_never_touched(db, org, world, make_team):
    phoenix = make_team("Phoenix")
    in_directory(db, org, world["diana"])
    link(db, org, source(db, org, "Phoenix", members=[world["diana"]]), phoenix)

    mirror.apply(db, org.id)

    assert world["diana"].team_id == phoenix.id
    assert world["diana"].org_role == "manager"


# ── Hand moves ───────────────────────────────────────────────────────────────


def placed(db, org, world, make_team):
    phoenix = make_team("Phoenix")
    in_directory(db, org, world["peter"])
    link(db, org, source(db, org, "Phoenix", members=[world["peter"]]), phoenix)
    mirror.apply(db, org.id)
    return phoenix


def test_a_hand_move_is_left_alone(db, org, world, make_team):
    """GoalGetter is a source of truth too. Somebody moved Peter on purpose."""
    phoenix = placed(db, org, world, make_team)
    world["peter"].team_id = world["smb"].id
    db.flush()

    assert status_of(db, org, world["peter"]).status == "moved_by_hand"
    mirror.apply(db, org.id)
    assert world["peter"].team_id == world["smb"].id
    assert phoenix.id != world["smb"].id


def test_keep_here_stops_listing_it_as_a_decision(db, org, world, make_team):
    placed(db, org, world, make_team)
    world["peter"].team_id = world["smb"].id
    db.flush()

    mirror.keep(db, world["peter"])

    assert status_of(db, org, world["peter"]).status == "kept"
    mirror.apply(db, org.id)
    assert world["peter"].team_id == world["smb"].id


def test_follow_teams_hands_them_back(db, org, world, make_team):
    phoenix = placed(db, org, world, make_team)
    world["peter"].team_id = world["smb"].id
    db.flush()

    mirror.follow(db, org.id, world["peter"].id)

    assert world["peter"].team_id == phoenix.id
    assert status_of(db, org, world["peter"]).status == "in_step"


def test_leaving_the_microsoft_team_undoes_the_mirrors_own_placement(db, org, world, make_team):
    placed(db, org, world, make_team)
    db.execute(M365Member.__table__.delete())

    assert status_of(db, org, world["peter"]).status == "would_move"
    mirror.apply(db, org.id)
    assert world["peter"].team_id is None
    assert db.get(MirrorPlacement, world["peter"].id) is None


def test_somebody_put_on_a_linked_team_by_hand_is_not_removed(db, org, world):
    """Clark was on SMB before it was linked, and is not in its Microsoft Team.
    The mirror never put him there, so it is not the mirror's to undo."""
    in_directory(db, org, world["clark"])
    link(db, org, source(db, org, "SMB"), world["smb"])

    assert status_of(db, org, world["clark"]).status == "only_here"
    mirror.apply(db, org.id)
    assert world["clark"].team_id == world["smb"].id


# ── Offices ──────────────────────────────────────────────────────────────────


def test_a_channel_team_inside_an_office_team_goes_in_that_office(db, org, world, make_team):
    phoenix_office = Office(organization_id=org.id, name="Phoenix")
    db.add(phoenix_office)
    closers = make_team("Closers")
    in_directory(db, org, world["peter"])
    parent = source(db, org, "Phoenix", members=[world["peter"]])
    channel = source(
        db, org, "Closers", members=[world["peter"]], kind="channel",
        parent=parent, membership="private",
    )
    link(db, org, parent, phoenix_office)
    link(db, org, channel, closers)

    decided = mirror.picture(db, org.id)
    assert [(c.team_id, c.to_office_id) for c in decided.office_changes] == [
        (closers.id, phoenix_office.id)
    ]
    assert status_of(db, org, world["peter"]).teams_office_id == phoenix_office.id

    mirror.apply(db, org.id)
    assert closers.office_id == phoenix_office.id


def test_an_office_link_alone_moves_nobody(db, org, world):
    """A person here has a team, and a team has an office. An office link says
    where somebody should be; it is shown, not forced."""
    office = Office(organization_id=org.id, name="Tempe")
    db.add(office)
    db.flush()
    in_directory(db, org, world["clark"])
    link(db, org, source(db, org, "Tempe", members=[world["clark"]]), office)

    found = status_of(db, org, world["clark"])
    assert found.status == "not_linked"
    assert found.teams_office_id == office.id
    mirror.apply(db, org.id)
    assert world["clark"].team_id == world["smb"].id


# ── What is not linked ───────────────────────────────────────────────────────


def test_a_link_to_a_source_that_is_gone_does_nothing(db, org, world, make_team):
    phoenix = make_team("Phoenix")
    in_directory(db, org, world["peter"])
    gone = source(db, org, "Phoenix", members=[world["peter"]])
    gone.gone_at = NOW
    link(db, org, gone, phoenix)

    assert status_of(db, org, world["peter"]).status == "not_linked"


def test_somebody_not_in_the_directory_is_said_so(db, org, world):
    assert status_of(db, org, world["peter"]).status == "not_in_m365"


def test_people_without_an_account_yet_are_counted(db, org, world, make_team):
    phoenix = make_team("Phoenix")
    src = source(db, org, "Phoenix")
    db.add(M365Member(source_id=src.id, person_external_id="somebody-new"))
    link(db, org, src, phoenix)

    assert mirror.picture(db, org.id).not_yet_here == 1


# ── Storing what was read ────────────────────────────────────────────────────


def read_of(*teams, channels=(), problems=(), read_for=None, teams_read=True):
    return structure.Structure(
        teams=list(teams), channels=list(channels), problems=list(problems),
        teams_read=teams_read,
        channels_read_for=set(read_for if read_for is not None else [t.external_id for t in teams]),
    )


def test_a_rename_in_microsoft_keeps_the_link(db, org, world, make_team):
    phoenix = make_team("Phoenix")
    structure.store(db, org.id, read_of(structure.TeamInfo("g1", "Phoenix", ["a"])), now=NOW)
    row = db.scalar(select(M365Source).where(M365Source.external_id == "g1"))
    link(db, org, row, phoenix)

    structure.store(
        db, org.id, read_of(structure.TeamInfo("g1", "Phoenix Sales", ["a"])),
        now=NOW + timedelta(days=1),
    )

    db.refresh(row)
    assert row.name == "Phoenix Sales"
    assert db.scalar(select(M365Link).where(M365Link.source_id == row.id)) is not None


def test_members_not_read_this_time_are_kept(db, org):
    structure.store(db, org.id, read_of(structure.TeamInfo("g1", "Phoenix", ["a", "b"])), now=NOW)

    structure.store(db, org.id, read_of(structure.TeamInfo("g1", "Phoenix", None)), now=NOW)

    row = db.scalar(select(M365Source).where(M365Source.external_id == "g1"))
    assert len(db.scalars(select(M365Member).where(M365Member.source_id == row.id)).all()) == 2


def test_channels_not_asked_about_are_not_gone(db, org):
    team = structure.TeamInfo("g1", "Phoenix")
    channel = structure.Channel("c1", "g1", "Closers", "private", ["a"])
    structure.store(db, org.id, read_of(team, channels=[channel]), now=NOW)

    structure.store(db, org.id, read_of(team, read_for=[]), now=NOW + timedelta(days=1))
    row = db.scalar(select(M365Source).where(M365Source.external_id == "c1"))
    assert row.gone_at is None

    structure.store(db, org.id, read_of(team), now=NOW + timedelta(days=2))
    db.refresh(row)
    assert row.gone_at is not None, "its Team's channels were read and it was not there"


def test_a_team_that_disappears_is_marked_gone_not_deleted(db, org):
    structure.store(db, org.id, read_of(structure.TeamInfo("g1", "Phoenix")), now=NOW)

    structure.store(db, org.id, read_of(), now=NOW + timedelta(days=1))

    row = db.scalar(select(M365Source).where(M365Source.external_id == "g1"))
    assert row.gone_at is not None


def test_a_failed_read_changes_nothing(db, org):
    structure.store(db, org.id, read_of(structure.TeamInfo("g1", "Phoenix")), now=NOW)

    structure.store(db, org.id, read_of(teams_read=False), now=NOW + timedelta(days=1))

    row = db.scalar(select(M365Source).where(M365Source.external_id == "g1"))
    assert row.gone_at is None


# ── Reading Graph ────────────────────────────────────────────────────────────


@pytest.fixture
def graph(monkeypatch):
    """A tenant: URL suffix → items, or a RestProblem to raise. Records asks."""
    asked: list[str] = []

    def install(pages):
        def collect(client, url, params=None):
            path = url.removeprefix(microsoft.GRAPH)
            asked.append(path)
            answer = pages.get(path, [])
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(microsoft, "token_for", lambda db, connection: "token")
        monkeypatch.setattr(microsoft, "_collect", collect)
        return asked

    return install


TENANT = {
    "/groups": [{"id": "g1", "displayName": "Phoenix"}],
    "/groups/g1/members": [{"id": "u1"}, {"id": "u2"}],
    "/teams/g1/channels": [
        {"id": "c1", "displayName": "General", "membershipType": "standard"},
        {"id": "c2", "displayName": "Closers", "membershipType": "private"},
    ],
    "/teams/g1/channels/c2/members": [{"userId": "u1"}],
}


def test_reading_everything_skips_standard_channel_members(db, connection, graph):
    asked = graph(TENANT)

    found = structure.read(db, connection)

    assert [t.members for t in found.teams] == [["u1", "u2"]]
    assert [(c.name, c.members) for c in found.channels] == [("General", None), ("Closers", ["u1"])]
    assert "/teams/g1/channels/c1/members" not in asked


def test_a_scheduled_read_asks_only_about_what_is_linked(db, connection, graph):
    asked = graph(TENANT)

    structure.read(db, connection, structure.Wanted(members_for={"c2"}, channels_for={"g1"}))

    assert "/groups/g1/members" not in asked
    assert "/teams/g1/channels/c2/members" in asked


def test_no_channel_permission_still_reads_the_teams(db, connection, graph):
    graph({**TENANT, "/teams/g1/channels": RestProblem("403", status=403)})

    found = structure.read(db, connection)

    assert [t.name for t in found.teams] == ["Phoenix"]
    assert found.problems == [structure.channels_refused("application")]
    assert found.channels_read_for == set()


def test_a_refused_permission_is_asked_once_not_per_team(db, connection, graph):
    asked = graph({
        "/groups": [{"id": "g1", "displayName": "Phoenix"}, {"id": "g2", "displayName": "Tempe"}],
        "/teams/g1/channels": RestProblem("403", status=403),
        "/teams/g2/channels": RestProblem("403", status=403),
    })

    structure.read(db, connection)

    assert [a for a in asked if a.endswith("/channels")] == ["/teams/g1/channels"]


def test_the_advice_names_the_kind_of_permission(db):
    assert "APPLICATION" in structure.channels_refused("application")
    assert "DELEGATED" in structure.channels_refused("delegated")


# ── Directory sync ───────────────────────────────────────────────────────────


@pytest.fixture
def tenant(monkeypatch):
    calls: list = []

    def install(found=None, explode=None):
        def read(db, connection, want=None):
            calls.append(want)
            if explode:
                raise explode
            return found or read_of()

        monkeypatch.setitem(directory_sync.STRUCTURE_READERS, "microsoft", read)
        return calls

    return install


def test_nothing_linked_reads_nothing(db, org, connection, tenant):
    calls = tenant()

    assert directory_sync.read_teams_structure(db, connection, now=NOW) is False
    assert calls == []


def test_a_sync_moves_nobody_unless_told(db, org, world, connection, tenant, make_team):
    org.teams_enabled = True
    phoenix = make_team("Phoenix")
    in_directory(db, org, world["peter"])
    src = source(db, org, "Phoenix", members=[world["peter"]])
    link(db, org, src, phoenix)
    tenant(read_of(structure.TeamInfo(src.external_id, "Phoenix", [f"ext-{world['peter'].id}"])))
    still_here(directory_sync, world["peter"])

    directory_sync.run(db, connection, now=NOW)
    assert world["peter"].team_id is None

    connection.directory_mirror_teams = True
    directory_sync.run(db, connection, now=NOW + timedelta(days=1))
    assert world["peter"].team_id == phoenix.id


def test_a_refused_structure_read_is_shown_not_raised(db, org, world, connection, tenant, make_team):
    org.teams_enabled = True
    link(db, org, source(db, org, "Phoenix"), make_team("Phoenix"))
    tenant(explode=RuntimeError("no"))

    assert directory_sync.read_teams_structure(db, connection, now=NOW) is False
    assert "no" in connection.teams_read_note


def still_here(module, *people):
    """Directory sync reads people first. The same people, so nobody leaves."""
    from app.directory.rules import Person

    module.READERS["microsoft"] = lambda db, connection: [
        Person(external_id=f"ext-{p.id}", email=p.email, display_name=p.full_name)
        for p in people
    ]


@pytest.fixture(autouse=True)
def _restore_people_reader():
    saved = dict(directory_sync.READERS)
    yield
    directory_sync.READERS.clear()
    directory_sync.READERS.update(saved)


# ── The page ─────────────────────────────────────────────────────────────────


def test_standard_channels_are_listed_but_not_usable(client, sign_in, db, org, world):
    sign_in(world["admin"])
    parent = source(db, org, "Phoenix")
    source(db, org, "General", kind="channel", parent=parent, membership="standard")
    source(db, org, "Closers", kind="channel", parent=parent, membership="private")

    body = client.get("/api/admin/directory/mirror").json()

    usable = {s["name"]: s["linkable"] for s in body["sources"]}
    assert usable == {"Closers": True, "General": False, "Phoenix": True}
    assert next(s for s in body["sources"] if s["name"] == "Phoenix")["standard_channels"] == 1


def test_use_as_a_team_makes_one_named_after_it(client, sign_in, db, org, world, tenant):
    sign_in(world["admin"])
    src = source(db, org, "Phoenix Sales")
    tenant()

    body = client.put(f"/api/admin/directory/mirror/sources/{src.id}", json={"use_as": "team"}).json()

    linked = next(s for s in body["sources"] if s["id"] == src.id)["link"]
    assert linked["target"] == "team" and linked["name"] == "Phoenix Sales"
    assert db.get(Team, linked["id"]).organization_id == org.id


def test_use_as_a_team_reuses_the_one_already_called_that(client, sign_in, db, org, world, tenant):
    sign_in(world["admin"])
    src = source(db, org, "smb")
    tenant()

    body = client.put(f"/api/admin/directory/mirror/sources/{src.id}", json={"use_as": "team"}).json()

    assert next(s for s in body["sources"] if s["id"] == src.id)["link"]["id"] == world["smb"].id


def test_use_as_an_office(client, sign_in, db, org, world, tenant):
    sign_in(world["admin"])
    src = source(db, org, "Tempe")
    tenant()

    body = client.put(f"/api/admin/directory/mirror/sources/{src.id}", json={"use_as": "office"}).json()

    linked = next(s for s in body["sources"] if s["id"] == src.id)["link"]
    assert linked["target"] == "office"
    assert db.get(Office, linked["id"]).name == "Tempe"


def test_a_standard_channel_cannot_be_used(client, sign_in, db, org, world):
    sign_in(world["admin"])
    parent = source(db, org, "Phoenix")
    general = source(db, org, "General", kind="channel", parent=parent, membership="standard")

    reply = client.put(f"/api/admin/directory/mirror/sources/{general.id}", json={"use_as": "team"})

    assert reply.status_code == 400


def test_one_team_follows_one_source(client, sign_in, db, org, world, tenant):
    sign_in(world["admin"])
    link(db, org, source(db, org, "Phoenix"), world["smb"])
    other = source(db, org, "Tempe")
    tenant()

    reply = client.put(
        f"/api/admin/directory/mirror/sources/{other.id}",
        json={"use_as": "team", "id": world["smb"].id},
    )

    assert reply.status_code == 409


def test_using_as_nothing_leaves_everybody_where_they_are(client, sign_in, db, org, world):
    sign_in(world["admin"])
    src = source(db, org, "SMB", members=[world["clark"]])
    link(db, org, src, world["smb"])

    client.put(f"/api/admin/directory/mirror/sources/{src.id}", json={"use_as": "nothing"})

    assert db.scalar(select(M365Link).where(M365Link.source_id == src.id)) is None
    assert world["clark"].team_id == world["smb"].id


def test_apply_from_the_page_is_audited(client, sign_in, db, org, world, make_team):
    sign_in(world["admin"])
    phoenix = make_team("Phoenix")
    in_directory(db, org, world["peter"])
    link(db, org, source(db, org, "Phoenix", members=[world["peter"]]), phoenix)

    client.post("/api/admin/directory/mirror/apply")

    assert world["peter"].team_id == phoenix.id
    assert db.scalar(select(AuditLog).where(AuditLog.action == "team.mirror_moved")) is not None


def test_follow_and_keep_from_the_page(client, sign_in, db, org, world, make_team):
    sign_in(world["admin"])
    placed(db, org, world, make_team)
    world["peter"].team_id = world["smb"].id
    db.flush()

    kept = client.post(f"/api/admin/directory/mirror/people/{world['peter'].id}/keep").json()
    assert next(p for p in kept["people"] if p["user_id"] == world["peter"].id)["status"] == "kept"

    back = client.post(f"/api/admin/directory/mirror/people/{world['peter'].id}/follow").json()
    assert next(p for p in back["people"] if p["user_id"] == world["peter"].id)["status"] == "in_step"


def test_the_comparison_shows_office_differences(client, sign_in, db, org, world):
    sign_in(world["admin"])
    here = Office(organization_id=org.id, name="Phoenix")
    tempe = Office(organization_id=org.id, name="Tempe")
    db.add_all([here, tempe])
    db.flush()
    world["smb"].office_id = here.id
    in_directory(db, org, world["clark"], office="Mesa")
    link(db, org, source(db, org, "Tempe", members=[world["clark"]]), tempe)

    body = client.get("/api/admin/directory/mirror").json()

    clark = next(p for p in body["people"] if p["user_id"] == world["clark"].id)
    assert (clark["office"], clark["teams_office"], clark["m365_office"]) == ("Phoenix", "Tempe", "Mesa")
    assert clark["office_differs_teams"] and clark["office_differs_m365"]


def test_read_from_microsoft_reads_everything(client, sign_in, db, org, world, tenant):
    sign_in(world["admin"])
    calls = tenant(read_of(structure.TeamInfo("g9", "Mesa")))

    body = client.post("/api/admin/directory/mirror/read").json()

    assert calls == [None]
    assert [s["name"] for s in body["sources"]] == ["Mesa"]
    assert body["read_at"] is not None


def test_only_an_admin(client, sign_in, world):
    sign_in(world["diana"])

    assert client.get("/api/admin/directory/mirror").status_code == 403


def test_without_directory_sync_it_says_so(client, sign_in, db, world, connection):
    sign_in(world["admin"])
    connection.directory_sync_enabled = False
    db.flush()

    assert client.get("/api/admin/directory/mirror").json()["available"] is False


def test_the_teams_list_says_what_a_team_follows(client, sign_in, db, org, world):
    sign_in(world["admin"])
    link(db, org, source(db, org, "SMB Floor"), world["smb"])

    teams = client.get("/api/teams").json()

    assert next(t for t in teams if t["id"] == world["smb"].id)["follows"] == "SMB Floor"


def test_with_teams_switched_off_a_sync_reads_nothing(db, org, world, connection, tenant, make_team):
    """Off in the Microsoft 365 box means nothing scheduled touches Teams."""
    link(db, org, source(db, org, "Phoenix"), make_team("Phoenix"))
    calls = tenant()

    assert directory_sync.read_teams_structure(db, connection, now=NOW) is False
    assert calls == []


def test_reading_by_hand_works_while_switched_off(db, org, world, connection, tenant):
    """So everything can be set up before it is switched on."""
    calls = tenant(read_of(structure.TeamInfo("g1", "Phoenix")))

    assert directory_sync.read_teams_structure(db, connection, now=NOW, everything=True) is True
    assert calls == [None]

