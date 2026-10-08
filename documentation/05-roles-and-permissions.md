# Roles & Permissions

**Phase 1.** Get this right early — retrofitting authorization is how data leaks happen.

## Two dimensions

Permission is the combination of **what role someone has** and **what part of the org they can see**.

```
        ROLE (what actions)          SCOPE (over whom)
        ─────────────────            ─────────────────
        admin                        entire organization
        manager        ×             their teams
        agent                        themselves
```

A manager can edit goals — but only for people on their team. Both questions must be answered on every request.

## Org roles

| Role | Intent |
|---|---|
| **admin** | The few who control the deployment itself: settings, integrations, users, metrics. |
| **manager** | Runs a team. Sets goals, manages agents, and moves people between teams — within their own team. |
| **agent** | The people whose performance is measured — the players. Sync from the identity provider. See their own numbers, their goals, and leaderboards published to them. |

Three built-in roles, and **custom roles on top of them — built.** A custom role
is a built-in role with capabilities taken away: "Team lead" is a manager who
cannot run competitions or correct data; "Reporting admin" is an admin who
cannot change integrations or settings. See "Custom roles" below.

## Permission matrix

`✓` full · `~` scoped to their own team · `S` self only · `–` none

| Capability | admin | manager | agent |
|---|:--:|:--:|:--:|
| **Organization** |||
| View org settings | ✓ | – | – |
| Edit org settings, branding | ✓ | – | – |
| View audit log | ✓ | – | – |
| **Users** |||
| View user list | ✓ | ~ | – |
| Invite users | ✓ | ~ | – |
| Edit user profile | ✓ | ~ | S |
| Change a user's org role | ✓ | – | – |
| Suspend / archive user | ✓ | – | – |
| **Teams** |||
| View org tree | ✓ | ✓* | ✓* |
| Create / edit / archive team | ✓ | ~ | – |
| Manage team membership | ✓ | ~ | – |
| Assign team leads | ✓ | ~ | – |
| **Metrics** |||
| View metric definitions | ✓ | ✓ | ✓ |
| Create / edit metrics | ✓ | – | – |
| Correct / backfill metric data | ✓ | ~ | – |
| Import CSV / Excel | ✓ | ~ | – |
| Edit / delete metric facts | ✓ | ~ | – |
| **Goals** |||
| View own goals | ✓ | ✓ | ✓ |
| View others' goals | ✓ | ~ | – |
| Create / edit / delete goals | ✓ | ~ | – |
| **Leaderboards** |||
| View leaderboard | ✓ | ~ | per visibility |
| Create / edit leaderboard | ✓ | ~ | – |
| Enable TV display | ✓ | ~ | – |
| **Competitions** (Phase 2) |||
| View | ✓ | ~ | participating + public |
| Create / edit / close | ✓ | ~ | – |
| **Data sources** (Phase 3) |||
| View / configure connections | ✓ | – | – |
| Trigger manual sync | ✓ | – | – |
| **Reporting** (Phase 4) |||
| Manager overview, track records, competition reports | ✓ | ~ | – |
| **Points economy** (Phase 4) |||
| See the season table, earn, buy cosmetics, spin the wheel | ✓ | ✓ | ✓ |
| Award points or give a badge by hand | ✓ | ~ | – |
| Hand over a prize won on the wheel | ✓ | ~ | – |
| Seasons, tiers, prices, badges, cosmetics, the wheel's stock | ✓ | – | – |

\* Structure and names only — visible so people understand the org. Performance data within it follows the rules above.

**The reporting tab is a job, not a view.** Agents are refused at the edge rather than shown their own slice of it. Nothing on that page is secret — every figure is one the viewer could reach by opening the goal — but each answer it gives is a list of *other people to talk to*, and handing an agent a ranked list of colleagues who are behind is a different product from the one this is.

