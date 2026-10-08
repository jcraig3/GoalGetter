"""The admin endpoints for directory sync: the switch, the rules, the decisions.

The engine underneath is tested on its own. What is left here is what an admin can
and cannot do through the API — and the two things that matter most are refusals:
**a switch that cannot work is not flipped**, and **a person the directory has
stopped returning is not approvable**.
"""

import pytest

from app.crypto import encrypt
from app.models import DirectoryPerson, DirectoryRule, OauthClient, Organization


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


@pytest.fixture
def connection(db, org):
    def _connect(*, secret="shhh", enabled=False, provider="microsoft"):
        row = OauthClient(
            organization_id=org.id,
            provider=provider,
            client_id="client",
            # Never NULL — the column does not allow it. "No secret yet" is an
            # empty string, which is what `store_client` refuses to create and
            # what a half-finished setup would leave behind.
            client_secret_encrypted=encrypt(secret) if secret else "",
            tenant_id="contoso.onmicrosoft.com",
            directory_sync_enabled=enabled,
        )
        db.add(row)
        db.flush()
        db.commit()
        return row

    return _connect


@pytest.fixture
def waiting(db, org):
    def _waiting(external_id="e1", **kwargs):
        defaults = dict(
            organization_id=org.id,
            provider="microsoft",
            external_id=external_id,
            email=f"{external_id}@acme.com",
            display_name="Sam Rivera",
            job_title="Account Executive",
            department="Sales",
            office_location="Phoenix",
            groups=[],
            enabled=True,
            status="pending",
        )
        defaults.update(kwargs)
        row = DirectoryPerson(**defaults)
        db.add(row)
        db.flush()
        db.commit()
        return row

    return _waiting


# ── Status ───────────────────────────────────────────────────────────────────


def test_the_page_says_what_could_sync_even_with_nothing_connected(signed_in):
    """So it can say "connect Microsoft to sync your people" rather than showing
    an empty screen and explaining nothing."""
    body = signed_in.get("/api/admin/directory").json()

    assert body["available"] == ["microsoft"]
    assert body["connected"] is False
    assert body["enabled"] is False


def test_a_connection_with_a_secret_reports_itself_connectable(signed_in, connection):
    connection()

    body = signed_in.get("/api/admin/directory").json()

    assert body["connected"] is True
    assert body["provider"] == "microsoft"
    assert body["enabled"] is False


def test_the_badge_counts_people_waiting_on_a_decision(signed_in, waiting):
    waiting("e1")
    waiting("e2")
    waiting("e3", status="approved")

    assert signed_in.get("/api/admin/directory").json()["pending"] == 2


# ── The switch ───────────────────────────────────────────────────────────────


def test_the_switch_cannot_be_turned_on_without_a_connection(signed_in):
    """**Enabling something that cannot work is how a feature gets called broken
    rather than unconfigured.** The message names the page where the fix is."""
    response = signed_in.put(
        "/api/admin/directory", json={"provider": "microsoft", "enabled": True}
    )

    assert response.status_code == 400
    assert "Integrations page" in response.json()["detail"]


def test_the_switch_cannot_be_turned_on_for_a_connection_with_no_secret(
    signed_in, connection
):
    connection(secret=None)

    response = signed_in.put(
        "/api/admin/directory", json={"provider": "microsoft", "enabled": True}
    )

    assert response.status_code == 400


