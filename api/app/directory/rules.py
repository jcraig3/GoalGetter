"""Deciding what a person from the directory becomes here.

**No database and no HTTP in this module**, on purpose. Which rule wins is the most
decision-dense thing in the whole of directory sync and the easiest to get subtly
wrong, so it lives where it can be tested exhaustively rather than inside a sync
loop that needs a tenant to exercise.

## The shape of a rule

Conditions on the left, assignments on the right:

    Department = Sales  AND  Office = Phoenix   →   team "Phoenix Sales", role agent

Any condition left blank means *any*. A rule with no conditions at all matches
everyone, which is a legitimate and useful thing — it is how a company says
"everybody is an agent unless something more specific applies".

**Office is a condition, never an assignment**, and that surprised us. A person's
office is already derived: `user_account.team_id` → `team.office_id`. There is no
`user_account.office_id` to set. Assigning one independently would let somebody sit
in the Phoenix team while assigned to the Dallas office, which nothing in the
product could then resolve. Matching on the directory's `officeLocation` and
assigning a team gets the same result with one fewer thing that can disagree.

## Why specificity rather than order

The obvious design is first-match-wins, and it is worse. It makes correctness depend
on an admin keeping the list in the right order, so adding a broad rule at the top
silently disables every specific one below it — with no error, and no visible change
until somebody notices the wrong people on the wrong leaderboard.

Scoring instead means *the most specific matching rule wins*, whatever order they
were written in:

    department  4
    job title   2
    office      1

The weights only have to produce the right ordering, and the ordering they encode is
that a department is the coarsest grouping and therefore the weakest claim. Powers
of two would work identically; these are the smallest numbers that read clearly.

**Ties are still possible** — two rules with identical conditions — and are a
mistake rather than a decision, so `conflicts` finds them and the UI says so at the
moment they are saved rather than leaving somebody to discover it later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: What a rule can decide. Deliberately short.
#:
#: Role and team, and nothing else — see the module docstring on why office is not
#: here. Metrics are not here either: which metrics somebody is measured on follows
#: from their team, and a rule that could set them separately would be a second
#: place for that to be decided.
ASSIGNS = ("role", "team")


def normalise(value: str | None) -> str:
    """One spelling for comparing two pieces of directory text.

    Directories are typed in by people over years. *Sales*, *sales*, ` Sales `, and
    *Sales  Team* are the same department to everyone except a string comparison, and
    a rule that fails to match because somebody left a trailing space is a rule whose
    author will conclude the feature is broken.

    Case-folded, trimmed, and internal runs of whitespace collapsed. Deliberately
    *not* stripping punctuation: `Sales — EMEA` and `Sales EMEA` are plausibly
    different departments, and merging them would be us guessing.
    """
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


@dataclass(frozen=True)
class Person:
    """What a directory says about somebody, in our vocabulary rather than theirs.

    A provider module turns Graph's `jobTitle` or LDAP's `title` into this, so the
    rules never learn a provider's spelling and a second provider is a translation
    rather than a second matching engine.
    """

    external_id: str
    email: str
    display_name: str = ""
    job_title: str = ""
    department: str = ""
    office_location: str = ""
    #: Group or team memberships, by name. The strongest signal of the four — a
    #: department is a string somebody typed once, while membership of *Phoenix
    #: Sales* is a fact somebody actively maintains.
    groups: tuple[str, ...] = ()
    #: False for somebody disabled at the far end. They are archived rather than
    #: deleted, so their history survives.
    enabled: bool = True


@dataclass(frozen=True)
class Rule:
    """One "people like this become that" statement.

    Conditions are compared normalised; the raw text is kept for display, because an
    admin should see the rule as they wrote it.
    """

    #: Conditions. Empty means *any*.
    department: str = ""
    job_title: str = ""
    office: str = ""
    group: str = ""

    #: Assignments. `role` falls back to the deployment's default when empty;
    #: `team_id` of None means the rule places somebody without choosing a team,
    #: which leaves them unassigned for an admin to place.
    role: str = ""
    team_id: int | None = None

    def conditions(self) -> dict[str, str]:
        """The conditions that are actually set, normalised, keyed by field.

        **Built in a fixed order and then filtered**, so two rules setting the same
        conditions always produce the same sequence whatever order their fields were
        written in. `conflicts` relies on that to compare rules — it used to sort
        this as well, which mutation testing showed changed nothing, because there
        was never an order to correct.
        """
        found = {
            "department": normalise(self.department),
            "job_title": normalise(self.job_title),
            "office": normalise(self.office),
            "group": normalise(self.group),
        }
        return {key: value for key, value in found.items() if value}


#: How much each condition contributes to a rule's specificity.
#:
#: Only the ordering matters, not the magnitudes. Group is highest because
#: membership is actively maintained; department is lowest because it is the
#: coarsest grouping and so the weakest claim to describing somebody.
WEIGHTS = {"group": 8, "department": 4, "job_title": 2, "office": 1}


def specificity(rule: Rule) -> int:
    """How strong a rule's claim is. Higher wins.

    Additive, so *department + title* beats *department* — which is the property
    that lets an admin write a broad rule and then carve exceptions out of it
    without having to think about ordering.
    """
    return sum(WEIGHTS[key] for key in rule.conditions())


def matches(rule: Rule, person: Person) -> bool:
    """Whether every condition a rule sets is true of this person.

    All conditions must hold — a rule is an *and*, not an *or*. An *or* is two
    rules, which is both easier to read and easier to change later.

    A rule with no conditions matches everybody. That is deliberate: it is how a
    deployment says "everyone is an agent unless something more specific applies",
    and it falls out of the definition rather than being a special case.
    """
    values = {
        "department": normalise(person.department),
        "job_title": normalise(person.job_title),
        "office": normalise(person.office_location),
    }
    groups = {normalise(name) for name in person.groups}

    for key, wanted in rule.conditions().items():
        if key == "group":
            if wanted not in groups:
                return False
        elif values[key] != wanted:
            return False
    return True


def best(rules: list[Rule], person: Person) -> Rule | None:
    """The most specific rule that matches, or None if none does.

    **Ties break towards the earlier rule**, which is not a meaningful decision —
    two rules with identical conditions are a mistake, and `conflicts` reports them
    so it can be corrected. What matters here is only that the answer is *stable*:
    the same rules and the same person must always produce the same assignment,
    because a sync that reshuffled people between runs would be far worse than one
    that picked the wrong rule consistently.
    """
    winner: Rule | None = None
    highest = -1
    for rule in rules:
        if not matches(rule, person):
            continue
        score = specificity(rule)
        if score > highest:
            highest = score
            winner = rule
    return winner


def conflicts(rules: list[Rule]) -> list[tuple[int, int]]:
    """Pairs of rules with identical conditions, as (first, later) positions.

    Not an error — the second is simply unreachable — but always a mistake, and one
    an admin cannot see by looking at the list. Reported when rules are saved, while
    they are still looking at the screen, rather than discovered weeks later when
    somebody lands on the wrong leaderboard.
    """
    found: list[tuple[int, int]] = []
    seen: dict[tuple[tuple[str, str], ...], int] = {}
    for index, rule in enumerate(rules):
        key = tuple(rule.conditions().items())
        if key in seen:
            found.append((seen[key], index))
        else:
            seen[key] = index
    return found


@dataclass(frozen=True)
class Placement:
    """What a person should become, once the rules have spoken."""

    role: str
    team_id: int | None
    #: The rule that decided, for showing an admin *why* somebody landed where they
    #: did. None when nothing matched.
    rule: Rule | None

    @property
    def assigned(self) -> bool:
        """Whether this actually places somebody, or leaves them for an admin.

        A rule that matched but names no team still leaves somebody unassigned —
        which is why this asks about the outcome rather than about whether a rule
        was found.
        """
        return self.team_id is not None


def place(rules: list[Rule], person: Person, *, default_role: str = "agent") -> Placement:
    """Where a person lands, and why.

    **Anything the rules cannot place stays unassigned rather than being guessed
    at.** `user_account.team_id` is already nullable, so an unplaced person is a
    real account with no team, surfaced for an admin to put somewhere. That is the
    same answer as an unmatched metric row, for the same reason: propose, never
    guess.
    """
    rule = best(rules, person)
    if rule is None:
        return Placement(role=default_role, team_id=None, rule=None)
    return Placement(
        role=rule.role or default_role,
        team_id=rule.team_id,
        rule=rule,
    )