**Agents never write metric data.** Self-reporting is not built — see [06-metrics-engine.md](06-metrics-engine.md#data-entry). Production data arrives from connectors ([15-data-integrations.md](15-data-integrations.md)); admin correction exists only to fix bad rows, and every correction is audited and visibly marked.

## Scope resolution

The core question: *which users' data may this requester see?*

Implemented in [`api/app/scope.py`](../api/app/scope.py):

| Role | Sees |
|---|---|
| **admin** | Everyone in the organization |
| **manager** | Their own team, plus agents on no team, plus themselves |
| **agent** | Themselves |

```python
def visible_user_ids(db, actor) -> list[int] | None:
    if actor.org_role == "admin":
        return EVERYONE                      # None — "apply no filter"

    if actor.org_role == "manager":
        # Their team OR nobody's team. An explicit or_(), not a ternary:
        # a ternary evaluates to a SINGLE condition, so the unassigned
        # branch is dropped whenever the manager has a team.
        on_their_team = (UserAccount.team_id == actor.team_id
                         if actor.team_id is not None else false())
        rows = db.scalars(select(UserAccount.id).where(
            UserAccount.organization_id == actor.organization_id,
            UserAccount.archived_at.is_(None),
            or_(on_their_team, UserAccount.team_id.is_(None)),
        )).all()
        return sorted({*rows, actor.id})

    return [actor.id]                        # agent: themselves
```

Three things make this safe:

**An admin returns `EVERYONE` (None), not a list of every id.** Otherwise a
5,000-person organization builds a 5,000-element `IN` clause on every request.
Callers translate it to "no extra `WHERE` clause", which is both correct and free.

**Managers see unassigned agents on purpose.** Without that, a manager could
never pull a newly invited person onto their team — they would be invisible
until an admin placed them. That is the setup failure this product should
surface, not hide.

**It resolves per request, not at login.** Move someone between teams and it takes effect on their next request — no stale session data. This is one of the reasons sessions are server-side rather than JWT ([03-auth-and-users.md](03-auth-and-users.md)).

### Out of scope answers 404, not 403

For a user outside the actor's scope, confirming the account exists is itself
information they are not entitled to. `403` says "that person exists and you may
not touch them"; `404` says nothing at all.

### The result is a filter, not a check

The critical implementation rule:

> **Scope filters the query. It does not validate the response.**

```python
# WRONG — leaks existence and count, and one missed branch leaks data
rows = db.query(MetricFact).filter(metric_id=m).all()
return [r for r in rows if r.subject_user_id in visible]

# RIGHT — the database never returns what they can't see
rows = (db.query(MetricFact)
          .filter(MetricFact.metric_definition_id == m)
          .filter(MetricFact.subject_user_id.in_(visible))
          .all())
```

Filtering after the fact means pagination counts, aggregates, and "no results" states are all subtly wrong, and any code path that forgets the filter leaks silently. Pushing scope into the query makes the safe path the default one.

## Enforcement

Permission is enforced **server-side, in the service layer**. Every service function that touches org data takes the acting user and applies scope itself.

Routers use a FastAPI dependency for the coarse role check:

```python
@router.post("/goals", dependencies=[Depends(require_role("admin", "manager"))])
async def create_goal(payload: GoalCreate, actor: User = Depends(current_user)):
    return goal_service.create(actor, payload)   # service applies scope
```

Two layers on purpose: the dependency rejects obviously-wrong roles at the edge, and the service enforces scope with the domain knowledge to do it correctly.

**The frontend hides things it shouldn't show. It never enforces anything.** Every UI permission check is a duplicate of a server check, purely for user experience. Anything relying only on a hidden button is not protected.

## Frontend permission model

`GET /api/auth/me` returns resolved capabilities so the UI doesn't reimplement the rules:

```json
{
  "id": 42,
  "full_name": "Jayden Craig",
  "org_role": "manager",
  "team_id": 8,
  "capabilities": ["offices.view", "teams.view", "users.assign_team",
                   "users.invite", "users.view"]
}
```

A **list of what you hold**, not a map of every capability to true/false. The
map form has to be exhaustive — every new capability must be added to every
role's object, and one forgotten entry reads as `undefined`, which is falsy and
therefore silently denies. A list only names what is granted.

Three consumers, one source:

```tsx
<Can do="users.invite">                      {/* a button */}
  <button>Invite someone</button>
</Can>

<RequireCapability capability="users.view">  {/* a route */}
  <Users />
</RequireCapability>

{ to: '/settings', label: 'Settings', needs: 'org.settings.edit' }  // a nav item
```

Returning capabilities rather than the raw role keeps role semantics in one place. Adding a role later, or custom roles, changes `_CAPABILITIES` in `app/scope.py` and the interface follows automatically — no component edits.

**Capability and scope are separate answers.** A manager holds
`users.assign_team`: the capability says yes, and `visible_user_ids()` narrows
it to their own team plus unassigned agents. Folding scope into the capability
check would mean re-answering "which rows?" inside every permission test.

## Leaderboard visibility

Leaderboards have their own `visibility` field that interacts with scope:

| Visibility | Who can view |
|---|---|
| `org` | Everyone in the organization, regardless of team |
| `team` | Members of the scoped team and its sub-teams, plus anyone whose scope covers it |
| `private` | The creator and admins |

**Deliberate exception:** an `org`-visible leaderboard is viewable by an `agent` even though it shows other people's numbers. That's the point of a leaderboard — public ranking is the motivational mechanism. The control is that a manager chooses to publish it.

What an agent still cannot do is view another agent's *detail* page, goals, or raw metric history. Rank and score on a published board is public; the underlying record is not.

## Special cases

**TV displays use a signed URL, not an account**
A wall-mounted screen authenticates with a display token that grants access to
leaderboards flagged `is_tv_enabled` and nothing else — see
[08-leaderboards.md](08-leaderboards.md). A dedicated `viewer` role existed for
this and was dropped: the token already scopes access precisely, so the role
protected nothing and added a column to every permission table.

**Admin lockout**
The last active admin cannot be archived, suspended, or demoted. Enforced in the service layer with a clear error. Without it, one click permanently locks everyone out of a self-hosted install with no support team to call.

**Self-access**
An agent always has full read access to their own data regardless of scope — every user is inside their own scope by definition.

## Audit

Every permission-relevant action writes to `audit_log`. Built today: invite,
resend invite, role change, team change, suspend, reactivate, archive. Still to
come with their features: manual metric entry and edits, goal create/edit/delete,
data source config.

The reason is trust. When someone's leaderboard position changes unexpectedly, an admin needs to answer "did someone edit the data?" If that question can't be answered, people stop believing the numbers.

**Rows commit in the same transaction as the change they describe.**
`audit.record()` only adds to the session; the handler's existing `db.commit()`
writes it. So the two cannot disagree — a rolled-back role change takes its
audit row with it, and a change can never be applied without being recorded.
Verified: five refused actions wrote zero rows.

**Actor and target emails are copied into the row**, not joined at read time. A
rename or a departure would otherwise silently rewrite history — "Admin User
changed a role" is useless if that name now belongs to someone else. Both
foreign keys are `ON DELETE SET NULL`, so a deleted account loses the link but
never the record of what it did.

**Reads are not logged.** Logging every `GET` would bury the handful of rows
that matter under millions nobody reads. The question this table answers is
"who gave that person admin?", not "who looked at the user list?".

`GET /api/audit` is **admin-only** and returns the 50 most recent entries by
default, capped at 200. A manager can see who is on their team; the record of
who granted whom what is organization-level oversight. Surfaced on the Settings
page as **Recent activity** rather than its own nav item — it is consulted when
something looks wrong, not daily, and a permanent link for a rarely-used page is
exactly the clutter this project avoids.

## Open questions

1. ~~**Should managers be able to invite users?**~~ **Resolved: yes.** Managers
   hold `users.invite` but may only invite agents — `POST /api/users/invite`
   returns 403 if a non-admin passes any other role, so a manager cannot mint an
   admin. An org setting to disable it can follow if anyone asks.
2. **Cross-team visibility for agents** — should an agent see other teams' org-visible leaderboards, or only their own team's? *Leaning: yes, org-wide is the default, with a setting to restrict.*
3. ~~**Self-reporting**~~ — **Resolved: not built.** Agents cannot write metric data. Data arrives from connectors; admin correction covers bad rows. Rationale: self-reported numbers are gameable, and a leaderboard nobody believes is worthless.

## Related docs

- [03-auth-and-users.md](03-auth-and-users.md)
- [04-organizations-and-teams.md](04-organizations-and-teams.md)
- [17-security.md](17-security.md)

## Custom roles — built

Settings → Roles. Name a role, choose what it is based on (manager or admin),
tick what it may not do, and add people who have that built-in role.

- **Narrower, never wider.** A person's `org_role` stays the built-in one, so
  every existing check and every scope rule — whose numbers they can see —
  works unchanged. A custom role only subtracts. Widening (an agent who may set
  goals) would mean passing checks written for managers, a different feature.
- **Enforced in one place, by route.** `require_role`, which every guarded
  endpoint already goes through, also looks up the capability the request's
  method and path need (`app/roles.py::ROUTE_RULES`) and refuses it with "Your
  role does not include that." if the person's custom role took it away. The
  capabilities sent to the interface are narrowed the same way, so buttons for
  what was removed are hidden too.
- **Only what the server enforces can be removed.** The editor offers exactly
  the capabilities the route table covers, and only those the base role has.
- **Applies while its base matches.** Promote somebody from manager to admin and
  a manager-based role stops applying rather than narrowing the wrong thing.
- **Guard rails.** Changing roles counts as an organization setting, so an admin
  whose role takes settings away cannot edit their own role to lift it, and
  nobody can put themselves in a role that takes settings or integrations.
  Deleting a role returns its people to their built-in role. It is a guard rail
  for honest mistakes, not a boundary against a determined admin, who can still
  create another admin account.