def test_the_switch_turns_on_for_a_real_connection(signed_in, connection):
    connection()

    response = signed_in.put(
        "/api/admin/directory", json={"provider": "microsoft", "enabled": True}
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_the_switch_turns_off_without_needing_a_working_connection(
    signed_in, connection, db
):
    """A deployment whose credential was revoked must still be able to stop the
    sync, or the only way out is the database."""
    row = connection(enabled=True)
    row.client_secret_encrypted = ""
    db.commit()

    response = signed_in.put(
        "/api/admin/directory", json={"provider": "microsoft", "enabled": False}
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_a_provider_this_build_cannot_read_is_refused(signed_in):
    response = signed_in.put(
        "/api/admin/directory", json={"provider": "workday", "enabled": True}
    )

    assert response.status_code == 400
    assert "workday" in response.json()["detail"]


def test_syncing_now_needs_the_switch_on(signed_in, connection):
    connection()

    response = signed_in.post("/api/admin/directory/sync")

    assert response.status_code == 400
    assert "not switched on" in response.json()["detail"]


# ── Rules ────────────────────────────────────────────────────────────────────


def test_a_rule_is_added_and_read_back(signed_in, make_team):
    sales = make_team("Sales")

    response = signed_in.post(
        "/api/admin/directory/rules",
        json={"department": "Sales", "role": "manager", "team_id": sales.id},
    )

    assert response.status_code == 201
    rules = response.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["department"] == "Sales"
    assert rules[0]["team_id"] == sales.id


def test_a_rule_with_no_conditions_at_all_is_allowed(signed_in):
    """It is the catch-all — how a company says "everyone is an agent unless
    something more specific applies" — so refusing it would remove the simplest
    useful rule there is."""
    response = signed_in.post("/api/admin/directory/rules", json={"role": "agent"})

    assert response.status_code == 201


def test_a_role_that_is_not_a_role_is_refused_by_name(signed_in):
    """A rule naming a nonexistent role would fail silently at apply time, days
    later, for everybody it matched."""
    response = signed_in.post(
        "/api/admin/directory/rules", json={"department": "Sales", "role": "wizard"}
    )

    assert response.status_code == 400
    assert "wizard" in response.json()["detail"]


def test_two_rules_with_the_same_conditions_are_reported_as_a_clash(signed_in):
    """The second is unreachable, and an admin cannot see that by reading the list
    — so they are told while still on the screen where they wrote it."""
    signed_in.post("/api/admin/directory/rules", json={"department": "Sales"})
    response = signed_in.post(
        "/api/admin/directory/rules", json={"department": "sales", "role": "manager"}
    )

    assert response.json()["clashes"] == [[0, 1]]


def test_rules_that_differ_are_not_reported_as_a_clash(signed_in):
    signed_in.post("/api/admin/directory/rules", json={"department": "Sales"})
    response = signed_in.post(
        "/api/admin/directory/rules", json={"department": "Support"}
    )

    assert response.json()["clashes"] == []


def test_a_rule_is_edited_in_place(signed_in):
    made = signed_in.post(
        "/api/admin/directory/rules", json={"department": "Sales"}
    ).json()["rules"][0]

    response = signed_in.put(
        f"/api/admin/directory/rules/{made['id']}", json={"department": "Support"}
    )

    assert response.json()["rules"][0]["department"] == "Support"


def test_deleting_a_rule_moves_nobody(signed_in, db, org, make_team, make_user):
    """**The rules only ever propose.** A deletion that silently reassigned fifty
    people would be the loudest possible version of the thing this whole design
    exists to prevent."""
    sales = make_team("Sales")
    person = make_user("agent", sales)
    made = signed_in.post(
        "/api/admin/directory/rules",
        json={"department": "Sales", "team_id": sales.id},
    ).json()["rules"][0]

    signed_in.delete(f"/api/admin/directory/rules/{made['id']}")

    db.expire_all()
    assert person.team_id == sales.id
    assert db.query(DirectoryRule).filter_by(organization_id=org.id).count() == 0


def test_a_rule_from_another_organization_is_not_found(signed_in, db):
    from app.models import Organization

    other = Organization(name="Other")
    db.add(other)
    db.flush()
    theirs = DirectoryRule(organization_id=other.id, department="Sales")
    db.add(theirs)
    db.commit()

    assert signed_in.delete(f"/api/admin/directory/rules/{theirs.id}").status_code == 404


# ── People ───────────────────────────────────────────────────────────────────


def test_the_pending_list_shows_what_the_rules_would_do(signed_in, waiting, make_team):
    """**Shown before the button is pressed, not after.** An admin approving two
    hundred people should be able to see where they will land."""
    sales = make_team("Sales")
    signed_in.post(
        "/api/admin/directory/rules",
        json={"department": "Sales", "role": "manager", "team_id": sales.id},
    )
    waiting()

    found = signed_in.get("/api/admin/directory/people").json()

    assert found[0]["would_be_role"] == "manager"
    assert found[0]["would_be_team_id"] == sales.id


def test_somebody_no_rule_places_shows_as_unassigned(signed_in, waiting):
    waiting()

    found = signed_in.get("/api/admin/directory/people").json()

    assert found[0]["would_be_team_id"] is None
    assert found[0]["would_be_role"] == "agent"


def test_the_list_can_be_asked_for_any_status(signed_in, waiting):
    waiting("e1")
    waiting("e2", status="declined")

    declined = signed_in.get("/api/admin/directory/people?status=declined").json()

    assert [p["external_id"] for p in declined] == ["e2"]


def test_a_status_that_is_not_a_status_is_refused_by_name(signed_in):
    response = signed_in.get("/api/admin/directory/people?status=maybe")

    assert response.status_code == 400
    assert "maybe" in response.json()["detail"]


# ── Deciding ─────────────────────────────────────────────────────────────────


def test_people_are_approved_in_bulk(signed_in, waiting, db):
    """**The first use is two hundred people at once.** One row at a time is the
    chore that makes somebody give up and keep typing names by hand."""
    first, second = waiting("e1"), waiting("e2")

    response = signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [first.id, second.id], "status": "approved"},
    )

    assert response.status_code == 200
    db.expire_all()
    assert first.status == "approved"
    assert second.status == "approved"


