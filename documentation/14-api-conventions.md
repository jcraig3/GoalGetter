# API Conventions

Rules every endpoint follows, so the generated TypeScript client stays predictable.

## Basics

- Base path `/api`. nginx proxies it to FastAPI, so the browser sees one origin — no CORS, and session cookies work without `SameSite` workarounds.
- JSON in, JSON out. The only exception is file upload (`multipart/form-data`).
- `snake_case` in JSON, matching Python. The generated TS client preserves it. Consistency beats aesthetics; a translation layer is a bug factory.
- All timestamps are ISO 8601 UTC with `Z`. Never local time, never epoch integers.
- All monetary and metric values are **strings**, not numbers.

**Why values are strings:** JavaScript numbers are IEEE-754 doubles and cannot represent all decimal values exactly. Serializing `NUMERIC` as a JSON number silently corrupts precision. The value crosses the wire as `"84200.0000"` and the client formats it via `<MetricValue>`. Ranking and arithmetic happen server-side in Postgres where precision is exact.

## URLs

```
GET    /api/goals              list
POST   /api/goals              create
GET    /api/goals/{id}         read
PATCH  /api/goals/{id}         partial update
DELETE /api/goals/{id}         delete

POST   /api/goals/{id}/archive        action on a resource
POST   /api/leaderboards/preview      action on a collection
```

- Plural nouns for collections.
- `PATCH` for updates, not `PUT`. Clients send only changed fields.
- Actions that aren't CRUD are `POST` to a verb sub-path. Archiving isn't a delete, and pretending otherwise distorts the model.
- `POST` is used for reads with complex bodies (`/api/metrics/query`) where filters don't fit sanely in a query string.

## Pagination

Cursor-based on anything unbounded.

```
GET /api/metric-facts?limit=50&cursor=eyJpZCI6MTIzfQ
```

```json
{
  "items": [...],
  "next_cursor": "eyJpZCI6MTczfQ",
  "has_more": true
}
```

**Why cursors, not `offset`/`page`:** offset pagination on a table receiving continuous inserts (`metric_fact`) skips and duplicates rows as data arrives between requests. It also degrades badly at high offsets, since the database must count past every skipped row. Cursors are stable and fast.

Total counts are **not** returned by default. Counting requires a second full scan, and nothing in the UI needs an exact total. Where a count is genuinely needed, it's an explicit `?include_total=true`.

Small bounded collections (teams, metric definitions) return complete lists. Pagination there would add complexity for no gain.

## Filtering & sorting

```
GET /api/goals?status=active&metric_id=4&team_id=7&sort=-created_at
```

- Filters are query params named for the field.
- Date ranges: `from` / `to`, inclusive of `from`, exclusive of `to`. Half-open intervals compose without off-by-one errors at period boundaries.
- Sorting: `sort=field`, `-` prefix for descending. Multiple sorts comma-separated.
- **Unknown query params are rejected with 422**, not ignored. A typo'd filter that silently returns unfiltered data is how someone sees numbers they shouldn't.

## Errors

Consistent shape everywhere:

```json
{
  "error": {
    "code": "goal_period_overlap",
    "message": "A recurring goal for this metric already covers this period.",
    "details": { "conflicting_goal_id": 18 }
  }
}
```

| Status | Meaning |
|---|---|
| `400` | Malformed request |
| `401` | Not authenticated — client clears auth, redirects to login |
| `403` | Authenticated but not permitted — render denial, do not redirect |
| `404` | Not found, **or** exists but outside the requester's scope |
| `409` | Conflict (duplicate, cycle, invalid state transition) |
| `422` | Validation failed — field-level details |
| `429` | Rate limited |
| `500` | Server error — generic message, full detail logged server-side |

**403 vs 404 matters.** If a manager requests a goal outside their scope, returning `403` confirms the goal exists — that's information leakage. Out-of-scope resources return `404`, identical to nonexistent ones. `403` is reserved for cases where the resource is in scope but the action isn't permitted.

Validation errors (`422`) carry field paths so React Hook Form can attach them to inputs directly:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "Some fields need attention.",
    "details": {
      "fields": [
        { "path": "target_value", "message": "Must be greater than zero." },
        { "path": "assignments.0.user_id", "message": "User not found." }
      ]
    }
  }
}
```

`code` is stable and machine-readable; `message` is human-facing and may change. Clients branch on `code`, never on message text.

## Request/response modeling

Separate Pydantic models per direction:

```python
class GoalCreate(BaseModel):     # what the client may send
    metric_definition_id: int
    target_value: Decimal
    ...

class GoalUpdate(BaseModel):     # all fields optional
    target_value: Decimal | None = None
    ...

class GoalRead(BaseModel):       # what the server returns
    id: int
    created_at: datetime
    progress: GoalProgress
    ...
```

**Why not one model:** a single shared model lets a client send `id` or `created_at` and invites mass-assignment bugs. Separate models make the writable surface explicit, and give the generated TS client accurate types for each direction — `GoalCreate` requires `target_value`, `GoalUpdate` doesn't.

## Embedded data

Frequently co-needed data is embedded rather than requiring a second request:

```json
{
  "id": 42,
  "target_value": "50000.0000",
  "metric": { "id": 4, "name": "Revenue Closed", "unit": "currency", "decimal_places": 0 },
  "progress": { "current_value": "32400.0000", "percent": 64.8, "status": "on_track" }
}
```

The rule: embed what the UI always needs to render the object; link by ID for the rest. Rendering a goal always requires the metric's name and unit, so a separate fetch is guaranteed waste. This is chosen deliberately over the flexibility of GraphQL — the client's needs are known and stable.

Avoid generic `?expand=` parameters. They make responses unpredictable and the generated types become unions the client has to narrow constantly.

## Idempotency

- `PATCH` and `DELETE` are naturally idempotent.
- `POST /api/imports/{id}/commit` takes an `Idempotency-Key` header, so a double-click or a retry after a timeout can't import the same file twice.
- Connector writes to `metric_fact` are idempotent through the `(data_source_id, external_id, occurred_at)` unique index — see [02-data-model.md](02-data-model.md).

## Rate limiting

Applied at the API layer, per user and per IP:

| Endpoint class | Limit |
|---|---|
| `POST /api/auth/login` | 5 / 15 min per account, 20 / 15 min per IP |
| Password reset | 3 / hour per account |
| Import upload | 10 / hour per user |
| General authenticated | 300 / min per user |
| Display token endpoints | 120 / min per token |

Login limits are the important ones — they're what stops credential stuffing against a self-hosted instance that may be internet-exposed.

## Versioning

**No version prefix in v1.** The API and its only client ship together in the same Docker image, so they can't drift.

If a public API is ever exposed, versioning is introduced then via `/api/v2`. Adding `/api/v1` now would be ceremony with no benefit.

## OpenAPI

Every endpoint carries a `summary`, a `response_model`, and documented error responses. This isn't optional politeness — it's the input to client generation. An endpoint without a `response_model` produces an untyped `any` in TypeScript and silently removes type safety at that call site.

```python
@router.get(
    "/goals/{goal_id}",
    response_model=GoalRead,
    summary="Get a goal with computed progress",
    responses={404: {"model": ErrorResponse}},
)
```

## Related docs

- [01-architecture.md](01-architecture.md)
- [13-frontend-architecture.md](13-frontend-architecture.md)
- [17-security.md](17-security.md)
