#!/bin/sh
# Nightly database dump with retention.
#
# pg_dump (not pg_dumpall) because this deployment has one database — the dump
# is smaller and restoring it is a single command with no role juggling.
set -eu

KEEP=${BACKUP_KEEP:-14}
STAMP=$(date +%Y%m%d-%H%M%S)
TARGET="/backups/goalgetter-$STAMP.sql.gz"

echo "[db-backup] starting $STAMP"

if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
      -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      | gzip > "$TARGET"; then
    echo "[db-backup] wrote $TARGET ($(du -h "$TARGET" | cut -f1))"
    # Delete oldest beyond KEEP. Runs only on success, so a failed dump can
    # never trigger deletion of good backups.
    ls -1t /backups/goalgetter-*.sql.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
else
    echo "[db-backup] FAILED" >&2
    # Remove the truncated file so it can't be mistaken for a usable backup.
    rm -f "$TARGET"
    exit 1
fi
