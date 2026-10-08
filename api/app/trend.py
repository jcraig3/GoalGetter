"""The wire shape of a plotted line.

One model, used by goals and by dashboard placements, so a sparkline component
on the client can take either without knowing which it was handed.

Timestamps are sent per point rather than left for the client to derive from a
start plus an index. Deriving them looks cheaper right up to the two days a
year a daylight-saving change makes a local day 23 or 25 hours long, and the
month buckets where every step is a different length — at which point the
labels drift and nobody notices, because a sparkline has no axis to check them
against.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class TrendPoint(BaseModel):
    #: The bucket's start, in UTC. Buckets are whole days or whole months in
    #: the organization's timezone — see `periods.bucket_starts`.
    at: datetime
    #: None means "no honest number here", not zero. An average over a day with
    #: no facts is unknown, and drawing it as zero invents a collapse that never
    #: happened. Only `sum` and `count` fill empty buckets with zero.
    value: Decimal | None


class Trend(BaseModel):
    #: "day" or "month". The client shows it in the tooltip so a reader knows
    #: what one point covers without counting them.
    unit: str
    #: True when the line is a running total rather than per-bucket activity.
    #: The two are read completely differently — one climbs toward a target,
    #: the other is a heartbeat — so the client must not have to guess.
    cumulative: bool
    points: list[TrendPoint]