def test_approving_creates_the_account_now(signed_in, waiting, db, org):
    """**This asserted the opposite until it met a real tenant.**

    Accounts used to be created only by the next sync pass — one path from
    approved to account, with the per-person error handling on it, which was the
    right instinct. What it missed is that a daily sync puts twenty-four hours
    between the two: an admin approves four hundred people, the pending queue
    empties, the People list does not change, and the only available reading is
    that they vanished.

    The instinct survives by calling the same function the sync calls rather than
    a second copy, so there is still one path — and the sync still sweeps up
    anybody this could not place.
    """
    from app.models import UserAccount

    row = waiting()
    before = db.query(UserAccount).filter_by(organization_id=org.id).count()

    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [row.id], "status": "approved"},
    )

    db.expire_all()
    assert db.query(UserAccount).filter_by(organization_id=org.id).count() == before + 1
    # And linked, so the next sync does not propose them all over again.
    assert db.get(DirectoryPerson, row.id).user_account_id is not None


def test_declining_somebody_creates_nothing(signed_in, waiting, db, org):
    """The other half, which is what makes the assertion above mean something."""
    from app.models import UserAccount

    row = waiting()
    before = db.query(UserAccount).filter_by(organization_id=org.id).count()

    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [row.id], "status": "declined"},
    )

    assert db.query(UserAccount).filter_by(organization_id=org.id).count() == before


def test_somebody_the_directory_stopped_returning_cannot_be_approved(
    signed_in, waiting, db
):
    """**They are gone.** Approving them would create an account for a person who
    no longer works there, and the next sync would archive it again — a button
    that lies."""
    row = waiting(status="archived")

    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [row.id], "status": "approved"},
    )

    db.expire_all()
    assert row.status == "archived"


def test_declining_clears_the_reason_they_were_waiting(signed_in, waiting, db):
    row = waiting(pending_reason="Their job details changed")

    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [row.id], "status": "declined"},
    )

    db.expire_all()
    assert row.pending_reason == ""


def test_a_decision_that_is_not_one_is_refused(signed_in, waiting):
    """`archived` is deliberately not decidable: it is the directory's to say."""
    row = waiting()

    response = signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [row.id], "status": "archived"},
    )

    assert response.status_code == 400
    assert "archived" in response.json()["detail"]


