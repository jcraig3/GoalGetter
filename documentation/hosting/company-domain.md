# Your own domain: goalgetter.company.com

Part of [Hosting GoalGetter](../20-hosting.md). Read its [Before you start](../20-hosting.md#before-you-start) first: a fixed address, and the firewall.

If your company already owns a domain (most Microsoft 365 companies do),
this gives you a certificate that every device already trusts, from
[Let's Encrypt](https://letsencrypt.org). It is free, renews itself, and
needs nothing installed anywhere.

The server stays private. Let's Encrypt checks that you own the name through
a temporary DNS record, so it never connects to your server. You need an API
token for the domain's DNS. GoalGetter supports **Cloudflare** directly (free,
and where many companies already keep their DNS). If yours is elsewhere, see
[the note below](#if-your-dns-is-not-on-cloudflare).

## 1. Point the name at the server

In your domain's DNS, add an **A record** `goalgetter` → `192.168.1.149`, the
server's private address. In Cloudflare, set it to **DNS only** (grey cloud,
not orange): Cloudflare's proxy cannot reach a private address.

Publishing a private address in public DNS is normal and safe: outside your
network the address leads nowhere. If your office also runs its own DNS for
the same domain ("split DNS"), add the same record there.

## 2. Make a Cloudflare API token

Cloudflare dashboard → My Profile → **API Tokens** → Create Token → use the
**Edit zone DNS** template → Zone Resources: *Include → Specific zone →
company.com* → Create. Copy the token.

## 3. Switch over

In **Settings → Hosting → Change**:

1. **How:** **Your company's domain**.
2. **Set up:** **Name** `goalgetter.company.com`, paste the **Cloudflare API
   token**. **Email** is optional: renewal warnings go there. **Check**
   confirms the name points at this server and Cloudflare accepts the token.
3. **Switch over**, then **Keep** once HTTPS answers with Let's Encrypt's
   certificate.

No restart, and the old address keeps working until you keep it
([Changing it safely](../20-hosting.md#changing-it-safely)). The first
certificate takes a minute or two; watch it with `docker compose logs -f https`.

**Or in `.env`**, picked up within half a minute:

```bash
HTTPS_HOST=goalgetter.company.com
HTTPS_CERTIFICATE=letsencrypt
DNS_PROVIDER=cloudflare
DNS_API_TOKEN=<the token>
ACME_EMAIL=it@company.com        # optional
```

## 4. Microsoft sign-in

Add `https://goalgetter.company.com/api/auth/sso/callback` in Azure, as in
[B step 4](own-certificate.md#4-microsoft-sign-in).

## If your DNS is not on Cloudflare

Choose one:

- **Put just this one name on Cloudflare.** Move the domain's DNS to Cloudflare
  (free), or have your DNS host delegate a subdomain such as
  `goals.company.com` to a free Cloudflare zone, and use names under it.
- **Ask IT for a certificate** for `goalgetter.company.com` and use
  [option E](certificate-files.md).
- **Use [option D](duckdns.md)** instead, or option B.
