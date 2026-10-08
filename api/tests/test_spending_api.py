"""Spending points over the wire: buying, wearing, spinning, handing over.

Most of what matters is tested beside the services in `test_spending.py`.
What is left for here is who may do what — everybody spends, admins stock the
shelves, managers hand over prizes to their own people — and that a cosmetic
actually reaches the places other people look, because a ring nobody else can
see is a receipt.
"""

import pytest
from sqlalchemy import select

from app import points, wheel as wheel_service
from app.models import AuditLog, WheelSpin


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    db.flush()
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", smb, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def earn(db, org, user, amount, subject_id=1):
    points.award(
        db, org=org, user_id=user.id, points=amount, event_key="goal.achieved",
        subject_type="goal", subject_id=subject_id, reason="Hit a goal",
    )
    db.commit()


def stock(client, **body):
    return client.post(
        "/api/points/unlockables",
        json={"name": "Gold ring", "kind": "ring", "value": "#f5b301", "price": 300, **body},
    )


# -- Cosmetics ---------------------------------------------------------------


def test_an_admin_stocks_a_cosmetic(client, db, world, sign_in):
    sign_in(world["admin"])

    assert stock(client).status_code == 201


def test_a_ring_must_be_a_colour(client, db, world, sign_in):
    """Anything else ends up in a `style` attribute on a public television."""
    sign_in(world["admin"])

    reply = stock(client, value="red; background: url(x)")

    assert reply.status_code == 422
    assert "#f5b301" in reply.json()["detail"]


def test_an_agent_cannot_stock_the_shelf(client, db, world, sign_in):
    sign_in(world["peter"])

    assert stock(client).status_code == 403


def test_an_agent_buys_and_is_wearing_it(client, db, org, world, sign_in):
    sign_in(world["admin"])
    ring = stock(client).json()
    earn(db, org, world["peter"], 1000)

    sign_in(world["peter"])
    shop = client.post(f"/api/points/unlockables/{ring['id']}/buy").json()

    bought = next(i for i in shop["items"] if i["id"] == ring["id"])
    assert (bought["owned"], bought["equipped"], shop["wallet"]) == (True, True, 700)


def test_not_enough_says_how_much_short(client, db, org, world, sign_in):
    sign_in(world["admin"])
    ring = stock(client).json()
    earn(db, org, world["peter"], 100)

    sign_in(world["peter"])
    reply = client.post(f"/api/points/unlockables/{ring['id']}/buy")

    assert reply.status_code == 409
    assert "300" in reply.json()["detail"] and "100" in reply.json()["detail"]


def test_buying_twice_is_refused(client, db, org, world, sign_in):
    sign_in(world["admin"])
    ring = stock(client).json()
    earn(db, org, world["peter"], 1000)

    sign_in(world["peter"])
    client.post(f"/api/points/unlockables/{ring['id']}/buy")
    again = client.post(f"/api/points/unlockables/{ring['id']}/buy")

    assert again.status_code == 409
    assert client.get("/api/points/unlockables").json()["wallet"] == 700


def test_taking_it_off_and_putting_it_back(client, db, org, world, sign_in):
    sign_in(world["admin"])
    ring = stock(client).json()
    earn(db, org, world["peter"], 1000)
    sign_in(world["peter"])
    client.post(f"/api/points/unlockables/{ring['id']}/buy")

    off = client.post(f"/api/points/unlockables/{ring['id']}/take-off").json()
    on = client.post(f"/api/points/unlockables/{ring['id']}/wear").json()

    assert not next(i for i in off["items"] if i["id"] == ring["id"])["equipped"]
    assert next(i for i in on["items"] if i["id"] == ring["id"])["equipped"]


def test_you_cannot_wear_what_you_have_not_bought(client, db, world, sign_in):
    sign_in(world["admin"])
    ring = stock(client).json()

    sign_in(world["peter"])

    assert client.post(f"/api/points/unlockables/{ring['id']}/wear").status_code == 404


def test_something_people_have_bought_cannot_be_deleted(
    client, db, org, world, sign_in
):
    """Deleting it then would take it off people who paid for it. Retire it
    instead — and the refusal says so."""
    sign_in(world["admin"])
    ring = stock(client).json()
    earn(db, org, world["peter"], 1000)
    sign_in(world["peter"])
    client.post(f"/api/points/unlockables/{ring['id']}/buy")

    sign_in(world["admin"])
    reply = client.delete(f"/api/points/unlockables/{ring['id']}")

    assert reply.status_code == 409
    assert "Retire" in reply.json()["detail"]


def test_something_nobody_owns_can_be_deleted(client, db, world, sign_in):
    sign_in(world["admin"])
    ring = stock(client).json()

    assert client.delete(f"/api/points/unlockables/{ring['id']}").status_code == 204