def test_people_from_another_organization_are_not_touched(signed_in, db, waiting):
    from app.models import Organization

    other = Organization(name="Other")
    db.add(other)
    db.flush()
    theirs = DirectoryPerson(
        organization_id=other.id,
        provider="microsoft",
        external_id="x1",
        email="x@other.com",
        groups=[],
        status="pending",
    )
    db.add(theirs)
    db.commit()

    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [theirs.id], "status": "approved"},
    )

    db.expire_all()
    assert theirs.status == "pending"


# ── Who may do any of this ───────────────────────────────────────────────────


def test_an_agent_cannot_read_or_change_anything(client, db, make_user, sign_in):
    agent = make_user("agent")
    sign_in(agent)
    db.commit()

    assert client.get("/api/admin/directory").status_code == 403
    assert client.get("/api/admin/directory/rules").status_code == 403
    assert client.get("/api/admin/directory/people").status_code == 403
    assert (
        client.put(
            "/api/admin/directory", json={"provider": "microsoft", "enabled": True}
        ).status_code
        == 403
    )


# ── How often, and what the dropdowns offer ──────────────────────────────────


def test_the_frequency_is_reported_so_the_panel_can_show_it(signed_in, connection):
    connection(enabled=True)

    body = signed_in.get("/api/admin/directory").json()

    assert body["sync_hours"] == 24


def test_a_deployment_with_nothing_connected_still_gets_a_number(signed_in):
    """Rather than a zero the page would then have to explain. What it shows is
    what *would* happen once something is connected."""
    assert signed_in.get("/api/admin/directory").json()["sync_hours"] == 24


def test_the_frequency_can_be_changed(signed_in, connection, db):
    row = connection(enabled=True)

    body = signed_in.put(
        "/api/admin/directory",
        json={"provider": "microsoft", "enabled": True, "sync_hours": 6},
    ).json()

    assert body["sync_hours"] == 6
    db.expire_all()
    assert row.directory_sync_hours == 6


def test_flicking_the_switch_does_not_reset_the_frequency(signed_in, connection, db):
    """**Omitted means "leave it alone".** Otherwise switching sync off to stop it
    for an afternoon, then back on, would quietly return an hourly connection to
    daily — and nobody would look at the frequency again to notice."""
    row = connection(enabled=True)
    signed_in.put(
        "/api/admin/directory",
        json={"provider": "microsoft", "enabled": True, "sync_hours": 1},
    )

    signed_in.put("/api/admin/directory", json={"provider": "microsoft", "enabled": False})
    body = signed_in.put(
        "/api/admin/directory", json={"provider": "microsoft", "enabled": True}
    ).json()

    assert body["sync_hours"] == 1
    db.expire_all()
    assert row.directory_sync_hours == 1


@pytest.mark.parametrize("hours", [0, -1, 100_000])
def test_an_impossible_frequency_is_refused(signed_in, connection, hours):
    """Bounded at the edge rather than clamped silently. Below an hour this stops
    being a schedule and becomes polling somebody else's rate-limited API."""
    connection(enabled=True)

    response = signed_in.put(
        "/api/admin/directory",
        json={"provider": "microsoft", "enabled": True, "sync_hours": hours},
    )

    assert response.status_code == 422


def test_the_dropdowns_offer_what_the_directory_actually_reported(
    signed_in, connection, waiting
):
    """**The failure this removes.** A rule is a string comparison against what the
    provider sent, so `Sales` typed against a tenant that says `Sales Team` saves
    cleanly and matches nobody, with nothing on screen saying so."""
    connection(enabled=True)
    waiting("e1", department="Sales", job_title="AE", office_location="Phoenix")
    waiting("e2", department="Sales", job_title="SDR", office_location="Dallas")
    waiting("e3", department="Support", job_title="AE", office_location="Phoenix")

    body = signed_in.get("/api/admin/directory/values").json()

    # Commonest first, so the useful answer is at the top of a long list.
    assert body["department"] == [
        {"value": "Sales", "people": 2},
        {"value": "Support", "people": 1},
    ]
    assert body["office"] == [
        {"value": "Phoenix", "people": 2},
        {"value": "Dallas", "people": 1},
    ]
    assert {v["value"] for v in body["job_title"]} == {"AE", "SDR"}


