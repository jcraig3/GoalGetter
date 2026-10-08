"""Which rule decides what a person from the directory becomes.

The most decision-dense part of directory sync, and the part that needs no tenant to
exercise — so it is tested here exhaustively rather than through a sync loop.

The rule being protected throughout: **an admin should be able to write rules in any
order and get the same answer.** That is the whole reason for specificity scoring
over first-match-wins, and most of what follows is a way of saying it precisely.
"""

from app.directory.rules import (
    Person,
    Rule,
    best,
    conflicts,
    matches,
    normalise,
    place,
    specificity,
)


def person(**kwargs) -> Person:
    defaults = dict(
        external_id="1",
        email="sam@acme.com",
        display_name="Sam Rivera",
        job_title="Account Executive",
        department="Sales",
        office_location="Phoenix",
    )
    defaults.update(kwargs)
    return Person(**defaults)


# ── Normalising what people typed ────────────────────────────────────────────


def test_case_and_surrounding_space_do_not_stop_a_rule_matching():
    """A directory is typed in by people over years. A rule that fails because
    somebody left a trailing space is a rule whose author concludes the feature is
    broken."""
    assert matches(Rule(department=" SALES "), person(department="sales"))


def test_a_double_space_inside_a_name_does_not_stop_a_rule_matching():
    """`Sales  Team` and `Sales Team` are the same department to everyone except a
    string comparison."""
    assert normalise("Sales  Team") == normalise("Sales Team")
    assert matches(Rule(department="Sales Team"), person(department="Sales  Team"))


def test_punctuation_is_left_alone_because_removing_it_would_be_guessing():
    """`Sales-EMEA` and `SalesEMEA` are plausibly different departments. Merging
    them would be us deciding something the admin did not.

    The example matters: `Sales — EMEA` versus `Sales EMEA` was the first one here,
    and it stays different even *with* punctuation stripped — the dash leaves a
    double space behind. It could not tell the two behaviours apart.
    """
    assert normalise("Sales-EMEA") != normalise("SalesEMEA")


def test_a_missing_value_normalises_to_nothing_rather_than_failing():
    """Directories return null for fields nobody filled in, and half of them are
    always empty."""
    assert normalise(None) == ""
    assert normalise("   ") == ""


# ── Matching ─────────────────────────────────────────────────────────────────


def test_a_rule_with_no_conditions_matches_everybody():
    """How a deployment says "everyone is an agent unless something more specific
    applies". It falls out of the definition rather than being a special case."""
    assert matches(Rule(), person())
    assert matches(Rule(), person(department="", job_title="", office_location=""))


def test_every_condition_has_to_hold_not_just_one():
    """A rule is an *and*. An *or* is two rules, which reads better and changes
    more safely."""
    rule = Rule(department="Sales", office="Phoenix")

    assert matches(rule, person(department="Sales", office_location="Phoenix"))
    assert not matches(rule, person(department="Sales", office_location="Dallas"))
    assert not matches(rule, person(department="Support", office_location="Phoenix"))


def test_a_condition_the_person_has_no_value_for_does_not_match():
    """Rather than treating an empty field as a wildcard, which would make a rule
    about a department apply to everybody whose department nobody filled in."""
    assert not matches(Rule(department="Sales"), person(department=""))


def test_group_membership_matches_any_one_of_the_groups():
    """Somebody is in several groups and a rule names one of them."""
    sam = person(groups=("Phoenix Sales", "All Staff"))

    assert matches(Rule(group="Phoenix Sales"), sam)
    assert matches(Rule(group="all staff"), sam)
    assert not matches(Rule(group="Support"), sam)


def test_a_person_in_no_groups_does_not_match_a_group_rule():
    assert not matches(Rule(group="Phoenix Sales"), person(groups=()))


# ── Specificity ──────────────────────────────────────────────────────────────


def test_more_conditions_beat_fewer():
    """The property that lets an admin write a broad rule and carve exceptions out
    of it without thinking about ordering."""
    broad = Rule(department="Sales")
    narrow = Rule(department="Sales", job_title="Account Executive")

    assert specificity(narrow) > specificity(broad)


def test_a_rule_with_no_conditions_is_the_weakest_of_all():
    """It has to lose to everything, or the catch-all would swallow every person
    before a specific rule ever saw them."""
    assert specificity(Rule()) == 0
    assert specificity(Rule(office="Phoenix")) > specificity(Rule())


def test_group_membership_outranks_a_department():
    """A department is a string somebody typed into the directory once. Membership
    of *Phoenix Sales* is a fact somebody actively maintains, so it is the stronger
    claim about who this person is."""
    assert specificity(Rule(group="Phoenix Sales")) > specificity(Rule(department="Sales"))


def test_a_department_outranks_a_job_title_which_outranks_an_office():
    """The ordering the weights exist to encode. Asserted as an ordering rather
    than as numbers, so the numbers can be retuned without rewriting this."""
    assert (
        specificity(Rule(department="x"))
        > specificity(Rule(job_title="x"))
        > specificity(Rule(office="x"))
    )


# ── Which rule wins ──────────────────────────────────────────────────────────


def test_the_most_specific_matching_rule_wins_whatever_order_it_is_written_in():
    """**The reason this is not first-match-wins.** With ordering, adding a broad
    rule at the top silently disables every specific rule below it — no error, no
    visible change, and the wrong people on the wrong leaderboard until somebody
    notices."""
    broad = Rule(department="Sales", role="agent")
    narrow = Rule(department="Sales", job_title="Account Executive", role="manager")

    assert best([broad, narrow], person()) is narrow
    assert best([narrow, broad], person()) is narrow


