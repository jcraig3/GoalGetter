#!/bin/sh
# The Cloudflare tunnel, run when the app says so (Phase 21).
#
# Always running, and idle until Settings → Hosting turns a tunnel on. The API
# writes the tunnel's token to /run/goalgetter-tunnel/token, in a volume only
# the two share; this starts cloudflared when that file has a token, restarts
# it when the token changes, and stops it when the file is emptied. No Docker
# socket, no restart of this container.
#
# For the app: `alive` is touched every few seconds (so it can tell this is
# running), cloudflared's output goes to `cloudflared.log` (its last error is
# shown on the Hosting tab), and cloudflared's /ready on :2000 says whether it
# is connected.
set -u

dir=/run/goalgetter-tunnel
token="$dir/token"
log="$dir/cloudflared.log"
pid=""
running=""
started=0

stop() {
  if [ -n "$pid" ]; then
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    pid=""
  fi
}

start() {
  cloudflared tunnel --no-autoupdate --metrics 0.0.0.0:2000 run --token-file "$token" >>"$log" 2>&1 &
  pid=$!
  started=$(date +%s)
}

trap 'stop; kill $follower 2>/dev/null; exit 0' TERM INT

: >"$log"
# cloudflared's output in `docker compose logs tunnel` too.
tail -n 0 -F "$log" 2>/dev/null &
follower=$!

while :; do
  touch "$dir/alive"
  want=""
  [ -s "$token" ] && want="$(md5sum "$token" | cut -d' ' -f1)"
  if [ "$want" != "$running" ]; then
    stop
    running="$want"
    : >"$log"
    if [ -n "$want" ]; then
      echo "tunnel: starting"
      start
    else
      echo "tunnel: stopped"
    fi
  elif [ -n "$want" ] && [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
    # cloudflared gave up — Cloudflare refused the token, say. Its error stays
    # in the log for the app to show; try again once a minute.
    if [ $(($(date +%s) - started)) -ge 60 ]; then
      start
    fi
  fi
  # Keep the log small; cloudflared appends, so emptying it is safe.
  if [ "$(wc -c <"$log")" -gt 524288 ]; then
    : >"$log"
  fi
  sleep 3
done
