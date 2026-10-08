"""What an admin may write into a celebration.

**The air-gapped answer to "make it feel less repetitive".** The product this
borrows from asks a language model to reword an announcement each time. Writing
three lines and picking one does the same job, needs no outbound connection,
and the words on the wall are always words somebody chose.
"""

import pytest

from app import merge_tags
from app.merge_tags import MergeTagError


# -- Alternatives ------------------------------------------------------------


def test_one_line_is_one_alternative():
    assert merge_tags.variants("{name} did it") == ["{name} did it"]


def test_blank_lines_are_not_alternatives():
    """Somebody pressing enter twice has not written an empty announcement."""
    assert merge_tags.variants("one\n\n  \ntwo") == ["one", "two"]


def test_an_empty_message_has_none():
    assert merge_tags.variants("") == []
    assert merge_tags.variants("   \n  ") == []


def test_the_same_win_always_reads_the_same_way():
    """**Seeded, not random.** A wall re-reading its feed must not quietly
    reword an announcement somebody already read."""
    message = "one\ntwo\nthree"

    assert merge_tags.pick(message, 41) == merge_tags.pick(message, 41)


def test_different_wins_do_not_march_through_them_in_order():
    """Consecutive fact ids modulo three would cycle, which reads as a rota
    rather than as variety. A hash is what breaks that."""
    message = "one\ntwo\nthree"
    run = [merge_tags.pick(message, seed) for seed in range(1, 13)]

    assert set(run) == {"one", "two", "three"}
    assert run != ["one", "two", "three"] * 4


def test_one_alternative_is_always_that_one():
    for seed in range(20):
        assert merge_tags.pick("only this", seed) == "only this"


def test_no_message_renders_to_nothing():
    """Empty is how a rule says "use the fixed shape", so this has to be
    falsy rather than a blank line the caller would print."""
    assert merge_tags.pick("", 1) == ""


# -- Filling in --------------------------------------------------------------


def test_every_tag_is_filled_in():
    out = merge_tags.render(
        "{name} ({first_name}) just did {value} of {metric}",
        seed=1,
        name="Peter Parker",
        first_name="Peter",
        value="$6,200",
        metric="Revenue",
    )

    assert out == "Peter Parker (Peter) just did $6,200 of Revenue"


def test_a_tag_used_twice_is_filled_in_twice():
    out = merge_tags.render("{name}! {name}!", seed=1, name="Peter")

    assert out == "Peter! Peter!"


def test_text_with_no_tags_survives_untouched():
    assert merge_tags.render("Nice one", seed=1, name="Peter") == "Nice one"


def test_an_unknown_tag_is_left_visible_rather_than_blanked():
    """`check` refuses these on the way in, so reaching here means an older row
    from before a tag was renamed — and `{squad}` on a wall is at least
    something an admin can search for."""
    out = merge_tags.render("{name} of {squad}", seed=1, name="Peter")

    assert out == "Peter of {squad}"


def test_braces_that_are_not_tags_are_left_alone():
    assert merge_tags.render("100% {of} target", seed=1) == "100% {of} target"


# -- Refusals ----------------------------------------------------------------


def test_an_empty_message_is_fine():
    """It is how a rule keeps the fixed shape it has always had."""
    merge_tags.check("")


def test_a_typod_tag_is_refused_by_name():
    """The message names both the mistake and what was available, because the
    person is mid-edit and has just guessed."""
    with pytest.raises(MergeTagError) as problem:
        merge_tags.check("{nmae} did it")

    assert "{nmae}" in str(problem.value)
    assert "{name}" in str(problem.value)


def test_every_offered_tag_passes_its_own_check():
    """The catalogue and the validator are one thing, and this is what says so.
    A tag added to the list and not to the pattern would be offered by a picker
    and refused on save."""
    for tag in merge_tags.TAGS:
        merge_tags.check(f"text {{{tag.name}}} text")


def test_a_line_nobody_could_read_is_refused():
    with pytest.raises(MergeTagError) as problem:
        merge_tags.check("x" * (merge_tags.MAX_LENGTH + 1))

    assert "across a room" in str(problem.value)


def test_too_many_alternatives_is_refused():
    with pytest.raises(MergeTagError):
        merge_tags.check("\n".join(f"line {n}" for n in range(20)))


def test_the_limit_is_per_line_not_per_message():
    """Ten short alternatives are ten short alternatives, not one long one."""
    merge_tags.check("\n".join("a short line" for _ in range(10)))


# -- Through a rule, onto a wall ---------------------------------------------


def _rule(db, org, metric, message: str):
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.models import AchievementRule

    rule = AchievementRule(
        organization_id=org.id,
        name="Big deal closed",
        metric_definition_id=metric.id,
        comparator="gte",
        threshold=Decimal(5000),
        scope="everyone",
        message=message,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db.add(rule)
    db.flush()
    return rule


def _fired(db, org, make_fact, metric, person, message: str) -> str:
    """The body of the announcement one win produced."""
    from sqlalchemy import select

    from app import notifications
    from app.models import Notification
    from tests.conftest import within_this_month

    _rule(db, org, metric, message)
    make_fact(metric, person, 12400, within_this_month())
    notifications.detect_rules(db)
    db.flush()

    row = db.scalars(
        select(Notification).where(Notification.event_key.like("achievement:%"))
    ).first()
    return row.body


def test_a_rule_with_no_message_keeps_the_shape_it_always_had(
    db, org, make_user, make_metric, make_fact
):
    """Every rule that already exists says exactly what it said."""
    metric = make_metric("revenue_closed", unit="currency", decimal_places=2)
    peter = make_user("agent", name="Peter Parker")

    body = _fired(db, org, make_fact, metric, peter, "")

    assert body.startswith("Peter Parker — ")


def test_a_written_message_reaches_the_announcement(
    db, org, make_user, make_metric, make_fact
):
    metric = make_metric("revenue_closed", unit="currency", decimal_places=2)
    peter = make_user("agent", name="Peter Parker")

    body = _fired(
        db, org, make_fact, metric, peter, "{first_name} just closed {value}!"
    )

    assert body.startswith("Peter just closed ")
    assert body.endswith("!")


def test_the_metric_tag_names_the_metric(
    db, org, make_user, make_metric, make_fact
):
    metric = make_metric("revenue_closed", unit="currency", decimal_places=2)
    peter = make_user("agent", name="Peter Parker")

    body = _fired(db, org, make_fact, metric, peter, "{metric} — {name}")

    assert body == f"{metric.name} — Peter Parker"
