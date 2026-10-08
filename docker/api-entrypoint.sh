#!/usr/bin/env sh
# Migrations run before the server starts, so the container is never reachable
# against a schema it doesn't expect.
#
# This is safe to do automatically because Postgres has transactional DDL: a
# failed migration rolls back completely and this script exits non-zero, so the
# container stops rather than serving a half-migrated database.
set -e

# **Started as root only to hand over two folders, then never again** (Phase
# 20). Settings → Hosting writes uploaded certificates, nginx's HTTPS address
# and the tunnel's token into them, and Docker creates a missing folder as root. So: give
# those two to the app's own user, and carry on as that user — the app itself
# never runs as root. Skipped when started as someone else already.
if [ "$(id -u)" = 0 ]; then
  for dir in /hosting/certs /run/goalgetter-nginx /run/goalgetter-tunnel; do
    if [ -d "$dir" ]; then
      chown -R goalgetter:goalgetter "$dir" 2>/dev/null || true
    fi
  done
  exec setpriv --reuid=goalgetter --regid=goalgetter --init-groups "$0" "$@"
fi

echo "==> Applying migrations"
alembic upgrade head

echo "==> Starting API"
exec "$@"
