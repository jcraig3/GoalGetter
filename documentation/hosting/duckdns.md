# A free DuckDNS name

Part of [Hosting GoalGetter](../20-hosting.md). Read its [Before you start](../20-hosting.md#before-you-start) first: a fixed address, and the firewall.

For a trusted certificate when you have no domain at all.
[DuckDNS](https://www.duckdns.org) gives out free names like
`acme-goals.duckdns.org`, and Let's Encrypt issues certificates for them.

1. Sign in at duckdns.org and create a subdomain, e.g. `acme-goals`. Set its
   **current ip** to the server's private address, `192.168.1.149`, and copy the
   **token** shown at the top of the page.
2. In **Settings → Hosting → Change**: **A free DuckDNS name**, **Name**
   `acme-goals.duckdns.org`, paste the token, **Check** (DuckDNS accepts the
   token, the name points at this server), **Switch over**, then **Keep** once
   `https://acme-goals.duckdns.org` opens. Until then the old address keeps
   working ([Changing it safely](../20-hosting.md#changing-it-safely)).
   - **Or in `.env`**, picked up within half a minute:
     ```bash
     HTTPS_HOST=acme-goals.duckdns.org
     HTTPS_CERTIFICATE=letsencrypt
     DNS_PROVIDER=duckdns
     DNS_API_TOKEN=<your DuckDNS token>
     ```
3. Add `https://acme-goals.duckdns.org/api/auth/sso/callback` in Azure.

**Two cautions.** DuckDNS is a free volunteer service, so if it goes down,
renewals can fail. And some office routers refuse public names that lead to
private addresses ("DNS rebinding protection"), which makes the name fail to
load on your network. Fix that by allowing `duckdns.org` in the router's
settings, or use option B.
