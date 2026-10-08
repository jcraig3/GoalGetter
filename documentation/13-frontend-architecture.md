# Frontend Architecture

**Phase 1.** React SPA served as static files by nginx.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Framework | React 19 + TypeScript | Largest ecosystem for data-dense UI |
| Build | Vite | Fast HMR, simple config, no framework conventions to fight |
| Routing | React Router v6 | Standard, well understood, nested layouts |
| Server state | TanStack Query | Caching, refetch intervals, invalidation — exactly what a polling dashboard needs |
| Client state | React Context + `useState` | There isn't enough global client state to justify Redux/Zustand |
| Forms | React Hook Form + Zod | Uncontrolled inputs (fast), schema validation shared with the API contract |
| Styling | Tailwind CSS | Utility classes keep styling co-located with markup |
| Components | hand-written | No component library yet. Add one only if a real need appears — every dependency is weight. |
| Charts | Recharts | Composable, adequate, reasonable size |
| API client | Generated from OpenAPI | Never hand-written |

## Why TanStack Query is the important choice here

Almost all of this app's state is **server state** — leaderboards, goals, users. Server state has properties client state doesn't: it goes stale, it needs refetching, multiple components want the same data, and it must be invalidated after a mutation.

Managing that with `useEffect` and `useState` means reimplementing caching, deduplication, and refetching by hand in every component. TanStack Query does it declaratively:

```tsx
// Leaderboard that refreshes every 30s, deduped across every component using it
const { data, isLoading } = useQuery({
  queryKey: ['leaderboard', id, periodAnchor],
  queryFn: () => api.leaderboards.getResults(id, periodAnchor),
  refetchInterval: 30_000,
  staleTime: 15_000,
});
```

Three components rendering the same leaderboard produce **one** network request. That's what makes polling viable without a WebSocket layer.

Redux is deliberately excluded: once server state is handled properly, the remaining global client state is the current user, theme, and sidebar collapse. Context covers that.

## Directory structure

What exists today:

```
web/src/
├── main.tsx          entry
├── App.tsx           routes
├── auth.tsx          AuthProvider, RequireAuth, RequireCapability, Can, useAuth
├── api.ts            fetch wrapper: errors, 401 handling
├── theme.css         design tokens + Tailwind mapping
├── components/       AppShell, Field, Avatar, MetricValue, HandoffLink,
│                     EmptyState, PageHeader, ActivityLog, Toasts, Loading,
│                     PeoplePicker, ConfirmHost, Breadcrumb,
│                     ChangePassword, Toggle, icons
└── pages/            Login, Setup, AcceptInvite, ResetPassword, Dashboard,
                      Account, Teams, Offices, Users, Metrics, Corrections,
                      Channels, Settings, Integrations, Placeholder
```

Still two folders. Every "we'll need a `lib/` for this" moment so far has been
one function that had a natural home in the file already using it.

### How this grows

Add a folder when something needs it, not before:

| Add | When |
|---|---|
| `pages/<area>/` subfolders | a page grows past one file |
| `lib/` | there is a second formatter or date helper to share |
| `api/schema.d.ts` | the first endpoint returning real data (generated from OpenAPI) |
| `hooks/` | a hook is used by two unrelated pages |

An earlier attempt created `routes/`, `features/`, `components/ui|layout|data`,
`hooks/`, `lib/`, and `styles/` up front. Most stayed empty, the
`features/` vs `components/` distinction produced constant "where does this
go?" hesitation, and the whole thing was deleted.

**The one rule worth keeping:** `components/` holds things with no domain
knowledge — a text field, a button. Anything that understands goals or
leaderboards lives with the page that uses it until a second page needs it.
Dependency direction only ever points inward: pages may import components,
never the reverse.

For a cautionary example, IT Hub's frontend has 127 files in one flat
`components/` directory. That is what happens without a rule.

## Data flow

```
Component
   │ useQuery(['goals', filters])
   ▼
TanStack Query cache ──hit──▶ instant render
   │ miss / stale
   ▼
Generated API client ──▶ fetch('/api/goals', {credentials:'include'})
   ▼
nginx ──▶ FastAPI
   ▼
Typed response ──▶ cache ──▶ every subscribed component re-renders
```

Mutations invalidate rather than manually patching:

```tsx
const createGoal = useMutation({
  mutationFn: api.goals.create,
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['goals'] }),
});
```

**Why invalidate instead of updating the cache by hand:** goal progress is computed server-side from metric facts. Hand-patching the cache would show a fabricated value that disagrees with the server. Refetching is one extra request and is always correct. Optimistic updates are reserved for genuinely trivial mutations like marking a notification read.

## The generated API client

```
FastAPI ──▶ /openapi.json ──▶ openapi-typescript ──▶ src/api/schema.d.ts
```

Run via `npm run generate:api` whenever backend routes or schemas change, and in CI to catch drift.

