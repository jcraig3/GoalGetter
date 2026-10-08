"""The connector contract, and the registry of what implements it.

**Adding a connector is writing a driver, not touching the engine.** The sync
loop, the mapping, the identity resolution and the wizard all speak to this
interface and never know which provider is behind it. That is the whole point of
Phase 3 being built framework-first: the seventh connector should cost a fraction
of the first.

Four methods, each earning its place:

    test_connection   the "Test" button. A bad credential must fail at
                      configuration time with a specific message, not silently at
                      three in the morning.
    discover          the columns this source actually has, so the mapping UI is
                      built from real data instead of asking an admin to type
                      field names and hope.
    fetch             the rows. Takes `since` so a sync can be incremental.

`fetch` returns an **iterator, not a list**. A warehouse query can return a
million rows, and a connector that materialises them has moved the memory problem
into the API process where it will be discovered under load.

`local` is keyword-only, optional, and only a **push** connector touches it — see
`LocalContext`. Every pulling connector ignores it. One optional keyword was the
smaller price than special-casing push inside the pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass(frozen=True)
class ConnectionResult:
    """Whether a source can be reached, and what to say if not.

    `detail` is written for the admin looking at the wizard, not for a log. "The
    spreadsheet is not shared with this account" is actionable; "403" is not.
    """

    ok: bool
    detail: str
    #: Anything worth showing on success — the sheet's title, the row count, the
    #: warehouse version. Confirms they connected the thing they meant to.
    info: dict[str, str] = field(default_factory=dict)


#: What a discovered field looks like to the mapping UI.
#:
#: `kind` is a guess, not a guarantee. It drives the auto-suggested mapping — a
#: column of values containing `@` is probably the person, a date column is
#: probably the date — and the admin confirms. Guessing wrong costs a click;
#: not guessing costs every admin typing every field name.
FIELD_KINDS = ("string", "number", "date", "datetime", "boolean", "email")


@dataclass(frozen=True)
class SourceField:
    name: str
    kind: str = "string"
    #: A few real values, for the preview. Enough to recognise a column by, few
    #: enough that discovery stays cheap.
    samples: tuple[str, ...] = ()

    #: Every distinct value, when there are few enough for the column to be a
    #: *choice* rather than data. Empty otherwise, and empty is the answer that
    #: matters: it is how "this is a category" is told apart from "this is a name".
    #:
    #: **What it is for.** A spreadsheet of deals has a `stage` column holding
    #: three words, and a metric counting every row counts the lost ones too. A
    #: filter is the fix, and nobody reaches for one they were not offered — so
    #: discovery has to say which columns could be filtered on. The values are
    #: already in hand when a connector reads a sheet; the cost is a set.
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceRow:
    """One row as the source gave it, before any mapping.

    Deliberately dumb: a dict of values plus the source's own id for the row.
    Mapping, filtering, identity resolution and unit conversion all happen
    downstream, in one place, so a connector cannot get them subtly wrong in its
    own private way.
    """

    #: The source's stable identifier for this row. `None` when the source has no
    #: such concept — see `app/sync.py` for what that costs.
    external_id: str | None
    values: dict[str, object]


@dataclass(frozen=True)
class LocalContext:
    """What an **in-process** connector needs, and a remote one must ignore.

    Only a *push* connector has any use for this. A webhook does not go and get
    anything: payloads arrive at an endpoint and are parked in `webhook_event`, so
    its "remote system" is a table two feet away and it needs the session the sync
    is already using, plus the identity of the source whose inbox is its.

    **The session matters more than it looks.** An earlier version had the webhook
    connector open its own `SessionLocal()`, which is wrong in two ways: it reads on
    a different connection from the one the sync writes facts on, so the two are not
    one transaction — and it is untestable, because the test suite runs inside a
    transaction that is never committed, so a second session sees an empty database.
    The second problem is how the first was found.

    A connector talking to Google or Salesforce must ignore this entirely. It is
    passed to everything for uniformity and used by almost nothing.
    """

    db: object
    source_id: int


@runtime_checkable
class Connector(Protocol):
    """What every connector implements.

    A `Protocol` rather than a base class: a connector is a small module with no
    state worth inheriting, and structural typing means a test can pass a stub
    without importing anything from here.

    **One optional attribute, deliberately not declared here.**
    `reads_everything = True` says every `fetch` returns the whole source rather
    than a window, which is what lets the sync withdraw a fact whose row has been
    deleted — see `reads_everything()` below and `sync._withdraw_missing`.

    It is absent from this body on purpose: a member here is *required* by
    structural matching, so declaring it would have made every existing connector
    stop being a `Connector`. Read through the helper, which defaults to False —
    the safe answer, because being wrong the other way deletes real data.
    """

    #: Stable, stored in `data_source.connector`. Renaming one orphans every
    #: source configured against it, so treat it as permanent.
    key: str
    display_name: str

    #: Non-secret settings — which sheet, which object. Pydantic so the wizard's
    #: form and its validation are generated rather than hand-built per connector.
    config_schema: type[BaseModel]
    #: Secrets. Stored encrypted, never returned to a client, never logged.
    credential_schema: type[BaseModel]

    def test_connection(
        self, config: BaseModel, credentials: BaseModel
    ) -> ConnectionResult: ...

    def discover(
        self,
        config: BaseModel,
        credentials: BaseModel,
        *,
        local: LocalContext | None = None,
    ) -> list[SourceField]: ...

    def fetch(
        self,
        config: BaseModel,
        credentials: BaseModel,
        since: datetime | None = None,
        *,
        local: LocalContext | None = None,
    ) -> Iterator[SourceRow]: ...


def reads_everything(connector: object, config: object = None) -> bool:
    """Whether this `fetch` returns the whole source rather than a window.

    `getattr` with a default rather than a required Protocol member: every
    connector written before this existed answers False without being touched,
    which is the safe answer. Opting in is a deliberate line in one file.

    **Either a flag or a question.** A spreadsheet is always whole, so it sets
    `reads_everything = True` and is done. A warehouse query is whole only when
    somebody chose that mode — `SELECT * FROM a_view` is, `WHERE updated_at >=
    :since` is not — so Snowflake defines it as a method taking the config, and
    the answer differs per source.

    Both spellings are accepted because forcing the simple case to write a method
    that ignores its argument is how a rule stops being read.
    """
    answer = getattr(connector, "reads_everything", False)
    if callable(answer):
        try:
            return bool(answer(config))
        except Exception:  # noqa: BLE001 — a connector that cannot say says no
            return False
    return answer is True


class Truncated(Exception):
    """A connector stopped early because there was more than it will read at once.

    **Raised after everything it did read has been yielded**, so the rows are kept
    and only the *completeness* is in question. The sync records it, which makes the
    run `partial` — and a partial run does not advance the watermark.

    That last part is the whole reason this exists. Both engines used to hit their
    row cap, log a line, and return; the run then reported `ok`, the watermark moved
    past rows nobody had read, and they were never read again. Two comments in the
    code claimed the truncation was "reported on the run". It was reported in a log
    file, and the run said everything was fine.

    **The consequence of holding the watermark is a source that stays stuck**,
    reading the same first hundred thousand rows every time and saying so on every
    run. That is deliberate and is the better failure: stuck and complaining can be
    fixed by narrowing the query or the backfill window, and silently lossy cannot
    be fixed at all because nobody knows it happened.
    """


class UnknownConnector(LookupError):
    """Asked for a connector that is not registered.

    Its own exception so callers can tell "this deployment does not ship that
    connector" apart from a genuine failure. A `data_source` row naming a
    connector this build does not have is not corruption — it is a source
    configured on a newer version, or a connector deliberately removed — and the
    scheduler skips it loudly rather than crashing the whole pass.
    """


_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> Connector:
    """Add a connector to the registry. Returns it, so it can be used as a
    decorator on a class.

    Refuses a duplicate key rather than overwriting. Two connectors answering to
    `google_sheets` is a mistake at import time, and the version that silently
    won would depend on import order — which is the kind of bug that appears only
    in the environment you cannot debug.
    """
    if connector.key in _REGISTRY:
        raise ValueError(f"A connector is already registered as {connector.key!r}.")
    _REGISTRY[connector.key] = connector
    return connector


def endpoint_credential_of(connector: Connector) -> str | None:
    """The credential that forms this connector's address, if it has one.

    A connector that is **posted to** rather than polled declares
    `endpoint_credential = "token"`. Three behaviours follow from that one line, and
    splitting them across the API would let them disagree:

    * it is **generated** when the source is created, never typed, because an
      address somebody chose is an address somebody can guess;
    * it is **refused** on a credential write, for the same reason;
    * it is the one secret the API **returns**, as part of a URL, because a token
      whose whole purpose is to be pasted into another system is useless if it
      cannot be read.

    Read through here rather than declared on `Connector`, deliberately. It is an
    optional capability, and a `Protocol` has no way to say so — a member there is a
    member `isinstance` demands, which would mean every fetching connector writing
    `endpoint_credential = None` to declare the absence of something. Asking through
    a function with a default says the same thing once.
    """
    return getattr(connector, "endpoint_credential", None)


def oauth_of(connector: Connector) -> object | None:
    """The `OAuthSpec` this connector signs in with, if it does.

    Read through a function with a default, for exactly the reasons spelled out on
    `endpoint_credential_of`: it is an optional capability, and a member on a
    `runtime_checkable` Protocol is a member `isinstance` demands.

    Typed `object | None` rather than `OAuthSpec | None` on purpose. `app.oauth`
    imports `app.credentials`, which imports the models — and having this module
    import *that* would put a cycle between the connector contract and the thing
    that stores connector secrets. The caller knows what it asked for.
    """
    return getattr(connector, "oauth", None)


def setup_steps_of(connector: Connector) -> tuple[str, ...]:
    """How to get the credentials this connector needs, in numbered steps.

    Read through a function with a default for the same reason as the two above:
    it is an optional capability, and a member on a `runtime_checkable` Protocol is
    a member `isinstance` demands.

    **Steps rather than only field hints.** Every credential field already carries
    a sentence, and that sentence is the right place for "which of the two boxes on
    this screen do I paste in here". It is the wrong place for "go to Settings,
    then Integrations, then Private apps, then create one" — a route through
    somebody else's product, spread across four hint texts, is a route nobody
    follows. The steps go above the form; the hints stay beside the fields.

    Empty for a connector with nothing to explain — a webhook generates its own
    credential, and an admin connecting a database already has one.
    """
    return tuple(getattr(connector, "setup_steps", ()) or ())


def get(key: str) -> Connector:
    """The connector for a key, or `UnknownConnector`."""
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownConnector(
            f"No connector named {key!r} in this build. "
            f"Available: {', '.join(sorted(_REGISTRY)) or 'none'}."
        ) from None


def available() -> list[Connector]:
    """Every registered connector, for the wizard's first step.

    Sorted by display name, not registration order: the grid of cards an admin
    picks from should be in a stable order that does not depend on which module
    imported first.
    """
    return sorted(_REGISTRY.values(), key=lambda c: c.display_name.lower())


def keys() -> tuple[str, ...]:
    """Registered keys, for validating `data_source.connector` on the way in."""
    return tuple(sorted(_REGISTRY))


# Shipped connectors, imported for their `register()` side effect.
#
# At the bottom of this module rather than at the top of `main.py`, so that
# `from app import connectors` always hands back a populated registry — a test that
# never touches FastAPI still needs to be able to look one up. Circular by
# construction and safe because everything these modules import from here is
# already defined above.
from app.connectors import api as _api  # noqa: E402,F401  (side effect)
from app.connectors import calls as _calls  # noqa: E402,F401  (side effect)
from app.connectors import crm as _crm  # noqa: E402,F401  (side effect)
from app.connectors import excel as _excel  # noqa: E402,F401  (side effect)
from app.connectors import freshdesk as _freshdesk  # noqa: E402,F401  (side effect)
from app.connectors import sheets as _sheets  # noqa: E402,F401  (side effect)
from app.connectors import sql as _sql  # noqa: E402,F401  (side effect)
from app.connectors import support as _support  # noqa: E402,F401  (side effect)
from app.connectors import webhook as _webhook  # noqa: E402,F401  (side effect)
