"""Pairing a television with a four-character code.

**Typing a display URL with a remote control is the worst part of setting one
up**, and it matters more here than anywhere else: a hosted product can email
the link to a laptop, and a self-hosted wall is often a television on a network
with no mail client on it.

The security shape is the thing worth testing. A code is guessable by design —
it has to be typeable with four arrow keys — so it authenticates nothing. The
screen keeps a long secret from the moment it asks, and that is what reads the
token back.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import pairing
from app.models import DisplayPairing


@pytest.fixture
def world(db, org, make_team, make_user):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
    }


@pytest.fixture
def channel(client, world, sign_in):
    sign_in(world["admin"])
    return client.post("/api/channels", json={"name": "Floor"}).json()


def start(client):
    """A screen asks for a code, with no account of any kind."""
    client.cookies.clear()
    reply = client.post("/api/displays/pair/start")
    assert reply.status_code == 201, reply.json()
    return reply.json()


# -- The code itself ---------------------------------------------------------


def test_the_alphabet_has_nothing_anybody_could_misread():
    """Every character that can be misread is a support call: 0 and O, 1 and I
    and L, 5 and S, 8 and B."""
    for character in "01ILOS8B":
        assert character not in pairing.ALPHABET


def test_no_character_appears_twice():
    """A duplicate would quietly bias the codes toward it — and this caught a
    typo that did exactly that."""
    assert len(set(pairing.ALPHABET)) == len(pairing.ALPHABET)


def test_a_code_is_four_characters_from_that_alphabet():
    code = pairing.new_code()

    assert len(code) == pairing.CODE_LENGTH
    assert all(c in pairing.ALPHABET for c in code)


def test_what_somebody_types_is_read_as_what_they_meant():
    """A person reading four characters aloud says them in pairs and types them
    that way."""
    assert pairing.normalise(" ab cd ") == "ABCD"


# -- Asking, claiming, collecting --------------------------------------------


def test_a_screen_can_ask_without_an_account(client, db):
    """A television has none. This is the one open endpoint in the product."""
    body = start(client)

    assert len(body["code"]) == pairing.CODE_LENGTH
    assert body["secret"]
    assert body["expires_in_seconds"] == 600


def test_it_is_waiting_until_somebody_claims_it(client, db):
    body = start(client)

    assert client.get(f"/api/displays/pair/{body['secret']}").status_code == 204


def test_an_admin_claims_it_and_the_screen_collects(
    client, db, world, sign_in, channel
):
    body = start(client)

    sign_in(world["admin"])
    claimed = client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Stairs TV", "channel_id": channel["id"]},
    )
    assert claimed.status_code == 201, claimed.json()

    client.cookies.clear()
    collected = client.get(f"/api/displays/pair/{body['secret']}")

    assert collected.status_code == 200
    assert collected.json()["url"].endswith(claimed.json()["url"].split("/")[-1])


def test_the_code_can_be_typed_however_it_is_read(
    client, db, world, sign_in, channel
):
    body = start(client)

    sign_in(world["admin"])
    reply = client.post(
        "/api/displays/pair",
        json={
            "code": f" {body['code'].lower()} ",
            "name": "Stairs TV",
            "channel_id": channel["id"],
        },
    )

    assert reply.status_code == 201, reply.json()


def test_what_it_makes_is_an_ordinary_display(
    client, db, world, sign_in, channel
):
    """**Pairing is a way of delivering the URL**, not a second kind of
    display: same token, same revocation, same everything."""
    body = start(client)
    sign_in(world["admin"])
    client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Stairs TV", "channel_id": channel["id"]},
    )

    listed = client.get("/api/displays").json()

    assert [d["name"] for d in listed] == ["Stairs TV"]


# -- What it refuses ---------------------------------------------------------


def test_a_manager_cannot_claim_one(client, db, world, sign_in, channel):
    """A display URL is a standing credential anybody in the room can read."""
    body = start(client)

    sign_in(world["manager"])
    reply = client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Stairs TV", "channel_id": channel["id"]},
    )

    assert reply.status_code == 403


def test_a_code_nobody_is_showing_is_refused_with_advice(
    client, db, world, sign_in, channel
):
    sign_in(world["admin"])

    reply = client.post(
        "/api/displays/pair",
        json={"code": "ZZZZ", "name": "Stairs TV", "channel_id": channel["id"]},
    )

    assert reply.status_code == 404
    assert "ten minutes" in reply.json()["detail"]


def test_a_code_cannot_be_claimed_twice(client, db, world, sign_in, channel):
    """Otherwise two televisions would answer to one code, and the second would
    quietly take over the first."""
    body = start(client)
    sign_in(world["admin"])
    client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "First", "channel_id": channel["id"]},
    )

    again = client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Second", "channel_id": channel["id"]},
    )

    assert again.status_code == 404


def test_an_expired_code_cannot_be_claimed(client, db, world, sign_in, channel):
    body = start(client)
    row = db.scalars(select(DisplayPairing)).first()
    row.created_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    sign_in(world["admin"])
    reply = client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Stairs TV", "channel_id": channel["id"]},
    )

    assert reply.status_code == 404


def test_an_expired_pairing_tells_the_screen_to_ask_again(client, db):
    """404 rather than 204: the screen should show a fresh code instead of
    waiting for one that will never come."""
    body = start(client)
    row = db.scalars(select(DisplayPairing)).first()
    row.created_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    assert client.get(f"/api/displays/pair/{body['secret']}").status_code == 404


def test_the_code_does_not_read_the_token_back(client, db, world, sign_in, channel):
    """**The property the whole design rests on.** Four characters are
    guessable — they have to be typeable with a remote — so guessing one lets
    somebody claim a pairing they cannot then read."""
    body = start(client)
    sign_in(world["admin"])
    client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Stairs TV", "channel_id": channel["id"]},
    )

    client.cookies.clear()
    assert client.get(f"/api/displays/pair/{body['code']}").status_code == 404


def test_another_organizations_channel_is_not_found(
    client, db, world, sign_in, channel
):
    body = start(client)
    sign_in(world["admin"])

    reply = client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Stairs TV", "channel_id": 999_999},
    )

    assert reply.status_code == 404


# -- Housekeeping ------------------------------------------------------------


def test_starting_one_sweeps_what_expired(client, db):
    """Swept where somebody is already writing, and it is what keeps the cap
    from being reached by abandoned screens."""
    start(client)
    row = db.scalars(select(DisplayPairing)).first()
    row.created_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()

    start(client)

    assert db.scalars(select(DisplayPairing)).all().__len__() == 1


def test_too_many_waiting_screens_is_refused(client, db, monkeypatch):
    """**A bound, not a rate limit.** The failure worth preventing is somebody
    filling the code space so the four characters an admin reads belong to a
    screen they do not own."""
    monkeypatch.setattr(pairing, "MAX_WAITING", 2)
    start(client)
    start(client)

    client.cookies.clear()
    reply = client.post("/api/displays/pair/start")

    assert reply.status_code == 429


def test_two_waiting_screens_never_share_a_code(client, db):
    codes = {start(client)["code"] for _ in range(12)}

    assert len(codes) == 12


# -- Reassigning and reloading -----------------------------------------------


def paired(client, db, world, sign_in, channel):
    """A display, made the pairing way so both paths are exercised."""
    body = start(client)
    sign_in(world["admin"])
    return client.post(
        "/api/displays/pair",
        json={"code": body["code"], "name": "Stairs TV", "channel_id": channel["id"]},
    ).json()


def test_a_screen_can_be_pointed_somewhere_else(
    client, db, world, sign_in, channel
):
    """**Reassigning beats revoking and re-pairing.** The token was never the
    thing that was wrong, so it does not need replacing — and the screen picks
    the new channel up on its next poll, with nobody in the room."""
    display = paired(client, db, world, sign_in, channel)
    other = client.post("/api/channels", json={"name": "Lobby"}).json()

    reply = client.patch(
        f"/api/displays/{display['id']}", json={"channel_id": other["id"]}
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["channel_id"] == other["id"]


def test_the_url_survives_being_reassigned(client, db, world, sign_in, channel):
    """Which is the whole point: a television that has to be re-typed has not
    been reassigned, it has been replaced."""
    display = paired(client, db, world, sign_in, channel)
    other = client.post("/api/channels", json={"name": "Lobby"}).json()

    moved = client.patch(
        f"/api/displays/{display['id']}", json={"channel_id": other["id"]}
    ).json()

    assert moved["url"] == display["url"]


def test_another_organizations_channel_cannot_be_assigned(
    client, db, world, sign_in, channel
):
    display = paired(client, db, world, sign_in, channel)

    reply = client.patch(
        f"/api/displays/{display['id']}", json={"channel_id": 999_999}
    )

    assert reply.status_code == 404


def test_a_manager_cannot_move_a_screen(client, db, world, sign_in, channel):
    display = paired(client, db, world, sign_in, channel)
    other = client.post("/api/channels", json={"name": "Lobby"}).json()

    sign_in(world["manager"])
    reply = client.patch(
        f"/api/displays/{display['id']}", json={"channel_id": other["id"]}
    )

    assert reply.status_code == 403


def test_the_feed_carries_no_reload_until_somebody_asks(
    client, db, world, sign_in, channel
):
    """Null is the ordinary case, which is why the screen remembers what it
    first saw rather than treating null as "no"."""
    display = paired(client, db, world, sign_in, channel)
    token = display["url"].rsplit("/", 1)[-1]
    client.cookies.clear()

    assert client.get(f"/api/display/{token}").json()["reload_at"] is None


def test_asking_for_a_reload_shows_up_in_the_feed(
    client, db, world, sign_in, channel
):
    """**For the browser open since a deploy three weeks ago**, and the one
    that has wedged. Both are on a wall somebody would need a ladder for."""
    display = paired(client, db, world, sign_in, channel)
    client.post(f"/api/displays/{display['id']}/reload")

    token = display["url"].rsplit("/", 1)[-1]
    client.cookies.clear()

    assert client.get(f"/api/display/{token}").json()["reload_at"] is not None


def test_a_manager_cannot_reload_a_screen(client, db, world, sign_in, channel):
    display = paired(client, db, world, sign_in, channel)

    sign_in(world["manager"])

    assert (
        client.post(f"/api/displays/{display['id']}/reload").status_code == 403
    )
