"""Syncing people from a company's own directory.

**A sibling of the metric pipeline, not a connector on it.** The two look alike from
a distance — both fetch on a schedule, with credentials, and produce rows — and the
resemblance is misleading in the one way that matters:

    the metric pipeline **appends events**;
    a directory sync **reconciles state**.

`app/sync.py` is correct because of `since_for` and a watermark that only advances
on a clean run. It asks *what changed since Tuesday* and appends what comes back.
A directory sync has to do the opposite: read the **whole** current membership, then
archive every person it did **not** see. There is no watermark that expresses *this
person left the company*, and bolting a full-snapshot mode onto a pipeline whose
entire correctness story is watermarks would hide exactly the sort of complexity
this project keeps refusing.

Everything else points the same way. The destination is `user_account`, not
`metric_fact`. The mapping is name and title and department, not
metric/subject/occurred_at/value. And identity resolution is **inverted**: the
metric pipeline matches rows to people who already exist and quarantines what it
cannot place, while this one *creates* them.

**So what is shared is shared by importing, not by abstracting.** No base class, no
generalised framework — three existing helpers:

    app.oauth.ensure_fresh              refreshing the provider token
    app.credentials                     the same Fernet key as every other secret
    app.connectors.rest.request_json    retries, rate limits, paging

And no `data_source` row at all: a directory connection is a capability on the
provider connection (see `app/providers.py`), so switching it on is a checkbox
rather than another wizard.

**Nobody appears without being approved.** Everything read from a directory lands in
a staging table with a status, and only an approved row becomes a real account. That
is the same shape as the quarantine for unmatched metric rows, and for the same
reason: an automated guess about identity should be answerable before it becomes a
fact. It is also what makes "agents are added by hand" the default without a second
mode to maintain — sync always proposes, an admin always disposes.
"""
