#!/usr/bin/env bash
# GoalGetter — pull-based deploy.
#
# Checks the branch on a schedule and, only if it moved, rebuilds and applies
# it. Intended for cron on the production host:
#
#   chmod +x ~/GoalGetter/deploy/auto-pull.sh
#   ( crontab -l 2>/dev/null; echo "17 * * * * $HOME/GoalGetter/deploy/auto-pull.sh" ) | crontab -
#
# STATUS: not yet exercised — written alongside the production overlay and
# reviewed, but never run against a real host. Verify manually on the first
# deploy before trusting it to cron.
set -euo pipefail

PROJECT_DIR="${GG_DIR:-$HOME/GoalGetter}"
BRANCH="${GG_BRANCH:-main}"
LOG="${GG_LOG:-$HOME/goalgetter-deploy.log}"

log() { echo "$(date -Is) $*" >>"$LOG"; }

# Single-instance guard: a slow build must not overlap the next cron tick.
exec 9>"$HOME/.goalgetter-deploy.lock"
if ! flock -n 9; then
  log "another run in progress — skipping"
  exit 0
fi

cd "$PROJECT_DIR"

git fetch --quiet origin "$BRANCH"
local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse "origin/$BRANCH")"

if [ "$local_rev" = "$remote_rev" ]; then
  log "up to date (${local_rev:0:9})"
  exit 0
fi

log "updating ${local_rev:0:9} -> ${remote_rev:0:9}"

# Fast-forward only: never auto-merge. If this fails, someone edited files on
# the server — that is logged and left alone rather than clobbered.
if ! git merge --ff-only "origin/$BRANCH" >>"$LOG" 2>&1; then
  log "ERROR: fast-forward failed (local changes on the server?) — left untouched"
  exit 1
fi

# Back up before applying, since a deploy may carry a migration. Migrations run
# automatically on API start and Postgres rolls a failed one back completely,
# but a dump costs seconds and removes all doubt.
log "taking a pre-deploy backup"
docker compose exec -T db-backup /usr/local/bin/db-backup.sh >>"$LOG" 2>&1 || \
  log "WARNING: pre-deploy backup failed — continuing"

# Rebuild and recreate. Unlike a bind-mounted deployment, production bakes code
# into images: a code change produces a new image, so Compose recreates the
# affected containers on its own. No path-matching heuristic needed to work out
# which services to restart.
log "building and applying"
docker compose up -d --build >>"$LOG" 2>&1

docker image prune -f >>"$LOG" 2>&1 || true

log "deploy complete (${remote_rev:0:9})"