def test_a_bought_ring_cannot_become_a_title(client, db, org, world, sign_in):
    """That would be selling somebody something different after the money
    changed hands."""
    sign_in(world["admin"])
    ring = stock(client).json()
    earn(db, org, world["peter"], 1000)
    sign_in(world["peter"])
    client.post(f"/api/points/unlockables/{ring['id']}/buy")

    sign_in(world["admin"])
    reply = client.patch(
        f"/api/points/unlockables/{ring['id']}",
        json={"name": "Gold ring", "kind": "title", "value": "Gold", "price": 300},
    )

    assert reply.status_code == 409


def test_a_retired_cosmetic_is_hidden_from_people_who_cannot_buy_it(
    client, db, world, sign_in
):
    sign_in(world["admin"])
    ring = stock(client).json()
    client.patch(
        f"/api/points/unlockables/{ring['id']}",
        json={"name": "Gold ring", "kind": "ring", "value": "#f5b301",
              "price": 300, "enabled": False},
    )

    sign_in(world["peter"])

    assert client.get("/api/points/unlockables").json()["items"] == []


# -- Where it shows ----------------------------------------------------------


def wear_gold(client, db, org, world, who="peter"):
    sign_in_as = client._sign_in
    sign_in_as(world["admin"])
    ring = stock(client).json()
    title = stock(client, name="Closer", kind="title", value="The Closer", price=200).json()
    earn(db, org, world[who], 1000, subject_id=99)
    sign_in_as(world[who])
    client.post(f"/api/points/unlockables/{ring['id']}/buy")
    client.post(f"/api/points/unlockables/{title['id']}/buy")


@pytest.fixture
def dressed(client, sign_in):
    client._sign_in = sign_in
    return client


def test_my_balance_says_what_i_am_wearing_and_what_i_can_spend(
    dressed, db, org, world
):
    wear_gold(dressed, db, org, world)

    body = dressed.get("/api/points/me").json()

    assert (body["ring"], body["title"]) == ("#f5b301", "The Closer")
    # Earned 1000, spent 500: the table says 1000, the wallet says 500.
    assert (body["points"], body["wallet"]) == (1000, 500)


def test_the_season_table_shows_the_ring(dressed, db, org, world):
    wear_gold(dressed, db, org, world)

    row = dressed.get("/api/points/standings").json()["standings"][0]

    assert row["ring"] == "#f5b301"


def board_of_calls(client, world):
    reply = client.post(
        "/api/leaderboards",
        json={
            "name": "Calls", "metric_id": world["metric"].id,
            "period_type": "month", "visibility": "org",
        },
    )
    assert reply.status_code == 201, reply.json()
    return reply.json()["id"]


def test_an_in_app_leaderboard_shows_the_ring(dressed, db, org, world, make_fact):
    from tests.conftest import within_this_month

    wear_gold(dressed, db, org, world)
    make_fact(world["metric"], world["peter"], 5, within_this_month())
    db.commit()
    dressed._sign_in(world["admin"])
    board = board_of_calls(dressed, world)

    entries = dressed.get(f"/api/leaderboards/{board}/results").json()["entries"]

    assert entries[0]["ring"] == "#f5b301"


def test_the_wall_shows_the_ring_and_the_spotlight_the_title(
    dressed, db, org, world, make_fact
):
    """**The wall is where a cosmetic earns its price.** Read the way a
    television reads it: through a display token, with no session."""
    from tests.conftest import within_this_month

    wear_gold(dressed, db, org, world)
    make_fact(world["metric"], world["peter"], 5, within_this_month())
    db.commit()
    dressed._sign_in(world["admin"])
    board = board_of_calls(dressed, world)
    channel = dressed.post("/api/channels", json={"name": "Floor"}).json()
    dressed.post(
        f"/api/channels/{channel['id']}/screens",
        json={"kind": "leaderboard", "leaderboard_id": board},
    )
    dressed.post(
        f"/api/channels/{channel['id']}/screens",
        json={"kind": "spotlight", "user_id": world["peter"].id},
    )
    display = dressed.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    token = display["url"].rsplit("/", 1)[-1]
    dressed.cookies.clear()

    slides = dressed.get(f"/api/display/{token}").json()["slides"]
    board_slide = next(s for s in slides if s["kind"] == "leaderboard")
    spotlight = next(s for s in slides if s["kind"] == "spotlight")

    assert board_slide["entries"][0]["ring"] == "#f5b301"
    assert (spotlight["person"]["ring"], spotlight["person"]["title"]) == (
        "#f5b301",
        "The Closer",
    )


# -- The wheel ---------------------------------------------------------------


def prize(client, **body):
    return client.post(
        "/api/points/wheel/prizes",
        json={"label": "So close", "kind": "nothing", "weight": 1, **body},
    )


def open_wheel(client, cost=100):
    return client.put("/api/points/wheel", json={"spin_cost": cost, "enabled": True})


def test_an_empty_wheel_cannot_be_switched_on(client, db, world, sign_in):
    """A wheel with nothing on it is a way to lose points to an animation."""
    sign_in(world["admin"])

    reply = open_wheel(client)

    assert reply.status_code == 422
    assert "Put something on the wheel" in reply.json()["detail"]


