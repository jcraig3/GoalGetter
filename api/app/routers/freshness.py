"""How current the numbers are, per metric.

**A leaderboard showing three-day-old figures looks exactly like one showing
current figures.** That is the fastest way to lose trust in the tool, and it is
not an admin-only problem: the people being ranked are the ones who notice their
deal is missing, and "the sync is broken" is a much better answer for them than
silence.

So this is open to any signed-in user, and what it returns is deliberately thin.
Per metric: when a fact from a connector last landed, and the bare scheduling
facts of the sources feeding it — a status word, two timestamps, an interval. No
names, no connector types, no credentials, nothing about how the sources are
configured. Enough for the client to say "these numbers are from four hours ago,
and something feeding them is failing"; not enough to learn what an organization
has plugged in.

**The judgement lives in the client, on purpose.** `sourceWizard.isLate` already
decides what "overdue" means, and it is tested and mutation-tested there. A second
implementation here would be a second definition of late, and the two would agree
right up until somebody adjusted one.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.models import (
    DataSource,
    MetricDefinition,
    MetricFact,
    SourceMapping,
    UserAccount,
)
from app.sessions import current_user

router = APIRouter(tags=["freshness"])


class FeedingSource(BaseModel):
    """One source behind a metric, described only as a schedule.

    Mirrors the fields `sourceWizard.isLate` reads and nothing else. Anything
    more would be telling every agent in the building what the sales operations
    stack looks like.
    """

    last_status: str | None
    last_run_at: datetime | None
    next_run_at: datetime | None
    interval_minutes: int
    enabled: bool


class MetricFreshness(BaseModel):
    metric_id: int
    #: When a fact from a connector last landed for this metric.
    #:
    #: The fact's `occurred_at`, not the import time: a leaderboard reader asking
    #: "how current is this?" means the data, not the plumbing. A source that
    #: syncs every hour and finds nothing new has not gone stale.
    latest_fact_at: datetime | None
    #: The newest number of any kind, a correction included — what "Data as
    #: of" says (Q2-12). Not what lateness is judged by: one correction must
    #: not make a stalled feed look current.
    latest_any_at: datetime | None = None
    #: Whether any source feeds it at all. A metric fed only by hand is not
    #: stale — nobody promised it would refresh.
    imported: bool
    sources: list[FeedingSource]


@router.get("/data-freshness", response_model=list[MetricFreshness])
def data_freshness(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[MetricFreshness]:
    """Freshness for every metric in the organization, in one call.

    All of them rather than a requested subset: a dashboard shows six
    leaderboards over four metrics, and one small response cached by the client
    beats four round trips carrying a query string each. The whole payload is a
    handful of timestamps per metric.
    """
    org_id = actor.organization_id

    # Newest connector-written fact per metric, in one pass rather than a query
    # per metric — this is called from pages that render immediately.
    #
    # **The organization filter here is unobservable, and deliberate.** The
    # results are keyed by metric id and only ever read for metrics the last
    # query returned, which are already this organization's — so removing it
    # leaks nothing and no test can catch it. It stays because it keeps the scan
    # off every other tenant's facts, which on the largest table in the schema is
    # the difference between an index range and the whole thing. The same is true
    # of the mapping query below.
    latest = dict(
        db.execute(
            select(MetricFact.metric_definition_id, func.max(MetricFact.occurred_at))
            .where(
                MetricFact.organization_id == org_id,
                MetricFact.source_type == "connector",
            )
            .group_by(MetricFact.metric_definition_id)
        ).all()
    )

    any_kind = dict(
        db.execute(
            select(MetricFact.metric_definition_id, func.max(MetricFact.occurred_at))
            .where(MetricFact.organization_id == org_id)
            .group_by(MetricFact.metric_definition_id)
        ).all()
    )

    feeding: dict[int, list[FeedingSource]] = {}
    rows = db.execute(
        select(SourceMapping.metric_definition_id, DataSource)
        .join(DataSource, DataSource.id == SourceMapping.data_source_id)
        .where(
            SourceMapping.organization_id == org_id,
            # A mapping that is switched off is not feeding anything, so it
            # cannot make a metric look overdue. This is the state every source
            # passes through in the middle of the connect flow.
            SourceMapping.enabled.is_(True),
            # Nor can a removed integration. Archiving disables the source, and
            # the client reads "every feed disabled" as *importing is paused* —
            # so without this, removing a source would put a warning about
            # pausing on a leaderboard that is working perfectly well from
            # whatever replaced it.
            DataSource.archived_at.is_(None),
        )
    ).all()
    for metric_id, source in rows:
        feeding.setdefault(metric_id, []).append(
            FeedingSource(
                last_status=source.last_status,
                last_run_at=source.last_run_at,
                next_run_at=source.next_run_at,
                interval_minutes=source.interval_minutes,
                enabled=source.enabled,
            )
        )

    metrics = db.scalars(
        select(MetricDefinition).where(
            MetricDefinition.organization_id == org_id,
            MetricDefinition.archived_at.is_(None),
        )
    ).all()

    return [
        MetricFreshness(
            metric_id=metric.id,
            latest_fact_at=latest.get(metric.id),
            latest_any_at=any_kind.get(metric.id),
            imported=bool(feeding.get(metric.id)),
            sources=feeding.get(metric.id, []),
        )
        for metric in metrics
    ]
