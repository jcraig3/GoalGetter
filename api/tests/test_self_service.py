"""What an agent may set about themselves.

Three things about somebody are theirs rather than the roster's — their
photograph, their details, and the clip that plays when they win. Until now the
answer to "may they set it" was decided in code and the same for every
deployment.

It is not the same for every deployment. A company with HR headshots wants one
uniform set of photographs; a floor that has heard one person's walk-up song
nine hundred times wants a manager to choose them. Most places want neither,
which is why every switch defaults to on.
"""

import io

import pytest
from PIL import Image


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 400), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def world(db, org, make_team, make_user):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
    }


def switch(client, name, on):
    reply = client.patch("/api/organization", json={name: on})
    assert reply.status_code == 200, reply.json()
    return reply


# -- The defaults ------------------------------------------------------------


def test_everything_is_open_to_begin_with(client, db, world, sign_in):
    """Most deployments want what the product did before there was a switch."""
    sign_in(world["admin"])

    body = client.get("/api/organization").json()

    assert body["self_photo"] is True
    assert body["self_details"] is True
    assert body["self_walkup"] is True


# -- Photographs -------------------------------------------------------------


def test_an_agent_can_set_their_own_photo_by_default(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = client.post(f"/api/users/{world['peter'].id}/photo", content=png())

    assert reply.status_code == 200, reply.json()


def test_the_switch_closes_it(client, db, world, sign_in):
    sign_in(world["admin"])
    switch(client, "self_photo", False)

    sign_in(world["peter"])
    reply = client.post(f"/api/users/{world['peter'].id}/photo", content=png())

    assert reply.status_code == 403
    assert "turned off" in reply.json()["detail"]


def test_a_manager_is_never_bound_by_it(client, db, world, sign_in):
    """**Agents only.** A manager can already set anybody's, so locking them
    out of their own would be a rule with no purpose — and locking an admin out
    of their own photograph is a support call rather than a policy."""
    sign_in(world["admin"])
    switch(client, "self_photo", False)

    sign_in(world["manager"])
    reply = client.post(f"/api/users/{world['manager'].id}/photo", content=png())

    assert reply.status_code == 200, reply.json()


def test_a_manager_can_still_set_it_for_the_agent(client, db, world, sign_in):
    """Which is the whole point of closing it: the photographs still happen,
    somebody else chooses them."""
    sign_in(world["admin"])
    switch(client, "self_photo", False)

    sign_in(world["manager"])
    reply = client.post(f"/api/users/{world['peter'].id}/photo", content=png())

    assert reply.status_code == 200, reply.json()


# -- Details -----------------------------------------------------------------


def test_details_can_be_closed(client, db, world, sign_in):
    sign_in(world["admin"])
    switch(client, "self_details", False)

    sign_in(world["peter"])
    reply = client.patch(
        f"/api/users/{world['peter'].id}/profile", json={"nickname": "Spidey"}
    )

    assert reply.status_code == 403
    assert "details" in reply.json()["detail"]


def test_closing_details_does_not_close_photographs(client, db, world, sign_in):
    """Three switches, not one: a company wanting uniform headshots has said
    nothing about nicknames."""
    sign_in(world["admin"])
    switch(client, "self_details", False)

    sign_in(world["peter"])
    reply = client.post(f"/api/users/{world['peter'].id}/photo", content=png())

    assert reply.status_code == 200, reply.json()


# -- Walk-up media -----------------------------------------------------------


def test_walkup_can_be_closed(client, db, world, sign_in):
    sign_in(world["admin"])
    switch(client, "self_walkup", False)

    sign_in(world["peter"])
    reply = client.put(
        "/api/me/walkup", json={"url": "https://youtu.be/dQw4w9WgXcQ"}
    )

    assert reply.status_code == 403
    assert "walk-up" in reply.json()["detail"]


def test_reading_your_own_walkup_is_not_setting_it(client, db, world, sign_in):
    """Somebody should still be able to see what will play for them."""
    sign_in(world["admin"])
    switch(client, "self_walkup", False)

    sign_in(world["peter"])

    assert client.get("/api/me/walkup").status_code == 403


def test_a_manager_can_still_choose_theirs(client, db, world, sign_in):
    sign_in(world["admin"])
    switch(client, "self_walkup", False)

    sign_in(world["manager"])
    reply = client.put(
        "/api/me/walkup", json={"url": "https://youtu.be/dQw4w9WgXcQ"}
    )

    assert reply.status_code == 200, reply.json()


def test_an_upload_is_closed_by_the_same_switch(client, db, world, sign_in):
    """It is the same decision reached by a different door."""
    sign_in(world["admin"])
    switch(client, "self_walkup", False)

    sign_in(world["peter"])
    reply = client.post("/api/me/walkup/audio", content=b"not audio")

    assert reply.status_code == 403


# -- Changing the switches ---------------------------------------------------


def test_only_an_admin_may_change_them(client, db, world, sign_in):
    sign_in(world["manager"])

    assert client.patch("/api/organization", json={"self_photo": False}).status_code == 403


def test_a_switch_sent_as_null_leaves_it_alone(client, db, world, sign_in):
    """A client filling in a default it did not mean must not turn a NOT NULL
    column into an error."""
    sign_in(world["admin"])
    switch(client, "self_photo", False)

    body = client.patch("/api/organization", json={"self_photo": None}).json()

    assert body["self_photo"] is False


def test_closing_one_leaves_the_others_alone(client, db, world, sign_in):
    sign_in(world["admin"])

    body = switch(client, "self_walkup", False).json()

    assert body["self_photo"] is True
    assert body["self_details"] is True
