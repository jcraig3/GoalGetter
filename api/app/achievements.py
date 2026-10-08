"""What a rule celebrates, defined once.

This exists for one reason. Two things now need to know which facts an
achievement rule matches: the pass that announces them, and the pass that
counts them toward a badge. Written twice they would drift — and the way that
drift shows up is a badge saying somebody closed ten big deals while the wall
announced eight, which is worse than either number being wrong on its own,
because now neither can be trusted.

So the predicate lives here and both import it.
"""

from __future__ import annotations

from app.models import AchievementRule, MetricFact

__all__ = ["bar", "considered", "matches"]


def considered(rule: AchievementRule) -> list:
    """Filters for the facts this rule *looks at* — before its bar is applied.

    **The split from `matches` is load-bearing, and it is not a tidiness
    thing.** The announcing pass advances its watermark past everything it
    examined rather than past what qualified, and the difference is a flood:
    an admin sets the bar at $50,000, sees nothing for a week, lowers it to
    $5,000, and every deal from that week suddenly qualifies and announces at
    once. "The rule existed but the bar was higher" is not work anybody expects
    to be celebrated retroactively.

    **Not retroactive** is the other guard here, and the one that matters most:
    work done before the rule existed is never celebrated by it. A connector
    syncing six months of history inserts thousands of rows with fresh ids and
    old timestamps, and without this every one of them would announce.
    """
    where = [
        MetricFact.organization_id == rule.organization_id,
        MetricFact.metric_definition_id == rule.metric_definition_id,
        MetricFact.occurred_at >= rule.created_at,
    ]
    if rule.scope == "team":
        # The snapshot, not current membership — the same rule every other
        # query here follows. Somebody who has since moved teams still earned
        # it on the team they were on.
        where.append(MetricFact.subject_team_id == rule.scope_team_id)
    return where


def bar(rule: AchievementRule):
    """Just the rule's threshold test.

    Its own function because the announcing pass needs it *apart* from the
    rest — it examines a wider set than it celebrates, for the reason in
    `considered` — and reaching into `matches()` by index to get it back out
    would be a line nobody could safely reorder.
    """
    return (
        MetricFact.value >= rule.threshold
        if rule.comparator == "gte"
        else MetricFact.value <= rule.threshold
    )


def matches(rule: AchievementRule) -> list:
    """Filters for the facts this rule actually celebrates.

    Deliberately excludes `last_fact_id`. That watermark belongs to the
    announcing pass — it says "I have looked at these already", not "these are
    not matches" — and a counting pass that inherited it would find nothing.
    """
    return [*considered(rule), bar(rule)]
