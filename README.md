# GoalGetter

Self-hosted sales performance and gamification. Set goals, rank agents and
teams, run competitions, celebrate wins, and put live leaderboards on the
office TVs. It all runs on your own server, and nothing leaves your network.

```
DATA IN  ──▶  MEASURE  ──▶  MOTIVATE
CSV/Excel     metrics       leaderboards & competitions
connectors    goals         recognition, badges & points
Microsoft 365 periods       TV walls & celebrations
```

## What it does

- **Goals**: targets for people and teams, by day, week, month, quarter or year,
  with pace ("on track", "behind") worked out as the period runs.
- **Leaderboards**: any metric, ranked, with movement, for people, teams or
  offices.
- **Competitions**: contests over any window, head-to-head or team against
  team, settled and frozen when they end.
- **Recognition**: shout-outs, badges, points, seasons and a prize wheel.
- **TV walls**: channels of leaderboards, goals and contests for the office
  screens, with full-screen celebrations, walk-up songs and game boards
  (race track, regatta, summit, space race).
- **Profiles**: public badges and wins, with private numbers that only the
  person and their managers see.
- **Data in**: typed in, CSV/Excel import, webhooks, Excel and Google Sheets
  online, SQL databases and warehouses (Snowflake included).
- **Microsoft 365**: single sign-on, directory sync, Teams posts, and sending
  mail through your own mailbox.
- **Running it**: roles (admin, manager, agent) plus custom roles, two-step
  sign-in, an audit log, an admin inbox, scheduled coaching emails, and your
  own branding.

---

## Getting started

About 15 minutes, most of it Docker downloading things the first time.

### Before you start

- [ ] **A computer or server that stays on**: Windows, Mac or Linux. A spare
      office PC is enough.
- [ ] **Docker**: [Docker Desktop](https://www.docker.com/products/docker-desktop/)
      on Windows or Mac (started, and saying it is running);
      [Docker Engine](https://docs.docker.com/engine/install/) with the Compose
      plugin on Linux.
- [ ] **Git**: [git-scm.com](https://git-scm.com/downloads), or
      `sudo apt install git`.
- [ ] **Free ports**: 8080, and 443 and 80 for HTTPS. Taken (IIS, say)? Set
      `HTTPS_PORT=8443` and `HTTP_PORT=8081` in `.env` after step 2.

No Python, Node or database to install: everything runs inside Docker.

### Steps

1. **Get the code.** In a terminal (on Windows, **PowerShell**):
   ```bash
   git clone https://github.com/jcraig3/GoalGetter.git
   cd GoalGetter
   ```
2. **Create your settings.** This writes `.env` with fresh random passwords
   and keys, and never replaces one that exists. Every setting is explained
   inside it.
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1    # Windows
   ```
   ```bash
   sh setup.sh                                           # Mac / Linux
   ```
   > **Keep `.env` safe and backed up.** It holds the key that encrypts stored
   > sign-in and connector credentials. Without it they cannot be read.
3. **Start it.**
   ```bash
   docker compose up -d
   ```
   The first start builds the app and takes a few minutes. `docker compose ps`
   should show six services running, with `api`, `web` and `postgres`
   **healthy**. `https` and `tunnel` run too, idle until Settings → Hosting
   turns them on.
4. **Create your admin account.** Open **http://localhost:8080**: your
   organization's name, then your name, email and a password of 12 characters
   or more.
5. **Make it reachable.** **Settings → Hosting → Change** asks how people will
   reach GoalGetter, lists what to set up outside it, and checks what it can.
   **Switch over** tries the new setup beside the old one: **Keep** it, or
   **Undo**. A change not kept within 15 minutes is undone by itself.

Then, from the sidebar: **Settings** (timezone, week start, fiscal year and
currency first: every daily and weekly board follows them) → **Metrics** →
**Integrations** (or type numbers in under **Corrections**) → **Users** (or
sync them from Microsoft 365) → **Goals**, **Leaderboards**, **Competitions**
→ **TVs & Channels**.

## Hosting options

Every option is free and has its own guide. The overview, with network basics,
TVs and troubleshooting: [documentation/20-hosting.md](documentation/20-hosting.md).

| Option | People type | Guide |
|---|---|---|
| **Your network**, GoalGetter's own certificate | `https://goals.internal` | [own-certificate.md](documentation/hosting/own-certificate.md) |
| **Your company's domain**, Let's Encrypt | `https://goalgetter.company.com` | [company-domain.md](documentation/hosting/company-domain.md) |
| **A free DuckDNS name** | `https://acme-goals.duckdns.org` | [duckdns.md](documentation/hosting/duckdns.md) |
| **A Cloudflare tunnel**, no port opened | `https://goalgetter.company.com` | [cloudflare-tunnel.md](documentation/hosting/cloudflare-tunnel.md) |
| **A certificate from IT** | the name it's for | [certificate-files.md](documentation/hosting/certificate-files.md) |
| **Your own proxy** | whatever it serves | [own-proxy.md](documentation/hosting/own-proxy.md) |
| **The Windows front door**, per-device sign-in limits | any of the first five | [windows-front-door.md](documentation/hosting/windows-front-door.md) |

---

## Everyday commands

Run these from the GoalGetter folder.

| To… | Run |
|---|---|
| Start, or apply a change to `.env` (HTTPS lines apply by themselves) | `docker compose up -d` |
| Stop | `docker compose down` (your data stays in `volumes/`) |
| Read the logs | `docker compose logs -f api` (or `web`, `https`, `tunnel`, `postgres`) |
| Update to the latest version | `git pull` then `docker compose up -d --build` |
| Back up now | `docker compose exec db-backup /usr/local/bin/db-backup.sh` |

Migrations apply by themselves on start. Nightly backups land in
`volumes/backups` (the last 14 kept): copy them off the server.

## Documentation

- [Hosting](documentation/20-hosting.md): HTTPS, Microsoft sign-in, TVs, troubleshooting
- [Deployment](documentation/16-deployment.md): containers, configuration, upgrades, backups
- [Dev workflow](documentation/19-dev-workflow.md): developing, tests, repository layout
- [Architecture](documentation/01-architecture.md): stack and design
- [Roadmap](documentation/18-roadmap.md): what was built, in what order, and why
- [Everything else](documentation/README.md)

## Principles

1. **Works with zero external dependencies.** Type the numbers in by hand if
   you have to. Connectors speed things up but are never required.
2. **The person deploying it is not a developer.** Sane defaults everywhere.
3. **Trust is the product.** A leaderboard that is wrong, or that shows somebody
   data they should not see, ends the tool.

**Out of scope, permanently:** pricing, billing and subscriptions (this is
internal software), and telemetry or phoning home. It must be deployable with
no internet connection at all.