def test_a_wheel_that_would_print_points_cannot_be_saved(
    client, db, world, sign_in
):
    """Refused when it is saved, not discovered in a month by the one person
    who did the sums."""
    sign_in(world["admin"])
    prize(client)

    reply = prize(client, label="+500", kind="points", points=500)

    assert reply.status_code == 422
    assert "make points out of" in reply.json()["detail"]


def test_raising_nothing_but_the_price_cannot_tip_it(client, db, world, sign_in):
    sign_in(world["admin"])
    prize(client, weight=3)
    prize(client, label="+100", kind="points", points=100)
    assert open_wheel(client, cost=100).status_code == 200

    reply = open_wheel(client, cost=20)

    assert reply.status_code == 422


def test_the_odds_are_shown_to_the_person_about_to_spin(
    client, db, world, sign_in
):
    """A wheel whose odds are hidden is a slot machine."""
    sign_in(world["admin"])
    prize(client, weight=3)
    prize(client, label="Long lunch", kind="prize", weight=1)
    open_wheel(client)

    sign_in(world["peter"])
    segments = client.get("/api/points/wheel").json()["segments"]

    assert {s["label"]: s["chance"] for s in segments} == {
        "So close": 0.75,
        "Long lunch": 0.25,
    }


def test_an_agent_spins(client, db, org, world, sign_in):
    sign_in(world["admin"])
    prize(client)
    open_wheel(client)
    earn(db, org, world["peter"], 500)

    sign_in(world["peter"])
    reply = client.post("/api/points/wheel/spin")

    assert reply.status_code == 201, reply.json()
    assert reply.json()["label"] == "So close"
    assert client.get("/api/points/wheel").json()["wallet"] == 400


def test_a_spin_says_why_when_it_cannot_be_afforded(client, db, org, world, sign_in):
    sign_in(world["admin"])
    prize(client)
    open_wheel(client)

    sign_in(world["peter"])
    reply = client.post("/api/points/wheel/spin")

    assert reply.status_code == 409
    assert "100" in reply.json()["detail"]


def test_a_switched_off_wheel_says_so(client, db, org, world, sign_in):
    earn(db, org, world["peter"], 500)
    sign_in(world["peter"])

    reply = client.post("/api/points/wheel/spin")

    assert reply.status_code == 409
    assert "switched off" in reply.json()["detail"]


def test_a_manager_sees_their_own_peoples_prizes_to_hand_over(
    client, db, org, world, sign_in
):
    sign_in(world["admin"])
    prize(client, label="Long lunch", kind="prize")
    open_wheel(client)
    earn(db, org, world["peter"], 500)
    earn(db, org, world["clark"], 500, subject_id=2)

    for person in (world["peter"], world["clark"]):
        sign_in(person)
        client.post("/api/points/wheel/spin")

    sign_in(world["manager"])
    waiting = client.get("/api/points/wheel/waiting").json()

    assert [w["winner_name"] for w in waiting] == ["Peter Parker"]


def test_handing_it_over_takes_it_off_the_list(client, db, org, world, sign_in):
    sign_in(world["admin"])
    prize(client, label="Long lunch", kind="prize")
    open_wheel(client)
    earn(db, org, world["peter"], 500)
    sign_in(world["peter"])
    won = client.post("/api/points/wheel/spin").json()

    sign_in(world["manager"])
    reply = client.post(f"/api/points/wheel/spins/{won['id']}/given")

    assert reply.status_code == 200
    assert reply.json()["given_at"] is not None
    assert client.get("/api/points/wheel/waiting").json() == []
    assert "wheel.prize_given" in db.scalars(select(AuditLog.action)).all()


def test_a_manager_cannot_hand_over_somebody_elses_prize(
    client, db, org, world, sign_in
):
    sign_in(world["admin"])
    prize(client, label="Long lunch", kind="prize")
    open_wheel(client)
    earn(db, org, world["clark"], 500)
    sign_in(world["clark"])
    won = client.post("/api/points/wheel/spin").json()

    sign_in(world["manager"])

    assert client.post(f"/api/points/wheel/spins/{won['id']}/given").status_code == 404


def test_an_agent_cannot_see_the_handover_list(client, db, world, sign_in):
    sign_in(world["peter"])

    assert client.get("/api/points/wheel/waiting").status_code == 403


def test_deleting_a_segment_leaves_what_was_won(client, db, org, world, sign_in):
    sign_in(world["admin"])
    lunch = prize(client, label="Long lunch", kind="prize").json()
    prize(client)
    open_wheel(client)
    earn(db, org, world["peter"], 500)

    # Land on the lunch deterministically, through the service.
    from tests.test_spending import Always

    wheel_service.spin(db, org, world["peter"].id, rng=Always("Long lunch"))
    db.commit()

    sign_in(world["admin"])
    assert client.delete(f"/api/points/wheel/prizes/{lunch['id']}").status_code == 204

    spun = db.scalars(select(WheelSpin)).one()
    assert (spun.label, spun.prize_id) == ("Long lunch", None)
