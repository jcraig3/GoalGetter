#!/bin/sh
# Tells nginx the HTTPS address, so its plain port can serve TVs only (P5-3),
# and follows the app when it changes (Phase 20).
#
# Runs before nginx starts: the official image runs every executable script in
# /docker-entrypoint.d/. nginx includes /etc/nginx/gg/https.conf:
#
#   set $gg_https_address "https://goals.internal";   # HTTPS on
#   set $gg_https_address "";                         # HTTPS off
#
# **The app writes that file** (api/app/hosting_config.py), into a volume it
# shares with nginx, whenever HTTPS changes in Settings → Hosting. This script
# only fills it in on the very first start, before the app has said anything,
# from .env: HTTPS is on when HTTPS_HOST is set. Then it watches the file and
# reloads nginx when it changes, so no restart is ever needed.
set -eu

conf=/etc/nginx/gg/https.conf
mkdir -p /etc/nginx/gg

if [ -s "$conf" ]; then
  echo "web-https: using the HTTPS address the app wrote"
else
  address=""
  host="${HTTPS_HOST:-}"
  port="${HTTPS_PORT:-443}"
  if [ -n "$host" ]; then
    # A host name or address and nothing else: it is written into nginx's
    # config, so a quote or a space must never get there.
    if printf '%s' "$host" | grep -Eq '^[A-Za-z0-9.:-]+$' && printf '%s' "$port" | grep -Eq '^[0-9]+$'; then
      suffix=""
      [ "$port" = "443" ] || suffix=":$port"
      address="https://$host$suffix"
    else
      echo "web-https: HTTPS_HOST or HTTPS_PORT looks wrong; the plain port stays a full app" >&2
    fi
  fi
  printf 'set $gg_https_address "%s";\n' "$address" > "$conf"
  if [ -n "$address" ]; then
    echo "web-https: plain port serves TVs only; everything else goes to $address"
  fi
fi

# The app (uid 1000) rewrites it from now on.
chown -R 1000:1000 /etc/nginx/gg 2>/dev/null || true

# **Follow the app's changes without a restart.** Every few seconds, reload
# nginx if the file changed. Left running in the background; the entrypoint
# then starts nginx in the foreground as usual.
(
  last="$(md5sum "$conf" 2>/dev/null || true)"
  while sleep 5; do
    now="$(md5sum "$conf" 2>/dev/null || true)"
    if [ "$now" != "$last" ]; then
      last="$now"
      if nginx -t -q 2>/dev/null; then
        nginx -s reload && echo "web-https: HTTPS address changed; nginx reloaded"
      fi
    fi
  done
) &