def test_group_names_are_counted_across_everybody_who_is_in_them(
    signed_in, connection, waiting
):
    """Groups are a JSONB array per person rather than a column, so this is the one
    of the four that cannot be a GROUP BY."""
    connection(enabled=True)
    waiting("e1", groups=["Phoenix Sales", "All Staff"])
    waiting("e2", groups=["All Staff"])

    body = signed_in.get("/api/admin/directory/values").json()

    assert body["group"] == [
        {"value": "All Staff", "people": 2},
        {"value": "Phoenix Sales", "people": 1},
    ]


def test_blank_values_are_not_offered(signed_in, connection, waiting):
    """A tenant is full of accounts with no department. Offering "" as something to
    match on would be offering a rule that reads as "any" and behaves as "only the
    people nobody filled in"."""
    connection(enabled=True)
    waiting("e1", department="Sales")
    waiting("e2", department="")
    waiting("e3", department="   ")

    body = signed_in.get("/api/admin/directory/values").json()

    assert body["department"] == [{"value": "Sales", "people": 1}]


def test_one_organizations_values_do_not_leak_into_anothers(
    signed_in, connection, waiting, db
):
    """The rule this whole table is scoped by, asserted where it would be easiest
    to forget it — a new endpoint doing its own aggregation."""
    connection(enabled=True)
    waiting("e1", department="Sales")

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(
        DirectoryPerson(
            organization_id=other.id,
            provider="microsoft",
            external_id="theirs",
            email="them@other.com",
            display_name="Them",
            job_title="",
            department="Somebody Elses Department",
            office_location="",
            groups=[],
            enabled=True,
            status="pending",
        )
    )
    db.commit()

    body = signed_in.get("/api/admin/directory/values").json()

    assert body["department"] == [{"value": "Sales", "people": 1}]


def test_an_agent_cannot_read_the_directorys_values(client, db, make_user, sign_in):
    """It is a list of every department and group in the company, which is not an
    agent's business."""
    sign_in(make_user("agent"))
    db.commit()

    assert client.get("/api/admin/directory/values").status_code == 403


# ── Which way it signs in ────────────────────────────────────────────────────
#
# Two modes, and the point of having both is that they fail differently: the
# application acts as itself and needs a Privileged Role Administrator to consent
# once; a service account needs nobody senior and stops when it is disabled.


def test_a_fresh_deployment_reports_the_application_mode(signed_in):
    """The default, and the better shape — nothing to expire, nobody to offboard.
    A deployment that cannot reach a senior admin picks the other at setup."""
    assert signed_in.get("/api/admin/directory").json()["auth_mode"] == "application"


def test_the_application_mode_needs_no_account(signed_in, connection):
    """`account_required` is what stops the panel offering a sign-in for a mode
    that has nothing to sign in — and what stops the sync switch being disabled
    waiting for one that will never come."""
    connection(enabled=True)

    body = signed_in.get("/api/admin/directory").json()

    assert body["account_required"] is False
    assert body["account_connected"] is False


def test_the_delegated_mode_says_it_needs_an_account(signed_in, connection, db):
    row = connection(enabled=True)
    row.directory_auth_mode = "delegated"
    db.commit()

    body = signed_in.get("/api/admin/directory").json()

    assert body["auth_mode"] == "delegated"
    assert body["account_required"] is True
    assert body["account_connected"] is False


def test_signing_in_an_account_is_refused_in_application_mode(signed_in, connection):
    """There is nothing to sign in, and offering it would produce a stored token
    nothing ever reads — which is worse than a refusal, because it looks done."""
    connection(enabled=True)

    response = signed_in.post("/api/admin/directory/account?provider=microsoft")

    assert response.status_code == 409
    assert "acts as the application" in response.json()["detail"]


