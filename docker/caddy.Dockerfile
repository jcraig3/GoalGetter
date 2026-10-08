# Caddy with the two DNS providers `letsencrypt` mode knows how to use.
#
# Stock Caddy has no DNS plugins, and proving a name with a DNS record is the
# only way to get a public certificate for a server the internet cannot reach.
# `internal` and `files` certificates use none of this, but one image keeps
# switching certificates to a click in Settings → Hosting.

FROM caddy:2.10-builder-alpine AS build
RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/caddy-dns/duckdns

FROM caddy:2.10-alpine
COPY --from=build /usr/bin/caddy /usr/bin/caddy
