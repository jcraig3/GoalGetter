"""Whose number is this?

Every fact belongs to a person — that is what makes a leaderboard possible — so a
row naming `pparker@acme.com` has to become a `subject_user_id` before it can be
stored.

**Three outcomes, and the middle one is the point of this module:**

    matched       a user was found, or an admin mapped this identifier once
    quarantined   nobody matched, so the row waits and somebody gets asked
    ignored       an admin said "never mind this one", so the row is skipped

**Never auto-created.** A CRM is full of things that are not your salespeople:
service accounts, ex-employees who still own old records, contractors, duplicates
from a migration. An account per unrecognised name puts people who have never
signed in onto leaderboards — with no team and no office — and into every goal and
competition picker. Quarantining loses nothing and asks once.

Silently dropping unmatched rows was the third option and the worst: real numbers
disappear, and somebody notices months later that their deals never counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import DataSource, UserAccount, UserIdentity

#: What happened to a row's subject.
MATCHED = "matched"
QUARANTINED = "quarantined"
IGNORED = "ignored"


@dataclass(frozen=True)
class Resolution:
    outcome: str
    user_id: int | None = None


def resolve(
    db: DbSession,
    source: DataSource,
    raw_identifier: object,
    *,
    now: datetime | None = None,
    record: bool = True,
) -> Resolution:
    """Work out who a row belongs to, recording a question if we cannot.

    `record=False` looks without touching anything — no question opened, no row
    counted, no match written down. That is what the wizard's preview needs: it
    answers "who would these ten rows belong to?" and a preview that quietly
    created a quarantine queue as a side effect of being looked at would be a
    genuinely nasty surprise.

    Order matters, and each step is cheaper and more certain than the next:

    1. **An explicit mapping** for this identifier on this source. An admin's
       decision outranks any guess, and it is also the fast path once the first
       sync has been tidied up.
    2. **Email match.** Most sources identify people by their work email, which is
       the same address they sign in with — so a deployment using SSO matches
       nearly everything on the first sync and never sees a quarantine list.
    3. **Username match**, and only where it is unambiguous. Two systems in one
       company routinely disagree about how an address is built: a CRM sends
       `pparker@` where the directory holds `peterp@`, and both are Peter Parker.
       Exact email cannot bridge that, and asking an admin to answer the same
       question four hundred times is not a product. See `_by_username`, which
       refuses to guess when more than one person fits.
    4. **Quarantine.** Record the identifier, count the row, ask somebody.

    Emails are matched case-insensitively. `PParker@Acme.com` and `pparker@acme.com`
    are one person, and a CRM will send both.
    """
    now = now or datetime.now(UTC)
    identifier = _clean(raw_identifier)
    if not identifier:
        # A row whose subject column was blank. Quarantining an empty string would
        # collect every such row under one meaningless heading, so it is skipped
        # as unusable — the mapping is pointed at the wrong column, and the value
        # error surfaces in the sync's own counts.
        return Resolution(QUARANTINED, None)

    decided = db.scalar(
        select(UserIdentity).where(
            UserIdentity.data_source_id == source.id,
            func.lower(UserIdentity.external_identifier) == identifier.lower(),
        )
    )
    if decided is not None:
        if decided.ignored:
            return Resolution(IGNORED)
        if decided.user_id is not None:
            if record:
                decided.last_seen_at = now
            return Resolution(MATCHED, decided.user_id)
        if record:
            decided.last_seen_at = now
            # Known, still unanswered. Count the row against the existing question
            # rather than opening a second one.
            decided.pending_rows += 1
        return Resolution(QUARANTINED)

    matched = _by_email(db, source.organization_id, identifier)
    if matched is None:
        matched = _by_username(db, source.organization_id, identifier)
    if matched is not None:
        if record:
            # Written down even though it was found by matching, so the next sync
            # takes the fast path and — more importantly — so the answer survives
            # somebody later changing their email in GoalGetter.
            db.add(
                UserIdentity(
                    organization_id=source.organization_id,
                    data_source_id=source.id,
                    external_identifier=identifier,
                    user_id=matched,
                    last_seen_at=now,
                )
            )
            db.flush()
        return Resolution(MATCHED, matched)

    if record:
        db.add(
            UserIdentity(
                organization_id=source.organization_id,
                data_source_id=source.id,
                external_identifier=identifier,
                pending_rows=1,
                last_seen_at=now,
            )
        )
        db.flush()
    return Resolution(QUARANTINED)


def _clean(raw: object) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def _by_email(db: DbSession, org_id: int, identifier: str) -> int | None:
    """A user in this organization whose email is this identifier.

    **Only ever compares against `email`.** Matching a bare name against
    `full_name` is the obvious next idea and a bad one: two people called B. Banner
    are one leaderboard scandal, and a wrong match is worse than a question —
    it silently credits somebody else's work. That property comes from the query
    below, not from the guard.

    The guard is an optimisation and nothing more: an identifier with no `@` cannot
    equal an email, so the query would return nothing anyway. Mutation testing
    confirmed that — removing it changes no answer — and it stays because a sync
    resolves thousands of rows and each one would otherwise cost a round trip to
    learn that "0051x000ABCdef" is not an email address.
    """
    if "@" not in identifier:
        return None
    return db.scalar(
        select(UserAccount.id).where(
            UserAccount.organization_id == org_id,
            func.lower(UserAccount.email) == identifier.lower(),
            UserAccount.hidden_at.is_(None),
        )
    )


def _norm(text: str) -> str:
    """Lower-case letters and digits only.

    So `peter.parker`, `Peter_Parker` and `PeterParker` are one string, which is
    the whole point: the separator is the thing two systems most often disagree
    about and the least meaningful difference between them.
    """
    return "".join(c for c in text.lower() if c.isalnum())


def _usernames(full_name: str, email: str) -> set[str]:
    """Every spelling of a login this person plausibly has.

    **Both name parts, always.** A first name alone would match `peter@` to the
    only Peter in the roster even when the row belongs to a different Peter who
    is not in it — the wrong match the module docstring warns about, arrived at by
    a different route. Every form here uses the first name *and* the surname, so a
    hit means two independent pieces agreed.

    Middle names are dropped rather than permuted: `Mary Jane Watson` is treated
    as Mary Watson, because that is what a login is built from.
    """
    parts = [p for p in _norm_parts(full_name) if p]
    local = _norm(email.split("@", 1)[0])

    forms = {local} if local else set()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        forms |= {
            first + last[0],      # peterp
            first[0] + last,      # pparker
            first + last,         # peterparker
            last + first[0],      # parkerp
        }
    return {f for f in forms if len(f) > 2}


def _norm_parts(full_name: str) -> list[str]:
    return [_norm(part) for part in full_name.split()]


def _roster(db: DbSession, org_id: int) -> dict[str, set[int]]:
    """Every username form in this organization, to the people who own it.

    **Built once per session, not once per row.** A sync resolves thousands of
    rows and each unrecognised one would otherwise re-read the whole roster.
    Cached on the session because that is the unit this is scoped to — a longer
    life would mean a sync that started before somebody was added never seeing
    them, and a shorter one would mean no cache at all.
    """
    key = f"identity_roster_{org_id}"
    cached = db.info.get(key)
    if cached is not None:
        return cached

    index: dict[str, set[int]] = {}
    rows = db.execute(
        select(UserAccount.id, UserAccount.full_name, UserAccount.email).where(
            UserAccount.organization_id == org_id,
            UserAccount.hidden_at.is_(None),
        )
    ).all()
    for user_id, full_name, email in rows:
        for form in _usernames(full_name or "", email or ""):
            index.setdefault(form, set()).add(user_id)

    db.info[key] = index
    return index


def _by_username(db: DbSession, org_id: int, identifier: str) -> int | None:
    """The one person whose login this is, or nobody.

    **Ambiguity is a question, not a coin toss.** Where two people produce the
    same form — `bbanner` for Bruce Banner and Betty Banner — this returns `None`
    and
    the row goes to the quarantine list, exactly as an unrecognised identifier
    does. A wrong match silently credits somebody else's work, which is worse
    than an admin answering one question.

    The local part is what is compared, so `pparker@crm.example` and a bare
    `pparker` are the same lookup — a source that sends usernames rather than
    addresses needs no special case.

    **A human name is not a handle, and is refused.** `pparker` is unique by
    construction in the system that issued it, so working out who owns it is an
    inference from a guaranteed-unique key. "Clark Kent" guarantees nothing: the
    source may well contain two, and the ambiguity check below can only see people
    who are *in* the roster — so the second Alice, the one who is not, would have
    her work credited to the first. Whitespace is what separates the two cases,
    and `test_a_bare_name_is_never_guessed_at` is what holds this line.
    """
    if any(c.isspace() for c in identifier.strip()):
        return None

    local = _norm(identifier.split("@", 1)[0])
    if len(local) <= 2:
        return None

    owners = _roster(db, org_id).get(local)
    if owners is None or len(owners) != 1:
        return None
    return next(iter(owners))


def pending(db: DbSession, source: DataSource) -> list[UserIdentity]:
    """The unanswered questions for this source, busiest first.

    Ordered by how many rows are waiting, so the identifier holding up two
    thousand facts is at the top rather than alphabetically somewhere in the
    middle.
    """
    return list(
        db.scalars(
            select(UserIdentity)
            .where(
                UserIdentity.data_source_id == source.id,
                UserIdentity.user_id.is_(None),
                UserIdentity.ignored.is_(False),
            )
            .order_by(UserIdentity.pending_rows.desc(), UserIdentity.id)
        ).all()
    )


def map_to(db: DbSession, identity: UserIdentity, user_id: int) -> UserIdentity:
    """Answer a question: this identifier is that person.

    Clears the pending count, because those rows are no longer waiting — the next
    sync re-reads them and they match. **Quarantined rows are not stored**, only
    counted, which is why mapping does not have to go and find them: the source is
    the source of truth and re-reading it is cheaper than keeping a second copy of
    everything it sent.
    """
    identity.user_id = user_id
    identity.ignored = False
    identity.pending_rows = 0
    db.flush()
    return identity


def ignore(db: DbSession, identity: UserIdentity) -> UserIdentity:
    """"Never mind this one." For the `Integration User` a CRM owns half its
    records with — without this, the quarantine list asks about it forever."""
    identity.ignored = True
    identity.user_id = None
    identity.pending_rows = 0
    db.flush()
    return identity