def test_delegated_mail_will_not_switch_on_without_an_account(
    signed_in, connection, db
):
    """In that mode mail goes out *as* the signed-in account, so switching it on
    without one is a setting that looks configured and fails on the first
    invitation."""
    row = connection(enabled=True)
    row.directory_auth_mode = "delegated"
    db.commit()

    response = signed_in.put(
        "/api/admin/directory/mail",
        json={"provider": "microsoft", "enabled": True, "mail_from": ""},
    )

    assert response.status_code == 400
    assert "Sign in the account" in response.json()["detail"]


def test_application_mail_will_not_switch_on_without_a_mailbox(signed_in, connection):
    """The mirror image: an application has no mailbox of its own, so there is
    nothing to fall back to and a guess would fail on an address nobody chose."""
    connection(enabled=True)

    response = signed_in.put(
        "/api/admin/directory/mail",
        json={"provider": "microsoft", "enabled": True, "mail_from": ""},
    )

    assert response.status_code == 400
    assert "Name the mailbox" in response.json()["detail"]


def test_the_licence_filter_is_off_until_asked_for(signed_in, connection):
    connection(enabled=True)

    assert signed_in.get("/api/admin/directory").json()["ignore_unlicensed"] is False


def test_the_licence_filter_can_be_turned_on(signed_in, connection, db):
    row = connection(enabled=True)

    body = signed_in.put(
        "/api/admin/directory",
        json={"provider": "microsoft", "enabled": True, "ignore_unlicensed": True},
    ).json()

    assert body["ignore_unlicensed"] is True
    db.expire_all()
    assert row.directory_ignore_unlicensed is True


def test_flicking_the_switch_does_not_undo_the_licence_filter(
    signed_in, connection, db
):
    """Same rule the frequency already had: omitted means "leave it alone". A
    filter silently reset by switching sync off for an afternoon is a queue that
    fills with service accounts and nobody knowing why."""
    row = connection(enabled=True)
    signed_in.put(
        "/api/admin/directory",
        json={"provider": "microsoft", "enabled": True, "ignore_unlicensed": True},
    )

    signed_in.put("/api/admin/directory", json={"provider": "microsoft", "enabled": False})
    body = signed_in.put(
        "/api/admin/directory", json={"provider": "microsoft", "enabled": True}
    ).json()

    assert body["ignore_unlicensed"] is True
    db.expire_all()
    assert row.directory_ignore_unlicensed is True


# ── Testing the mail setting ─────────────────────────────────────────────────


def test_a_test_send_goes_through_microsoft_only(signed_in, connection, db, monkeypatch):
    """**Deliberately not `mail.send`.** That one falls back to SMTP, which is
    right for an invitation and wrong for a test: a green result that came from
    the fallback would report this setting as working when it does not."""
    from app import mail, mail_graph

    row = connection()
    row.mail_from = "noreply@acme.com"
    db.commit()

    seen = {}
    monkeypatch.setattr(
        mail_graph, "send",
        lambda db, c, *, to, subject, body: (
            seen.update(to=to, sender=c.mail_from) or mail_graph.Sent(ok=True, detail=f"Sent to {to}.")
        ),
    )
    # If the endpoint ever reached for the general sender, this would fire.
    monkeypatch.setattr(
        mail, "send",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("used the SMTP-capable path")),
    )

    body = signed_in.post(
        "/api/admin/directory/mail/test",
        json={"provider": "microsoft", "to": "someone@example.com"},
    ).json()

    assert body["ok"] is True
    assert seen["to"] == "someone@example.com"


def test_a_test_send_needs_a_mailbox_first(signed_in, connection, db):
    """An application has no mailbox of its own, so there is nothing to send as
    and nothing sensible to guess."""
    row = connection()
    row.mail_from = ""
    db.commit()

    response = signed_in.post(
        "/api/admin/directory/mail/test",
        json={"provider": "microsoft", "to": "someone@example.com"},
    )

    assert response.status_code == 400
    assert "Name the mailbox" in response.json()["detail"]


