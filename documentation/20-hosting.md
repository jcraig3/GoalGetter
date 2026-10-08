# Hosting GoalGetter

**Phase 13; options added through Phase 18; set up in the app since Phase 20, the tunnel since Phase 21, tried before it's kept since Phase 22.** How to run GoalGetter for real:
on one computer, across your office network, with HTTPS, and with Microsoft
sign-in working for everybody. Every option here is free. You need neither a
domain nor a paid certificate.

This page is the overview: which option suits you, the network basics they
all share, and the troubleshooting. Each option has its own step-by-step
guide in [`hosting/`](#setup-guides).

For the first install, start with [Getting started](../README.md#getting-started)
in the README. Come back here when you want other people to use it.

---

## Which option is yours?

| You want… | Option | Address people use | Cost | Each device needs… |
|---|---|---|---|---|
| To try it on your own computer | [A. Just this computer](#a-just-this-computer) | `http://localhost:8080` | Free | Nothing |
| Your office to use it, with Microsoft sign-in, and nothing to register | [B. HTTPS with GoalGetter's own certificate](hosting/own-certificate.md) **(the base option)** | `https://goals.internal` | Free | To trust the certificate once (IT can push it to every PC) |
| A name in a domain your company already owns | [C. Your own domain](hosting/company-domain.md) | `https://goalgetter.company.com` | Free | Nothing |
| A trusted certificate without owning a domain | [D. A free DuckDNS name](hosting/duckdns.md) | `https://acme-goals.duckdns.org` | Free | Nothing |
| To use a certificate IT already gave you | [E. Your own certificate files](hosting/certificate-files.md) | Whatever the certificate is for | — | Nothing, if IT's authority is trusted |
| To put it behind a proxy you already run | [F. Behind your own reverse proxy](hosting/own-proxy.md) | Whatever your proxy serves | — | — |
| A Windows server, **and** per-device sign-in limits | [G. The Windows front door](hosting/windows-front-door.md) — HTTPS on Windows itself, with any of B–E's certificates | `https://goals.internal`, or your domain | Free | As B–E |
| Cloudflare to handle the certificate for your domain, with **no port opened** on the server; paste a token in Settings → Hosting | [H. A Cloudflare tunnel](hosting/cloudflare-tunnel.md) | `https://goalgetter.company.com` | Free (Cloudflare's free plan) | Nothing |

**Why HTTPS matters here.** On one computer, plain HTTP is fine. Once other
people connect, two things need HTTPS:

- **Microsoft sign-in.** Microsoft only sends people back to an `https://`
  address. The single exception is `http://localhost`, which works only on the
  server itself.
- **Passwords and sessions.** Over plain HTTP, anybody else on the network
  can read them.

## How it fits together

```
                 ┌─────────────── this server (Docker) ───────────────┐
 browser ─https─▶│ https (Caddy)  :443  ─┐                            │
 (443)           │                       ├─▶ web (nginx) ─/api─▶ api ─▶ postgres
 TV ─────http───▶│ web (nginx)   :8080 ──┘                            │
                 └────────────────────────────────────────────────────┘
```

- **`web` (nginx)** serves the app and passes `/api` to the API. It runs in
  every option, on plain HTTP port `8080`.
- **`https` (Caddy)** sits in front of nginx when HTTPS is on. It gets the
  certificate, renews it, and passes everything through to nginx. It always
  runs, and serves nothing while HTTPS is off. The app configures it live, so
  turning HTTPS on or off needs no restart.
- **TVs can keep using port 8080.** A smart TV often cannot be told to trust a
  private certificate. TVs never sign in, so they do not need HTTPS. With
  HTTPS on, port 8080 serves **only** what a TV needs; anything else opened
  there, the sign-in page included, moves to the HTTPS address, so nobody
  types a password over plain HTTP.
- Caddy talks to nginx on a port of its own (81) that is never published, so
  GoalGetter sees each visitor's real address either way in. The other front
  doors use the same port: the Windows front door ([G](hosting/windows-front-door.md))
  and a Cloudflare tunnel ([H](hosting/cloudflare-tunnel.md)), in which case
  Caddy is not used at all.
- **`tunnel` (cloudflared)** always runs too, idle until a Cloudflare tunnel is
  turned on. The app hands it the token through a volume only the two share.

**HTTPS is set up in the app: Settings → Hosting → Change.** Choose how
people reach GoalGetter, fill in what that way needs, **Check**, **Switch
over**, and **Keep**. Every change is tried first: see
[Changing it safely](#changing-it-safely).

**`.env` is kept in step, both ways.** The app writes its hosting lines there
(`HTTPS_HOST`, `HTTPS_CERTIFICATE`, `HTTPS_FRONT_DOOR`,
`CLOUDFLARE_TUNNEL_TOKEN`, `DNS_PROVIDER`, `DNS_API_TOKEN`, `ACME_EMAIL`,
`WEB_ADDRESS`, `TRUSTED_PROXY_HOPS`), and an edit made there shows
up in the app within half a minute, no restart. Whichever changed last wins.
Nothing else in `.env` is touched. Settings shows "Kept in step with .env"
when this works. An edit there is tried like a change made in the app, and
**Undo last change** can take it back. Both show in Activity.

**A `.env` the app can't write is still followed.** On Linux the file belongs
to whoever ran setup — root, after `sudo` — and the app runs as uid 1000.
Edits made in the file still apply (so emptying `HTTPS_HOST=` always turns
HTTPS off); only the app's changes aren't written back. Settings → Hosting →
Change says so. To have both, in the GoalGetter folder: `sudo chown 1000 .env`.

Only `HTTPS_PORT` and `HTTP_PORT` still need `docker compose up -d` after a
change. `COMPOSE_PROFILES` (`https`, `cloudflare`) is no longer used; left in
an old `.env`, it does no harm.

---

## Before you start

**A server.** Any always-on Windows, Mac or Linux machine with
[Docker](https://docs.docker.com/get-docker/) works. A spare office PC is
enough for a few hundred people. Give it a fixed IP address: ask IT to reserve
one, or set one in your router. If the address changes, every link and every
TV stops working.

**Find its network address.** It looks like `10.0.0.20` or `192.168.1.20`.

- Windows: run `ipconfig` and use the **IPv4 Address** under your Ethernet or
  Wi-Fi adapter. Skip the ones named `vEthernet` (WSL, Hyper-V): other
  computers cannot reach those.
- Mac: System Settings → Network → your connection → Details.
- Linux: `ip -4 addr` or `hostname -I`.

**Let other computers in.** Allow incoming connections on port 8080, and on
443 and 80 if you turn HTTPS on.

- Windows (in an administrator PowerShell):
  ```powershell
  New-NetFirewallRule -DisplayName "GoalGetter" -Direction Inbound -Protocol TCP -LocalPort 80,443,8080 -Action Allow -Profile Domain,Private
  ```
- Linux with ufw: `sudo ufw allow 80,443,8080/tcp`

Then, from another computer or a phone on the same network, open
`http://<server address>:8080`. If the page loads, the network part is done.

**Company-managed browsers.** Extensions IT installs on every browser can
cover GoalGetter's pages — one put a cookie notice over it in testing. Ask IT
to allow GoalGetter's name (and the server's address) before rollout.

---

## A. Just this computer

What [Getting started](../README.md#getting-started) sets up. Open
`http://localhost:8080` on the server itself. Microsoft sign-in works too: in
the Azure app registration, add the redirect address
`http://localhost:8080/api/auth/sso/callback`.

Other computers can open `http://<server address>:8080` and sign in with a
password, but not with Microsoft (see [why](#which-option-is-yours)). For that,
pick one of the [setup guides](#setup-guides).

---

## Setup guides

One guide per option, each complete on its own:

| Guide | In short |
|---|---|
| [B. HTTPS with GoalGetter's own certificate](hosting/own-certificate.md) | **The base option.** A name like `goals.internal` on your office DNS; GoalGetter runs its own certificate authority; each device trusts it once, or IT pushes it to every PC |
| [C. Your own domain](hosting/company-domain.md) | `goalgetter.company.com` with a free Let's Encrypt certificate, proved through Cloudflare DNS; the server stays private |
| [D. A free DuckDNS name](hosting/duckdns.md) | A trusted certificate without owning a domain |
| [E. Your own certificate files](hosting/certificate-files.md) | A certificate from IT or one you bought, as two files |
| [F. Behind your own reverse proxy](hosting/own-proxy.md) | IIS, nginx, a load balancer you already run, in front of port 8080 |
| [G. The Windows front door](hosting/windows-front-door.md) | B–E's certificates, handled on Windows itself, so Docker Desktop cannot hide devices' addresses |
| [H. A Cloudflare tunnel](hosting/cloudflare-tunnel.md) | Cloudflare holds the certificate and answers the internet; a small connector on the server reaches out to it, so nothing is opened. Set up in Settings → Hosting |

---

## Changing it safely

**Settings → Hosting → Change** is three steps:

1. **How.** "How will people reach GoalGetter?": your network, your company's
   domain, a free DuckDNS name, a Cloudflare tunnel, a certificate from IT,
   or plain HTTP. The one in use is marked "now". **Other setups** holds your
   own proxy and the Windows front door.
2. **Set up.** Only the fields that way needs, and an **Outside GoalGetter**
   checklist: the DNS record, the token, the certificate files, ports 443 and
   80 (firewall commands to copy), the tunnel's steps, and the Microsoft
   redirect for Azure. **Check** ticks off what the server can: the name is in
   DNS and points at the address your browser is on, Cloudflare or DuckDNS
   accept the token, the certificate covers the name, the tunnel token is
   valid. Check changes nothing and never blocks: after a failed one, the
   button says **Switch over anyway**.
3. **Try it.** **Switch over** starts a trial. The new setup runs beside the
   old one, so nothing that works stops working: Caddy serves the old name and
   the new, and a running tunnel keeps running. Coming from plain HTTP,
   `http://<server>:8080` also stays the full app, your way back in; coming
   from HTTPS, the old HTTPS name is that, and 8080 stays TVs only. Live checks show HTTPS answering (and whose certificate), the
   tunnel connecting, and **Opens from this device**: your browser tries the
   new address itself, which catches this device's DNS, a firewall, or a
   device that doesn't trust GoalGetter's own certificate yet (with a
   **Download the root certificate** link).

Then:

- **Keep** makes it final. The old name stops; with HTTPS on, port 8080 serves
  TVs only.
- **Undo** puts the old setup back.
- **Not kept within 15 minutes?** It's undone by itself.
- **Undo last change: back to …** stays on the first step after keeping. It
  is one step back, tried like any change.

**You can't lock yourself out by trying.** Port 8080 works throughout a trial:
Undo, or wait 15 minutes.

## Settings → Hosting

- **How GoalGetter is reached**, with **Change**: the Address (and where it
  comes from), HTTPS (on, and whose certificate), the Tunnel (with a
  Cloudflare tunnel), the Certificate ("Valid until …", or "Renewed
  automatically" for GoalGetter's own, which are short-lived and renew
  themselves), Sign-in limits, and **You appear as**, with ↻ to check again.
- **For devices and TVs**, with HTTPS on: the root certificate (option B)
  with how to trust it, and the TV address.
- **Microsoft redirect**: the exact address to add in Azure, to copy.
- **Advanced**, folded away: the [Web address](#the-web-address) and "A proxy
  in front of GoalGetter?" ([option F](hosting/own-proxy.md)).

---

## The web address

GoalGetter puts its own address into invite and reset links, TV links,
webhook URLs, scheduled emails, Teams posts and sign-in redirects. It uses the
first of these that is set:

1. **Settings → Hosting → Advanced → Web address**, if an admin filled it in
   (`WEB_ADDRESS` in `.env`).
2. **The HTTPS address**, when HTTPS is on: `https://<HTTPS_HOST>`.
3. **`APP_URL`** in `.env`. It defaults to `http://localhost:8080`; move it
   with `APP_PORT`. It never beats HTTPS.

If a Web address is set when you change how GoalGetter is reached, the guided
change says so, with **Use the HTTPS address instead** to clear it.

With options B to E, leave the Web address empty and HTTPS fills it in. Set it
only when people reach GoalGetter by a different address than the server
knows (option F).

**After changing the address,** add the new sign-in redirect addresses in
Azure. Settings warns you about this, and the Integrations page lists them.
And sign in from the new address: a sign-in started at one address and
finished at another fails.

## Seeing each device

GoalGetter limits wrong passwords two ways: **per account** (five in five
minutes) and **per device** (twenty in five minutes). A channel can also be
limited to screens on your office network. The last two need each device's
own address, and whether GoalGetter gets it depends on how it is hosted:

| Host | Devices' addresses | What GoalGetter does |
|---|---|---|
| Docker on Linux | Kept | Limits per account and per device; network lists on channels work |
| Docker Desktop on Windows or Mac | **Hidden.** Every device arrives as one address of Docker's own, because Docker runs inside a hidden Linux machine and copies each connection into it | Limits per account only; leave channels' network lists empty |
| [The Windows front door](hosting/windows-front-door.md) (Docker Desktop) | Kept: the front door sees each device before Docker does | Limits per account and per device |
| A proxy of your own, outside Docker, in front ([option F](hosting/own-proxy.md)) | Kept, passed on by the proxy | Limits per account and per device |
| [A Cloudflare tunnel](hosting/cloudflare-tunnel.md), any host | Kept, passed on by Cloudflare — by public address, so one office counts as one device | Limits per account and per device |

**Nothing to set.** GoalGetter recognises Docker's own address by itself and
treats it as "unknown" rather than as one person. Otherwise, twenty wrong
passwords from anybody would lock out everybody.

**Settings → Hosting** is where to check and change it:

- **You appear as**: "192.168.1.55", or "Unknown · Hidden by Docker", with ↻
  to check again. Open it from a phone or another PC to see what GoalGetter
  sees for that device.
- **Advanced → A proxy in front of GoalGetter?**: "As set up on the server",
  "No", or "Yes" (our own proxy or load balancer, option F). "Yes" is only
  accepted when a proxy is actually passing an address along.
- **Sign-in & security → Wrong-password limits**: per account (3–20,
  default 5) and per device (10–200, default 20), in five minutes.

Most people sign in with Microsoft, which has its own protections, so the
per-account limit is enough for many offices. To get per-device limits on a
Windows server, use [the Windows front door](hosting/windows-front-door.md).

## TVs

A TV opens a pairing page and is connected from TVs & Channels. With HTTPS
on, the TV link uses the HTTPS address. If a TV complains about the
certificate (common with smart TVs and streaming sticks under option B), open
the plain address on it instead:

```
http://<server address>:8080/pair
```

Settings → Hosting shows this address for your install. TVs never
sign in, so plain HTTP on your own network is fine for them.

**With HTTPS on, the plain address is for TVs only.** It serves the pairing
page, the TV display and what they load. Anything else, such as a bookmark to
`http://<server>:8080/goals`, moves to the HTTPS address.

### YouTube on TVs

Walk-up songs, celebrations, YouTube screens and backgrounds play in
YouTube's own player, which uses **the YouTube sign-in of the browser it runs
in**.

- **Sign in once on each TV's browser.** Open `youtube.com` in it and sign in,
  ideally with an office account. Until then YouTube may show "Sign in to
  confirm you're not a bot", and the TV says so under the video. Chrome and
  Edge keep the sign-in; if a signed-in browser still asks, allow third-party
  cookies for `[*.]youtube.com` (Settings → Privacy → Third-party cookies →
  Allowed). Private windows never keep it.
- **Everything with sound plays it, one at a time.** Celebrations, YouTube
  screens, and YouTube or uploaded-video backgrounds all play with sound. A
  celebration has the floor over a YouTube screen, which has it over the
  background; the others go quiet meanwhile and come back after. A small
  speaker in the TV's corner shows sound is on, crossed out while it's off.
- **Allow sound once in each TV's browser.** Browsers don't let a site start
  sound by itself — a tab needs a click first unless its browser has been
  told the site may. Nothing on the TV asks for one. Instead, once per TV:
  - **Edge:** Settings → Cookies and site permissions → Media autoplay →
    Allow, and add GoalGetter's address under Allow.
  - **Firefox:** on the channel, the icon left of the address → Autoplay →
    Allow Audio and Video.
  - **Chrome** has no setting for it: the `AutoplayAllowlist` policy (one
    PowerShell line, then restart Chrome), or start Chrome with
    `--autoplay-policy=no-user-gesture-required`.

  From then on sound plays from the moment the channel opens. Until then,
  videos play muted rather than not at all. **Each TV reports it**, so TVs &
  Channels marks one "Sound off", with these steps and its own address, until
  it plays something with sound.
- **Some videos only play on YouTube itself** (age-restricted, or embedding
  turned off by their owner). No sign-in changes that; the TV says so.
  Uploaded MP3 and MP4 files always play, with no sign-in and no adverts.

---

## Troubleshooting

| What you see | Why, and the fix |
|---|---|
| Microsoft: **AADSTS50011** "redirect URI … does not match" | The address GoalGetter sent is not in the Azure app registration. Copy the exact one from Settings → Hosting into Azure → Authentication. |
| Microsoft refuses to save an `http://` redirect address | Microsoft only allows plain `http://` for localhost. Turn HTTPS on (B, C or D). |
| Browser says **"Your connection is not private"** / `NET::ERR_CERT_AUTHORITY_INVALID` | Option B, and this device does not trust GoalGetter's authority yet. See [B step 3](hosting/own-certificate.md#3-trust-the-certificate-on-each-device). |
| Other computers cannot open it at all | Firewall, or the wrong address. Check from a phone on the same network, and see [Before you start](#before-you-start). Do not use `vEthernet`/WSL addresses. |
| `docker compose up` says port **80 or 443 is already in use** | Something else on the server uses it, often IIS or another web server on Windows. Caddy always holds these ports, even with HTTPS off. Stop that, or set `HTTPS_PORT=8443` and `HTTP_PORT=8081` in `.env` and run `docker compose up -d`. The address then becomes `https://goals.internal:8443`. |
| Switched over and the new address doesn't open | During the trial, carry on at `http://<server>:8080` and **Undo**, or wait: a change not kept is undone after 15 minutes. **Opens from this device** says what to look at (DNS, firewall, the certificate). Last resort, after **Keep**: empty `HTTPS_HOST=` in `.env`; within half a minute HTTPS is off and `http://<server>:8080` works again. |
| Let's Encrypt certificate never arrives | `docker compose logs https` says why. Usually it is a token without permission to edit DNS, or the wrong `DNS_PROVIDER`. |
| The name works outside the office but not inside it (D) | The router blocks public names that lead to private addresses. Allow the name in the router, or use option B. |
| Sign-in goes back to the sign-in page | You signed in at one address and the Web address points at another. Use the same address for both. |
| **"Too many sign-in attempts. Try again in 5 minutes."** | Five wrong passwords for one email address, or twenty from one device, in five minutes. It lifts by itself. If everybody sees it at once, GoalGetter cannot tell devices apart: you have your own proxy in front and `TRUSTED_PROXY_HOPS` is still 1 (see [option F](hosting/own-proxy.md)). On Docker Desktop, GoalGetter detects this and limits per account only — see [Seeing each device](#seeing-each-device). |
| A channel's screens all say they "cannot see screens' addresses" | The channel has a network list, and this server cannot see addresses (Docker Desktop). Remove the list from the channel. |
| A certificate error when typing the **IP address** instead of the name | The certificate is for the name in Settings → Hosting (`HTTPS_HOST`), not the address. Use the name, e.g. `https://goals.internal`. |
| The root certificate link doesn't open after moving `HTTP_PORT` | It moves with the port: `http://goals.internal:8081/goalgetter-root.crt`. Settings → Hosting shows the right link. |
| `http://<server>:8080` jumps to the HTTPS address | Expected with HTTPS on: the plain port is for TVs only. TVs use `http://<server>:8080/pair`. |
| Cloudflare tunnel: **Tunnel** says "Not connected" | The reason is beside it on Settings → Hosting, e.g. a token Cloudflare doesn't accept (copy it again from the tunnel's page). More in `docker compose logs tunnel`. |
| Cloudflare tunnel: the name shows a Cloudflare error page (502 or 1033) | 1033: the tunnel isn't connected; see the row above. 502 with the tunnel connected: the public hostname's service is not `http://web:81`. |
| Cloudflare tunnel: everybody shows the same address under **You appear as** | The public hostname points at `web:80`; it must be `web:81`. |
| Links in emails say `localhost` | No Web address and no HTTPS. Set one of them. See [The web address](#the-web-address). |

## What to back up

Everything that matters lives under `volumes/` in the GoalGetter folder:

| Folder | What it holds |
|---|---|
| `volumes/postgres` | The database: everything people entered |
| `volumes/backups` | Nightly copies of the database, the last 14 kept. Copy these off the server: a backup on the same disk is not a backup. |
| `volumes/caddy` | Certificates, and for option B the certificate authority itself. Lose it and every device has to trust a new one. |
| `volumes/certs` | Option E's certificate files |
| `volumes/caddy-windows` | The Windows front door's certificates, and its authority for option B |
| `.env` | Settings and the encryption key. **Without this key, the stored sign-in and connector credentials cannot be read.** |

## Related docs

- [README → Getting started](../README.md#getting-started): the first install
- [16 Deployment](16-deployment.md): containers, configuration, upgrades
- [17 Security](17-security.md): the threat model
- [03 Auth & Users](03-auth-and-users.md): sign-in, SSO and invitations
