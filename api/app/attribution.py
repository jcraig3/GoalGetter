"""Filling in the team a fact was recorded without.

Every fact carries a snapshot of its subject's team and office, taken when it
arrived, and team and office boards group on that snapshot rather than on where
people are now. That is what keeps last quarter's team board answering the same
way after somebody transfers, and it stays exactly as it is.

**A blank snapshot is different.** A fact recorded while its subject was on no
team says "no team", and no team is not a team: no board ever showed it under
one, so giving it the first team its subject joins rewrites no history. Without
this, a deployment that loads its data before building its teams — which is the
natural order — has team boards that stay empty for everything already loaded.
Only 3 of $1600 facts in the dev deployment had a team.

The same holds one level up. A fact on a team that had no office has no office,
and gains one when the team is put in one.

**One hook on the session, rather than a call at each door.** A person changes
team from their profile, the People page's bulk action, the Teams tab, the
directory mirror and more; a team changes office from its editor and from the
mirror. A call at each of those would be missed at the next one somebody adds,
and the symptom — an empty team board — would look like missing data rather
than a bug. So the rule lives where every one of those writes has to pass.

Moves between two real teams, or two real offices, are left alone: the old
snapshot is the right answer for those.
"""

from sqlalchemy import event, inspect, select, update
from sqlalchemy.orm import Session

from app.models import MetricFact, Team, UserAccount


def _became(obj: object, attribute: str) -> bool:
    """True when this flush gave `attribute` a value (not when it cleared one)."""
    history = inspect(obj).attrs[attribute].history
    return bool(history.added) and getattr(obj, attribute) is not None


@event.listens_for(Session, "after_flush")
def _fill_blank_snapshots(session: Session, _flush_context: object) -> None:
    # After the flush rather than before it, so a team created in the same
    # flush already has an id, and the team's office is already written.
    changed = [*session.new, *session.dirty]
    people = [
        obj.id
        for obj in changed
        if isinstance(obj, UserAccount) and _became(obj, "team_id")
    ]
    teams = [
        obj.id for obj in changed if isinstance(obj, Team) and _became(obj, "office_id")
    ]
    if not people and not teams:
        return

    connection = session.connection()
    if people:
        current_team = (
            select(UserAccount.team_id)
            .where(UserAccount.id == MetricFact.subject_user_id)
            .scalar_subquery()
        )
        current_office = (
            select(Team.office_id)
            .join(UserAccount, UserAccount.team_id == Team.id)
            .where(UserAccount.id == MetricFact.subject_user_id)
            .scalar_subquery()
        )
        connection.execute(
            update(MetricFact)
            .where(
                MetricFact.subject_user_id.in_(people),
                MetricFact.subject_team_id.is_(None),
            )
            .values(subject_team_id=current_team, subject_office_id=current_office)
        )
    if teams:
        connection.execute(
            update(MetricFact)
            .where(
                MetricFact.subject_team_id.in_(teams),
                MetricFact.subject_office_id.is_(None),
            )
            .values(
                subject_office_id=select(Team.office_id)
                .where(Team.id == MetricFact.subject_team_id)
                .scalar_subquery()
            )
        )

    # Facts already loaded in this session hold the old blanks; make them read
    # the new values next time rather than contradict the database.
    for obj in list(session.identity_map.values()):
        if isinstance(obj, MetricFact) and (
            obj.subject_user_id in people or obj.subject_team_id in teams
        ):
            session.expire(obj, ["subject_team_id", "subject_office_id"])
