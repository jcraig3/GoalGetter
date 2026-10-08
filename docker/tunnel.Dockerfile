# The Cloudflare tunnel, started and stopped by the app (Phase 21).
#
# Cloudflare's own image has nothing but cloudflared — no shell to watch for
# the token the app hands over — so its binary goes onto Alpine with
# docker/tunnel.sh, which does. Pinned, so an update is a deliberate change.

FROM cloudflare/cloudflared:2026.10.0 AS cloudflared

FROM alpine:3.22
COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY docker/tunnel.sh /usr/local/bin/tunnel.sh
# Owned by the same user as the API, which writes the token here. A new
# volume takes this folder's owner.
RUN mkdir -p /run/goalgetter-tunnel && chown 1000:1000 /run/goalgetter-tunnel
USER 1000:1000
ENTRYPOINT ["/bin/sh", "/usr/local/bin/tunnel.sh"]
