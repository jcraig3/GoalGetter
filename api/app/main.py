import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app import jobs, validation
from app.config import get_settings
from app.db import SessionLocal
from app.routers import (
    admin_sso,
    announcements as announcements_api,
    assets as assets_api,
    audit,
    auth,
    backgrounds as backgrounds_api,
    channels as channels_api,
    competitions as competitions_api,
    dashboard,
    data_sources,
    display_feed,
    economy,
    directory as directory_admin,
    displays,
    excel as excel_admin,
    sheets as sheets_admin,
    warehouse as warehouse_admin,
    freshness,
    game_boards as game_boards_api,
    goal_bulk,
    goal_preview,
    search as search_api,
    sounds as sounds_api,
    goals,
    images,
    inbox as inbox_api,
    health,
    hooks,
    hosting,
    leaderboards,
    metric_facts,
    metrics,
    metrics_query,
    notifications as notifications_api,
    oauth_clients,
    offices,
    organization,
    passwords,
    people,
    points as points_api,
    recognition,
    tv_announcements,
    reporting,
    roles as roles_api,
    setup,
    smtp as smtp_admin,
    sso,
    mfa as mfa_api,
    teams,
    teams_mirror,
    users,
)

settings = get_settings()

# Without this the root logger sits at WARNING and every logger.info() in the
# codebase is discarded — including the ones recording rejected sign-ins.
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

# How often the scheduled jobs run. Hourly rather than daily-at-a-time on
# purpose: every job is idempotent, so running one more often than strictly
# needed costs a handful of indexed queries, and it removes the entire class of
# "the container was down at 02:00" problems. A goal for a new period appears
# within an hour of that period starting.
JOB_INTERVAL_SECONDS = 3600


async def _job_loop() -> None:
    """Run the scheduled jobs forever, one at a time.

    A plain loop rather than APScheduler. The only schedule this needs is
    "every so often", and idempotency already handles missed and duplicate
    runs — which is most of what a scheduler library buys. Adding a dependency,
    a job store, and a second lifecycle to express `while True: sleep` would be
    more moving parts than the problem has.

    Runs in a thread so a slow query cannot block the event loop serving
    requests.
    """
    while True:
        try:
            await asyncio.to_thread(_run_jobs_once)
        except Exception:  # noqa: BLE001 — a failed job must never stop the loop
            logger.exception("jobs: run failed, continuing")
        await asyncio.sleep(JOB_INTERVAL_SECONDS)


#: How often hosting catches up with .env and Caddy (Phase 20): an edit made in
#: .env reaches the app, and a restarted Caddy gets its configuration back.
HOSTING_INTERVAL_SECONDS = 30


async def _hosting_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(_reconcile_hosting_once)
        except Exception:  # noqa: BLE001 — never stops the loop
            logger.exception("hosting: reconcile failed, continuing")
        await asyncio.sleep(HOSTING_INTERVAL_SECONDS)


def _reconcile_hosting_once() -> None:
    from app import hosting_config

    db = SessionLocal()
    try:
        problem = hosting_config.reconcile(db)
        if problem:
            logger.warning("hosting: Caddy did not take the configuration: %s", problem)
    finally:
        db.close()


def _run_jobs_once() -> None:
    db = SessionLocal()
    try:
        jobs.run_all(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Started here rather than in a separate container so a deployment is still
    # one `docker compose up`. The advisory lock in jobs.run_all means running
    # several API replicas does not run the work several times.
    task = asyncio.create_task(_job_loop())
    # Not under the test suite: it works on its own session, so a row it
    # created would outlive the test that caused it.
    hosting = asyncio.create_task(
        _hosting_loop() if not os.environ.get("GOALGETTER_NO_HOSTING_LOOP") else asyncio.sleep(0)
    )
    try:
        yield
    finally:
        task.cancel()
        hosting.cancel()
        # Awaiting the cancellation means shutdown waits for a job mid-run,
        # rather than tearing its database session out from under it.
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(asyncio.CancelledError):
            await hosting


app = FastAPI(title="GoalGetter API", version="0.1.0", lifespan=lifespan)

# Every refusal of something typed, said in words a person can act on — see
# `app/validation.py`. Same shape as FastAPI's own 422.
app.add_exception_handler(RequestValidationError, validation.handle)


# Everything is mounted under /api so nginx can proxy a single prefix and serve
# the SPA from the same origin. One origin means no CORS and no SameSite cookie
# workarounds.
app.include_router(health.router, prefix="/api")
app.include_router(setup.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(mfa_api.router, prefix="/api")
app.include_router(sso.router, prefix="/api")
app.include_router(organization.router, prefix="/api")
app.include_router(offices.router, prefix="/api")
app.include_router(teams.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(admin_sso.router, prefix="/api")
app.include_router(smtp_admin.router, prefix="/api")
app.include_router(directory_admin.router, prefix="/api")
app.include_router(teams_mirror.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(images.router, prefix="/api")
app.include_router(assets_api.router, prefix="/api")
app.include_router(backgrounds_api.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
# Registered after metrics.router so /metrics/query is matched by this
# router; the other one has no conflicting path, but order is explicit.
app.include_router(metrics_query.router, prefix="/api")
app.include_router(metric_facts.router, prefix="/api")
app.include_router(passwords.router, prefix="/api")
app.include_router(hosting.router, prefix="/api")
app.include_router(search_api.router, prefix="/api")
app.include_router(sounds_api.router, prefix="/api")
# Before goals.router, so nothing under /goals/bulk is ever read as a goal id.
app.include_router(goal_bulk.router, prefix="/api")
app.include_router(goals.router, prefix="/api")
# Registered after goals.router: both use the /goals prefix, and
# /goals/preview must not be swallowed by /goals/{goal_id}.
app.include_router(goal_preview.router, prefix="/api")
app.include_router(leaderboards.router, prefix="/api")
app.include_router(displays.router, prefix="/api")
app.include_router(channels_api.router, prefix="/api")
# Public: a wall screen has no session. The token in the path is the
# entire credential, and it grants one read-only channel.
app.include_router(display_feed.router, prefix="/api")
# Public, and the only unauthenticated *write*. The token in the path is the
# credential; it grants appending to one source's inbox and nothing else.
app.include_router(hooks.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(inbox_api.router, prefix="/api")
app.include_router(reporting.router, prefix="/api")
app.include_router(roles_api.router, prefix="/api")
app.include_router(points_api.router, prefix="/api")
app.include_router(economy.router, prefix="/api")
app.include_router(announcements_api.router, prefix="/api")
app.include_router(game_boards_api.router, prefix="/api")
app.include_router(notifications_api.router, prefix="/api")
app.include_router(recognition.router, prefix="/api")
app.include_router(tv_announcements.router, prefix="/api")
app.include_router(competitions_api.router, prefix="/api")
app.include_router(data_sources.router, prefix="/api")
app.include_router(freshness.router, prefix="/api")
app.include_router(oauth_clients.router, prefix="/api")
app.include_router(excel_admin.router, prefix="/api")
app.include_router(sheets_admin.router, prefix="/api")
app.include_router(warehouse_admin.router, prefix="/api")
app.include_router(people.router, prefix="/api")
