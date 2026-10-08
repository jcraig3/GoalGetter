# Behind your own reverse proxy

Part of [Hosting GoalGetter](../20-hosting.md). Read its [Before you start](../20-hosting.md#before-you-start) first: a fixed address, and the firewall.

Already running nginx, IIS, Traefik or a load balancer with certificates?
Leave HTTPS off in Settings → Hosting and point your proxy at
`http://<server>:8080`. (GoalGetter's Caddy still holds ports 443 and 80; if
your proxy runs on the same server, move Caddy's with `HTTPS_PORT` and
`HTTP_PORT` in `.env`, then `docker compose up -d`.) It needs to:

- send `X-Forwarded-Proto: https` (GoalGetter uses it to make session cookies
  HTTPS-only),
- append the visitor to `X-Forwarded-For`, then in **Settings → Hosting →
  Advanced → A proxy in front of GoalGetter?** choose **Yes** (or set
  `TRUSTED_PROXY_HOPS=2` in `.env`). GoalGetter then reads the entry your
  proxy added. Left as it is, every visitor looks like your proxy, and one
  person's failed sign-ins lock out everybody. Settings only accepts "Yes"
  when the page itself came through a proxy that passed an address, so open
  it through your proxy's address to set it,
- allow uploads up to 25 MB, and keep requests open for 120 seconds
  (imports can take a while).

Only your proxy should reach port 8080 then. With `TRUSTED_PROXY_HOPS=2`,
somebody connecting to it directly could choose the address they appear to
come from.

Then sign in and set **Settings → Hosting → Advanced → Web address** to the
address your proxy serves, e.g. `https://goals.company.com`.