This is what neutralizes the two-language cost. Rename a Pydantic field, regenerate, and `tsc` fails at every affected call site — the same feedback a single-language stack gives.

**Rule: never hand-edit the generated file.** Regeneration overwrites it. Generate *types only*, not a client: an earlier attempt used a generator that vendored 16 files and 57.6 KB of HTTP-client runtime into `src/`, of which nothing was imported. `openapi-typescript` emits one 5.2 KB file. Library code belongs in `node_modules`; generated types belong in `src/`.

`src/api/client.ts` is hand-written and thin — it configures `credentials: 'include'` for session cookies, attaches the CSRF token, and maps errors:

- `401` → clear auth state, redirect to `/login`, preserve destination
- `403` → render a permission-denied view (not a redirect; the user is legitimately signed in)
- `422` → surface field-level validation errors to the form
- `5xx` → generic error boundary with a retry

Handling this once means no route ever writes auth-error handling.

## Routing

Built today:

```
outside the shell — nobody here is signed in, so there is no nav to show
/login
/setup                    only while zero users exist
/accept-invite?token=     set a password from an invitation
/reset-password?token=    set a password from an admin-issued reset link

inside the shell
/                         overview: how are we doing
/account                  everything about you
/leaderboards             placeholder — 1f
/goals                    placeholder — 1e
/offices                  offices.manage
/teams
/competitions             placeholder — phase 2
/channels                 the TV guide
/users                    users.view
/metrics                  metrics.manage
/corrections              metrics.correct
/integrations             integrations.manage
/settings                 org.settings.edit  (+ Recent activity)
```

No `/admin/*` prefix. It was in the original plan and bought nothing: the
capability on the route already decides who gets in, so the prefix only made
URLs longer and forced a second decision ("is this admin enough?") for every
new page.

Guards read as capabilities, never roles:

```tsx
<Route path="/settings" element={
  <RequireCapability capability="org.settings.edit"><Settings /></RequireCapability>
} />
```

`/display/:token` for TV mode will sit outside `AppShell` entirely — it shares components but not layout. Not built yet; it arrives with leaderboards.

### Home is not about you

`/` answers *how are we doing*. `/account` answers *who am I*. They started
merged, and the result was that the first screen everyone saw was half occupied
by facts each person already knew about themselves.

The account area is reached by clicking your name in the top bar, which is a
**link, not a dropdown**. A dropdown would add focus trapping, click-outside
handling, and escape-key handling to hold a single destination.

**Sign out lives at the bottom of `/account`**, not in the top bar. It is the
one control on the page that ends what you were doing, so it is the only red
one — and moving it off the chrome means it is no longer a mis-click away from
every screen in the app. It is also where someone already goes to change their
password, so the two account-level actions sit together instead of one being
permanently on screen and the other buried.

## Auth on the client

```tsx
<AuthProvider>          // hydrates from GET /api/auth/me
  <RequireAuth>         // redirects if unauthenticated
    <Can do="goals.create">   // hides UI by capability
```

`AuthProvider` fetches `/api/auth/me` once at startup and holds `{ user, capabilities, scope }`. The session cookie is HTTP-only, so JavaScript never touches a token — it just discovers whether the cookie works.

**The client enforces nothing.** `<Can>` is UX. Every check duplicates a server-side check.

## Performance

- **Route-level code splitting** via `React.lazy`. Admin and TV routes shouldn't ship in the main bundle.
- **`staleTime` per query type** — metric definitions change rarely (5 min); leaderboard results change constantly (15s).
- **Virtualize lists over ~100 rows** (`@tanstack/react-virtual`). A 500-person org leaderboard renders 20 rows, not 500.
- **Poll only what's visible.** Pause `refetchInterval` when the tab is hidden — a TV left on overnight shouldn't hammer the API for 14 hours.

## Testing

| Layer | Tool | What's covered |
|---|---|---|
| Unit | Vitest | Formatters, date/period math, pure helpers |
| Component | Vitest + Testing Library | Component behavior with mocked API |
| Integration | MSW | Full flows against a mocked API |
| E2E | Playwright | Critical paths: login, create goal, view leaderboard |

Priority order: **date/period math first.** It's pure, it's where the subtle bugs live, and a wrong week boundary corrupts every number downstream.

## Open questions

1. **PWA / installable?** Agents checking rank on a phone would benefit. Adds service worker cache-invalidation complexity. *Leaning: defer past v1.*
2. **i18n** — worth wiring the plumbing now even if only English ships? Retrofitting is painful. *Leaning: no hard-coded strings in components; keep a strings module, skip a full i18n library.*
3. **Should `/display/:token` be a separate build?** It shares components but has different perf characteristics. *Leaning: same build, lazy-loaded route.*

## Related docs

- [12-design-system.md](12-design-system.md)
- [14-api-conventions.md](14-api-conventions.md)
- [19-dev-workflow.md](19-dev-workflow.md)
