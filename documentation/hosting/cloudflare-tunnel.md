# A Cloudflare tunnel: goalgetter.company.com

Part of [Hosting GoalGetter](../20-hosting.md). Read its [Before you start](../20-hosting.md#before-you-start) first: a fixed address, and the firewall.

**Cloudflare holds the certificate and answers the internet. Nothing on your
server is opened.** A small connector, `cloudflared`, runs beside GoalGetter
and makes an outgoing connection to Cloudflare. Visitors reach
`https://goalgetter.company.com` at Cloudflare, and Cloudflare passes each
request down that connection.

```
 visitor ──https──▶ Cloudflare ──tunnel──▶ cloudflared (on the server) ──▶ nginx :81 ──▶ GoalGetter
                   (certificate)              outgoing only, no open port
```

- **Caddy serves nothing.** GoalGetter's own HTTPS stays off; Cloudflare does that part.
- **A certificate every device already trusts.** Cloudflare issues and renews
  it, with nothing to install anywhere, and TVs are happy too.
- **Visitors' addresses come through**, even on Docker Desktop: Cloudflare
  writes each visitor's address into the request, and the connector goes to
  nginx's front-door listener (`:81`), which keeps it.
- **Free**, on Cloudflare's free plan.

## Before you choose it

- **It's reachable from the internet.** Anybody with the address sees the
  sign-in page, wherever they are. That's convenient for people working from
  home, and it's also the point of the sign-in limits. To keep it to your
  staff, put [Cloudflare Access](#limiting-who-can-reach-it) in front.
- **Traffic passes through Cloudflare.** Cloudflare decrypts it at its edge;
  that's how it can hold the certificate. If everything must stay inside your
  network, use [B](own-certificate.md), [C](company-domain.md) or
  [G](windows-front-door.md) instead.
- **One office, one address.** Through the internet, every PC in an office
  shares the office's public address. The per-device sign-in limit (20 wrong
  passwords in five minutes) then counts the whole office together. For a
  big office, raise it under **Settings → Sign-in & security**. The
  per-account limit is unaffected.

## You need

- A domain whose DNS is on **Cloudflare** (`company.com`). Moving a domain's
  DNS to Cloudflare is free.
- A Cloudflare account with **Zero Trust** turned on. Tunnels are part of its
  free plan.

## 1. Turn it on

In **Settings → Hosting → Change**:

1. **How:** **Cloudflare tunnel**.
2. **Set up:** **Name** `goalgetter.company.com`. The **Outside GoalGetter**
   checklist has three steps:
   1. In the [Cloudflare dashboard](https://one.dash.cloudflare.com):
      **Zero Trust → Networks → Tunnels → Create a tunnel**, type
      **Cloudflared**. Name it `goalgetter`.
   2. Copy the install command Cloudflare shows and paste it into **Tunnel
      token**. Just the token works too: GoalGetter finds it in whatever you
      paste. Don't run the command; GoalGetter runs the connector for you.
   3. Still in the tunnel, add a **Public hostname**: your name, service
      `http://web:81` (to copy from the checklist).

   **Check** confirms the token and that the name is in DNS.
3. **Switch over.** Try it shows **Connecting the tunnel…**, then **The tunnel
   is connected · 4 connections to Cloudflare**. If it can't connect, it says
   why in plain words, such as "Cloudflare doesn't accept this token". Once
   `https://goalgetter.company.com` opens, **Keep**.

**`web:81`, not `web:80` or `localhost:8080`.** Port 81 is nginx's listener
for a front door: it keeps the visitor's address Cloudflare wrote, and it
knows the visitor came in over HTTPS. Pointed at port 80, every visitor
would look like the connector.

**No restart, no lockout.** The `tunnel` service is always running, idle
until a tunnel is turned on; the app hands it the token and it connects.
Until you keep it, the old way in keeps working
([Changing it safely](../20-hosting.md#changing-it-safely)); then
`http://<server>:8080` serves TVs only — and only while the tunnel is
connected, so a tunnel that drops never strands it. Invite links and Microsoft sign-in use
`https://goalgetter.company.com`, and session cookies are HTTPS-only.

**The token is stored encrypted** and never shown again: the field says
"Saved", with the first characters of the tunnel's id so you can tell which
tunnel it is for. Paste a new one to replace it.

**Or in `.env`**, picked up within half a minute:

```bash
HTTPS_HOST=goalgetter.company.com
HTTPS_FRONT_DOOR=cloudflare
CLOUDFLARE_TUNNEL_TOKEN=<the token>
```

The app keeps these three lines in step with Settings, both ways. Leave
`HTTPS_CERTIFICATE` alone: Cloudflare's certificate is the one in use.
`COMPOSE_PROFILES=cloudflare` is no longer needed; left in, it does no harm.

## 2. Check it

- `https://goalgetter.company.com` opens, with a padlock and no warning.
- **Settings → Hosting** says HTTPS is "On · Cloudflare", and **Tunnel**
  "Connected". **You appear as** shows an address. From inside the office,
  that's the office's public address.

## 3. Microsoft sign-in

In Azure, **App registrations** → your GoalGetter app → **Authentication** →
**Add URI**:

```
https://goalgetter.company.com/api/auth/sso/callback
```

## TVs

Either way works:

- **The HTTPS address**, `https://goalgetter.company.com/pair`. Cloudflare's
  certificate is trusted by TVs too.
- **The plain address on your network**, `http://<server address>:8080/pair`.
  It serves TVs only, and keeps working if the internet connection drops.

## Limiting who can reach it

Optional. **Zero Trust → Access → Applications → Add an application → Self-
hosted**, for `goalgetter.company.com`, with a policy such as "emails ending
in `@company.com`" or "your office's public address". People then pass
Cloudflare's check before they see GoalGetter's sign-in page.

TVs can't pass that check. Either add a second application for
`goalgetter.company.com/display` and `/pair` with a **Bypass** policy, or
point TVs at the plain address on your network.

## Not working?

- **Tunnel says "Not connected".** The reason is beside it on Settings →
  Hosting. For more, `docker compose logs tunnel`: it should say
  **Registered tunnel connection** (usually four times).
- **Connected, but the name shows a Cloudflare 502 page.** The public
  hostname's service is not `http://web:81`.

## Turning it off

In **Settings → Hosting → Change**, choose another way (or **Plain HTTP**),
**Switch over** and **Keep**: the tunnel keeps running through the trial and
stops once you keep. Or empty `HTTPS_HOST=` or `HTTPS_FRONT_DOOR=` in `.env`;
the tunnel stops within half a minute. No restart either way.

## Without a tunnel?

Cloudflare can also sit in front by DNS alone (the orange cloud), forwarding
to your server's public address. That isn't set up by default and isn't
recommended here. It needs ports forwarded from the internet to the server,
and a Cloudflare origin certificate installed as [option E](certificate-files.md).
GoalGetter would also see Cloudflare's addresses rather than visitors', so
the per-device limit wouldn't work. The tunnel avoids all three.