def test_a_catch_all_only_applies_when_nothing_better_does():
    catch_all = Rule(role="agent")
    specific = Rule(department="Sales", role="manager")

    assert best([catch_all, specific], person(department="Sales")) is specific
    assert best([catch_all, specific], person(department="Legal")) is catch_all


def test_nothing_matching_is_a_real_answer():
    assert best([Rule(department="Support")], person(department="Sales")) is None


def test_no_rules_at_all_is_a_real_answer():
    """Which every deployment starts as, and many will stay as."""
    assert best([], person()) is None


def test_a_tie_resolves_the_same_way_every_time():
    """Two rules with identical conditions are a mistake, reported separately. What
    matters here is that the answer is *stable*: a sync that reshuffled people
    between runs would be far worse than one that picked consistently."""
    first = Rule(department="Sales", role="agent")
    second = Rule(department="Sales", role="manager")

    assert best([first, second], person()) is first
    assert best([first, second], person()) is first


# ── Conflicts ────────────────────────────────────────────────────────────────


def test_two_rules_with_the_same_conditions_are_reported():
    """The second is unreachable, and an admin cannot see that by looking at the
    list — so they are told while still on the screen where they wrote it."""
    rules = [Rule(department="Sales"), Rule(office="Phoenix"), Rule(department="sales")]

    assert conflicts(rules) == [(0, 2)]


def test_a_rule_is_compared_by_its_conditions_and_nothing_else():
    """This asserted that keyword order did not matter, which nothing could have
    made false — a dataclass does not remember which argument was written first.
    What is actually worth pinning is that two rules clash on their *conditions*,
    whatever else about them differs.
    """
    rules = [
        Rule(department="Sales", office="Phoenix", role="agent", team_id=1),
        Rule(department="Sales", office="Phoenix", role="manager", team_id=2),
    ]

    assert conflicts(rules) == [(0, 1)]


def test_different_assignments_do_not_make_two_rules_different():
    """The clash is in the conditions. Two rules that match the same people and
    assign different teams are precisely the mistake worth reporting."""
    rules = [Rule(department="Sales", role="agent"), Rule(department="Sales", role="manager")]

    assert conflicts(rules) == [(0, 1)]


def test_rules_that_differ_are_not_reported():
    assert conflicts([Rule(department="Sales"), Rule(department="Support")]) == []


def test_two_rules_agreeing_on_one_condition_and_differing_on_another_do_not_clash():
    """**Every condition has to be compared, not just the first.**

    Two Phoenix-and-Dallas rules for the same department are the single most normal
    pair of rules a company will write. Reporting them as a conflict would train an
    admin to ignore the warning, which is worse than not having one.
    """
    rules = [
        Rule(department="Sales", office="Phoenix"),
        Rule(department="Sales", office="Dallas"),
    ]

    assert conflicts(rules) == []


def test_three_identical_rules_report_both_of_the_later_ones():
    """Otherwise fixing the one reported would leave a second one still shadowed,
    and the warning would look like it had been dealt with."""
    rules = [Rule(department="Sales")] * 3

    assert conflicts(rules) == [(0, 1), (0, 2)]


# ── Placing somebody ─────────────────────────────────────────────────────────


def test_a_matching_rule_places_somebody_where_it_says():
    placement = place([Rule(department="Sales", role="manager", team_id=7)], person())

    assert placement.role == "manager"
    assert placement.team_id == 7
    assert placement.assigned is True


def test_the_rule_that_decided_comes_back_with_the_answer():
    """So an admin can be shown *why* somebody landed where they did, rather than
    being asked to work it out from the list."""
    rule = Rule(department="Sales", team_id=7)

    assert place([rule], person()).rule is rule


def test_nobody_matching_leaves_a_person_unassigned_rather_than_guessed_at():
    """`team_id` is already nullable, so an unplaced person is a real account with
    no team for an admin to place. The same answer as an unmatched metric row, for
    the same reason: propose, never guess."""
    placement = place([], person())

    assert placement.team_id is None
    assert placement.assigned is False
    assert placement.rule is None


def test_an_unplaced_person_still_gets_the_default_role():
    """An account with no role could not sign in at all, so there is no version of
    this where leaving it empty is the safe answer."""
    assert place([], person()).role == "agent"
    assert place([], person(), default_role="manager").role == "manager"


def test_a_rule_that_names_a_team_but_no_role_uses_the_default():
    """Most rules are about which team somebody is on. Making them restate the role
    every time would be four words of noise per rule."""
    placement = place([Rule(department="Sales", team_id=7)], person())

    assert placement.role == "agent"
    assert placement.team_id == 7


def test_a_rule_that_matches_but_names_no_team_still_leaves_them_unassigned():
    """A rule can set a role without deciding where somebody sits, and that must not
    read as "placed" — otherwise they would never appear in the list of people an
    admin still has to put somewhere."""
    placement = place([Rule(department="Sales", role="manager")], person())

    assert placement.role == "manager"
    assert placement.assigned is False


def test_office_decides_the_team_rather_than_being_assigned_itself():
    """**Office is a condition, never an assignment.** A person's office is derived
    through their team, so setting one independently could put somebody in the
    Phoenix team and the Dallas office at once — which nothing in the product could
    then resolve."""
    rules = [
        Rule(department="Sales", office="Phoenix", team_id=1),
        Rule(department="Sales", office="Dallas", team_id=2),
    ]

    assert place(rules, person(office_location="Phoenix")).team_id == 1
    assert place(rules, person(office_location="Dallas")).team_id == 2