def test_a_test_send_works_before_sending_is_switched_on(
    signed_in, connection, db, monkeypatch
):
    """"Does this work?" is a question asked *before* committing to it, so the
    test must not require the switch it is meant to inform."""
    from app import mail_graph

    row = connection()
    row.mail_from = "noreply@acme.com"
    row.mail_enabled = False
    db.commit()
    monkeypatch.setattr(
        mail_graph, "send",
        lambda db, c, *, to, subject, body: mail_graph.Sent(ok=True, detail="Sent."),
    )

    body = signed_in.post(
        "/api/admin/directory/mail/test",
        json={"provider": "microsoft", "to": "someone@example.com"},
    ).json()

    assert body["ok"] is True


def test_a_test_send_refuses_a_malformed_address(signed_in, connection):
    connection()

    response = signed_in.post(
        "/api/admin/directory/mail/test",
        json={"provider": "microsoft", "to": "not-an-address"},
    )

    assert response.status_code == 422


# ── Adding somebody hidden ───────────────────────────────────────────────────


def test_adding_hidden_creates_a_real_account(signed_in, waiting, db, org):
    """**An addition, not a refusal.** Most of a directory belongs here: a
    company of four hundred has contractors, service accounts and departments
    that do not sell. Declining them was the only tool for that, and it creates
    nothing at all — so they exist nowhere and cannot be found, photographed or
    moved onto a team later."""
    from sqlalchemy import select

    from app.models import UserAccount

    person = waiting("e1")

    response = signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [person.id], "status": "hidden"},
    )

    assert response.status_code == 200
    db.expire_all()
    account = db.scalars(
        select(UserAccount).where(UserAccount.email == person.email)
    ).first()
    assert account is not None


def test_a_hidden_addition_is_hidden_from_the_first_moment(
    signed_in, waiting, db, org
):
    """**Not created visible and hidden a moment later.** That account is on a
    leaderboard for that moment, and on a wall if the timing is unlucky."""
    from sqlalchemy import select

    from app.models import UserAccount

    person = waiting("e1")
    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [person.id], "status": "hidden"},
    )

    db.expire_all()
    account = db.scalars(
        select(UserAccount).where(UserAccount.email == person.email)
    ).first()
    assert account.hidden_at is not None


def test_they_show_up_under_hidden_in_people(signed_in, waiting, db):
    person = waiting("e1")
    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [person.id], "status": "hidden"},
    )

    hidden = signed_in.get("/api/users?roster=hidden").json()

    assert person.email in [u["email"] for u in hidden]


def test_adding_normally_is_not_hidden(signed_in, waiting, db, org):
    """The other half of the pair, so a mix-up in either direction is caught."""
    from sqlalchemy import select

    from app.models import UserAccount

    person = waiting("e1")
    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [person.id], "status": "approved"},
    )

    db.expire_all()
    account = db.scalars(
        select(UserAccount).where(UserAccount.email == person.email)
    ).first()
    assert account.hidden_at is None


def test_the_decision_survives_the_next_sync(signed_in, waiting, db):
    """Like every other decision. Without it, somebody added hidden would be
    re-proposed every hour for ever."""
    from app.models.directory import DECIDED

    assert "hidden" in DECIDED


def test_declining_still_creates_nothing(signed_in, waiting, db, org):
    """It is kept, and it is the rarer answer — for somebody who should not be
    in the roster at all."""
    from sqlalchemy import select

    from app.models import UserAccount

    person = waiting("e1")
    signed_in.post(
        "/api/admin/directory/people/decide",
        json={"ids": [person.id], "status": "declined"},
    )

    db.expire_all()
    assert (
        db.scalars(
            select(UserAccount).where(UserAccount.email == person.email)
        ).first()
        is None
    )
