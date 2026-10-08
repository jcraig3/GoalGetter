# Spinify feature inventory — what GoalGetter can replicate

Research notes, September 2026. Source: Spinify's public knowledge base
(knowledge.spinify.com, ~250 articles read), product pages, and the screenshots
in those articles. No Spinify account was used, so anything that only exists
inside their editor (exact field lists, live previews) is inferred from the
docs.

**Focus:** the player experience: how people are set up, how their numbers
become competitions, and how that is turned into a show on the office TV.
Integrations, billing and AI are covered only briefly at the end.

**Status key.** Status is judged against GoalGetter's docs and code as of commit
`357dc3a` plus the uncommitted photo work:

| | |
|---|---|
| ✅ | GoalGetter has it |
| 🟡 | partial / different shape |
| ⬜ | not built, not planned |
| 📋 | planned in `18-roadmap.md` |
| 🚫 | GoalGetter decided against it (worth re-reading the reason, not re-litigating) |

**Priority** (for the customization phase): **P1** = do next, high visible
impact for little work · **P2** = next wave · **P3** = later / optional.

---

## 1. The mental model — how Spinify is put together

Spinify is five building blocks. Every customization option hangs off one
of them:

```
USERS ──▶ COMPETITIONS / METRICS ──▶ ACHIEVEMENTS ──▶ CHANNELS ──▶ TV
(avatar,   (type + style + goal +      (trigger +       (ordered      (tv code or
 sound,     target + participants +     recipients +     playlist of   no-login URL)
 video,     theme + TV options +        theme + sound    screens +
 birthday)  gamification)               + channels)      ticker)
                     │
                     └──▶ POINTS ──▶ TIERS / BADGES ──▶ REWARD STORE / PRIZE WHEEL
```

GoalGetter already has the same spine, under different names:

| Spinify | GoalGetter |
|---|---|
| user / player / fan | user · agent / manager / admin |
| competition (+ "personal metric") | goal · leaderboard · competition |
| achievement | announcement rule (`achievement_rule`) + celebration takeover |
| gong | shout-out (admin/manager only) |
| channel + TV code | channel + display token (`/display/:token`) |
| achievement sound / music video | walk-up media |

**The takeaway:** GoalGetter's gap isn't structure. It's the *presentation
layer*: styles, themes, animated interstitial screens, per-person flair, and
the points/tiers/badges economy that gives the TV something to celebrate
between sales.

---

## 2. Users & profiles

What a user *is* in Spinify, and everything that makes them feel like a
"player" on the screen.

| Feature | How Spinify does it | GG | Pri | Notes for GoalGetter |
|---|---|---|---|---|
| Add user (first, last, email) | Email is the join key for every integration | ✅ | | |
| Three license types: **Admin**, **Player**, **Fan** | Fan = view-only: sees comps, gets birthday shout-outs, can comment and ring the gong, never scores | 🟡 | P2 | GG has admin/manager/agent. A *spectator/fan* role (execs, support staff who watch but don't compete) is cheap and useful. See §3 "Spectators". |
| Roles within licenses | Super Admin, Manager, Marketing, Participant, Fan | ✅ | | GG's role model is already cleaner; custom roles are 📋 Phase 4. |
| Bulk import (CSV template) | Download a template → upload → users appear in minutes | 🚫 | | GG gets people from directory sync / SSO. Fine. |
| Bulk / individual invites; "always send invite" company setting | | ✅ | | |
| **Avatar**: upload photo, pick from **160+ pre-made avatars**, or auto-assign | Players can take a selfie in the mobile app | 🟡 | **P1** | Your uncommitted photo work covers upload, tenant photo and initials. **Add a built-in avatar library** (illustrated, license-clean, e.g. DiceBear-style SVGs generated locally, so it stays air-gap safe). It makes an empty wall look alive on day one. |
| **Animated GIF avatars** | Spinify has a "How to create a GIF" article for this | ⬜ | P3 | `images.py` re-encodes to JPEG, so a GIF would lose its animation. Decide deliberately. |
| **Fun leaderboard avatars**: a per-user pick *per fun design* (e.g. which car you drive in the race track) | Set in My User → "Fun Leaderboard Avatars"; admins can set for others | ⬜ | P2 | Needed once you ship a race or carnival style (§4). Store as `user_avatar_variant(user, style_key, variant)`. |
| **Achievement sound**: upload an MP3 (≤3 MB) or pick a default | Plays on the TV when an achievement uses "User's achievement sound" | 🟡 | **P1** | GG walk-up media is URL-only (YouTube/GIF). **Add uploaded audio clips**, stored like `stored_image` and served through the display-token route. This is the single most-loved Spinify feature in their testimonials ("hear their favorite song every time they hit a target"). |
| **Music video**: a YouTube URL with custom start time, or a pre-configured list | Same "user's sound" switch | ✅ | | GG already has YouTube with start/end offsets and a ~15 s clamp. Consider a small **curated default list** so people who don't pick still get something. |
| **Celebration GIF**: plays in Slack/Teams when that person earns an achievement | | ⬜ | P3 | Only matters once Slack/Teams posting exists (📋 Phase 4). |
| Nickname / preferred name | | ✅ | | GG has `preferredName`. |
| **Company-wide name display format**: First · First + L. · Full · Last | Company Settings | ⬜ | **P1** | One org setting, applied everywhere a name renders on the wall. Privacy win too (First + initial on public TVs). |
| **Birthday & work anniversary** | Birthday = "date of next birthday"; auto-celebrated at 9 am on the channel for the whole day | ⬜ | P2 | Store month/day only (no year) to avoid holding a DOB. It's a built-in rule type (§6). |
| Player self-service profile ("My User") | Name, nickname, avatar, fun avatars, birthday, anniversary, sound, GIF | 🟡 | **P1** | GG: the person can set their own photo (in progress). Extend the same page to walk-up media + fun avatars + birthday. Admin can override; add an org toggle "let agents choose their own celebration media". |
| Offices (group teams/users; filters most pickers) | | ✅ | | |
| Teams with team avatar | Team has name, members, **avatar** | 🟡 | P2 | GG teams have no image. A team logo/avatar for team battles is cheap once image storage exists. |
| User ↔ integration mapping page (+ export CSV) | "Red !" on disconnected users | ✅ | | GG's identity resolution + quarantine is stronger. |

---

## 3. Metrics & targets

How a number becomes something you can win.

| Feature | How Spinify does it | GG | Pri | Notes |
|---|---|---|---|---|
| Goal = record type + filters (+ AND/OR filter logic) + which owner field gets credit | Credit field lets one record type feed different comps (e.g. setter vs closer) | ✅ | | GG metric definitions + mapping. |
| Score type: count of records · **value of a field** · **average** (sum ÷ count) | "Average Score" comps rank on average deal size, etc. | ✅ | | GG aggregations: sum/count/avg/max/min/last. |
| **All-in-One** score: several metrics combined into one score | "Well-rounded performance" boards | 📋 | P2 | GG defers weighted/composite points metrics. This is the natural home for a **points formula**, e.g. `call=1, meeting=5, deal=20`. It's one of the most common asks in call-centre gamification. |
| Target modes: **none** (leader = 100%) · **same for everyone** · **individual per participant** | With no target, the progress bars are relative to the leader | ✅ | | GG has goals + "bars relative to leader". |
| **Dynamic targets** from a data source (SQL/Power BI column matched on email) | | ⬜ | P2 | You already have SQL/Sheets/Excel engines. A "target column" in the same mapping gives you quotas-from-the-warehouse, which is exactly your use case. |
| Target suggestions | "Set it to last month's score", "historical best", "first place from a no-target month" | 🟡 | P3 | GG preview suggests from the last 6 periods. Add "personal best" and "last period" buttons. |
| Target display: **currency / number / percent**; decimals toggle; currency symbol (company setting) | | ✅ | | GG units + org currency. |
| Hide target · hide scores · hide player stats panel | Per competition | ⬜ | **P1** | Three booleans on the competition/screen. Needed for sensitive numbers on a public wall. |
| **Pacing indicator**: a line showing where you *should* be today | | ✅ | | GG pace status + projection. **Draw it on the wall bars** if it isn't already (a vertical tick on each bar). |
| **Predictive scoring / forecast** | "See each member's progress and forecast the month" | ✅ | | GG projection. |
| **Personal metrics**: like a competition but no ranking; **private** (player + admin only) or **public** | Private ones never go to TVs | 🟡 | P2 | GG goals can be private. What's missing is a "public personal metric" *wall screen*: a grid of everyone's own progress-to-goal, with no ranking. |
| **Manual scores ("Local Scores")**: admin types scores or uploads a CSV; **players can update their own score** | Also used to "see how it looks on the TV" before data is connected | 🚫/🟡 | P2 | GG has admin corrections and deliberately no agent self-entry (trust principle). **The demo/preview use is worth copying:** a "sample data" toggle that fills a competition with fake scores so admins can design the wall before connectors are live. |
| Self-entry via Google Forms → Sheet | | 🚫 | | Same principle. |
| Period types: one-off, daily, weekly (Sun–Sat / Mon–Fri / Mon–Sat), every 2 weeks, monthly, quarterly; "start/end on nearest weekday" | | ✅ | | GG periods + recurring goals. Add *Mon–Fri* / *Mon–Sat* windows and "nearest weekday" for call centres. |
| Record drill-down: "which records made up my score" | | 🟡 | P3 | GG goal detail has contributors. |
| Export competition results (CSV) | | ✅ | | |

---

## 4. Competitions

The heart of the product. Spinify splits every competition into a **Type**
(the scoring mechanic) and a **Style** (the visual design). That split is the
single best idea to copy.

### 4.1 Competition types (mechanics)

| Type | What it does | GG | Pri | Notes |
|---|---|---|---|---|
| **Value** (standard) | Rank by count or sum of a field | ✅ | |
| **Average** | Rank by average per record | ✅ | |
| **All-in-One** | Several metrics → one combined score | 📋 | P2 |
| **Head-to-head** | Two people or two teams | ✅ (2-entrant view) | |
| **Team vs team** | Teams compete; members' scores roll up | ✅ | |
| **Big Epic Goal** (Goal Tracker) | One shared target for a whole team/org, no ranking | 🟡 | **P1** | GG goals are per user or per team; no *org-wide* goal (listed as not built). This is the "how high can we reach together" thermometer every sales floor wants. |
| **Elimination** ("musical chairs") | Periodically, whoever is in last place is knocked out; the last one standing wins | ⬜ | P2 | Very game-show. Needs a knock-out schedule (e.g. every hour or every day) and an "eliminated" state on the entrant. Great TV moment (§5.2). |
| **Duel** | A player challenges another player *inside a running competition*, for the final hour. Scores start at 0 at duel creation; auto-added to the same channel with an announcement; winner screen stays 6 h; ≥1 h long; ends no later than the parent | ⬜ | P2 | Needs event-level timestamps (you have metric facts), so it's feasible. It's agent-initiated, but the numbers still come from the data, so it doesn't conflict with "agents can't enter their own numbers". |
| **Quick Create** | 1-page wizard: style → dates → goal → target → participants → channel | ⬜ | **P1** | Keep your full editor, but add a quick path. See 4.4. |
| **Playbooks / templates** | Pre-built bundles (competitions + achievements + messages) by goal, industry or role | ⬜ | P2 | e.g. "Call centre starter pack", "Month-end push". JSON seed files; zero AI needed. |

### 4.2 Competition styles (the visual catalog)

Every style is available for every compatible type. Spinify ships **29
designs in 5 groups** (from their picker screenshots):

| Group | Purpose | Designs |
|---|---|---|
| **Goal Tracker** | one big number / gauge for a shared goal | Journey (photo + progress bubble) · Back to Basics (one giant number) · Progress Gauge (semicircle) · Goal Dash (gauge + totals) · Minimalist (number in a ring) · Target Locked (progress + goal panel) |
| **Head to Head** | two faces, "VS" in the middle | Face Off · Match (team crests, "House Lannister vs House Stark") · Cool · Jolly · Pink Galaxy · Bubble Battle |
| **Podium** | top 3 on steps / cards | Art Splash · Passionfruit · Confetti · Sunny · Pink Starlight · Bluebble |
| **Standard** | scrollable ranked list with bars | Money Makers · Clean (table) · Spotlight (table + highlighted player card) · Candid · Serious · Sunshine |
| **Fun** | animated game metaphors | **Race Track** (cars move along a track by % to target) · **Carnival Game** (duck-shooting gallery) |

**What to replicate.** GG currently has one leaderboard look and one
competition screen. **P1:** introduce a `style` field on leaderboard and
competition screens, and ship **one design per group**:

- Standard, which you have
- Podium
- Head-to-head, which you have as a 2-entrant view
- Goal gauge
- one Fun style, the race track

Build them as data-driven React components that read theme tokens. The
colourways are then presets, not new code: Spinify's "Pink Galaxy",
"Sunshine" and "Serious" are the *same layout* with different backgrounds
and palettes.

### 4.3 Per-competition theme & display options

| Option | Spinify | GG | Pri |
|---|---|---|---|
| Name + description shown on the TV header | ✅ | ✅ | |
| **Background**: 1000+ library images, **video backgrounds**, **YouTube background (muted)**, **upload your own** (16:9, 1920×1080, ≤5 MB) | | ⬜ | **P1** — upload + a small bundled library; a solid/gradient option. |
| **Randomise background** each time a recurring competition restarts | | ⬜ | P3 |
| **AI-generated background** from a prompt | | 🚫 | Needs an external model; skip for air-gapped. |
| **Highlight colour** for participants and progress bars | | ⬜ | **P1** — one colour picker per competition, falling back to the org accent. |
| **Font size** slider (for big rooms) | | ⬜ | **P1** — a scale factor on the screen. |
| **Max participants shown** / limit rows | | ⬜ | P1 — "top N" on the screen. |
| **Channel display time** slider (dwell per competition) | | ✅ | GG dwell per screen. |
| Show/hide target, scores, decimals, player-stats side panel | | ⬜ | P1 (see §3) |
| Winner rule for points: all who hit target / by position (1st, 2nd…) | | ⬜ | P2 (§7) |
| **Tie handling**: allow ties vs first-to-reach wins | | ✅ | GG `earliest_to_reach` / `shared_rank`. |
| **Spectators** (view-only participants) | | ⬜ | P2 |
| **Draft** → Upcoming → Active → Completed | Active can't go back to draft; "reactivate" = duplicate | ✅ | GG lifecycle is richer (settlement window, freeze). |
| **Duplicate / clone** competition | | ⬜ | **P1** — trivial and heavily used. |
| **Email participants when a competition starts** | | ⬜ | P3 (SMTP exists) |
| **Competition grade** (A–F) after it ends: score lift vs last run, % who hit target, spread of the top 5 | Nudges admins to set better targets | ⬜ | P3 — nice analytics hook, pure computation. |
| Live preview while editing | The editor shows a live TV preview on the right | ⬜ | **P1** — render the real wall component in the editor at 16:9 scale. This makes customization feel instant. |

### 4.4 The creation wizard (UX to copy)

Spinify's editor is a stepper, and the *order* matters:

1. **Design**: pick Type, then Style from thumbnails
2. **Overview**: name and description
3. **Duration**: one-off or recurring, start and end
4. **Goal**: source, record type, filters, credit field, target mode, target unit, target label
5. **Players**: users *or* teams (never mixed), player vs spectator, per-row target when targets are individual
6. **TV**: channels, dwell time, font size
7. **Layout / Announcements**: profile screen, overtake screen, winner screen, milestone celebrations, start email
8. **Gamification**: show/hide toggles, points reward
9. **Theme**: background, highlight colour

"Save draft" is available once steps 1–5 are valid.

**Borrow:** *design first*. Picking the look before the numbers makes it feel
like building a game, not a report.

---

## 5. The TV / display experience

### 5.1 Channels (playlists)

| Feature | Spinify | GG | Pri |
|---|---|---|---|
| Multiple channels, each an ordered rotation of screens; a default "Show All / Launch All" channel | | ✅ | GG has no "all" channel; P3. |
| Add the same item to a channel **multiple times** to weight it | | 🟡 | P3 — allow duplicates in screen order. |
| **Screen types**: competition, comparison screen, image, YouTube, **web page (iframe)**, countdown, message, dashboard, prize wheel, integration dashboards | | 🟡 | GG has leaderboard, goal, competition, achievements, image, video, message. **Add Countdown (P1) and Web page (P2).** |
| **Comparison screen** (their "multimetric"): 2+ competitions side by side on one slide; header = each target's name; background from the primary | | ⬜ | **P1** — e.g. "Calls · Meetings · Deals" in three columns. A big wall-space win. |
| **RSS / news ticker** along the bottom | | ⬜ | P2 — must work offline, so allow internal RSS URLs only or a *manual ticker text* list (better fit for air-gapped). |
| **Per-channel display language** | | ⬜ | P3 (i18n later) |
| **Pause the loop** (space bar); full-screen (F11) | | ⬜ | P1 — space = pause, ←/→ = prev/next, for the person standing at the TV. |
| **Duplicate channel** | | ⬜ | P1 |
| Channel name suggestions | AI | 🚫 | |
| **Offline page** ("no internet") | | ✅ | GG shows "Reconnecting…". |
| IP allowlist per channel | | ✅ | |

### 5.2 Interstitial "moment" screens (the gamification layer)

These are what make the wall *entertaining* rather than a slideshow of
tables. Spinify turns each one on or off per competition, with/without sound
and with its own duration.

| Screen | When it shows | GG | Pri |
|---|---|---|---|
| **Overtake screen**: "WELL DONE — Hannah — 2nd PLACE ▲" banner | Before the competition, if anyone recently moved up | ⬜ | **P1** — GG already computes movement arrows; turn "rank improved since the last show" into a 3–5 s animated banner. Highest wow-per-line-of-code. |
| **Winner screen**: photo, big name, score, % of target, place, trophy graphic (trophy type selectable), motivational text | For a set time (default 1 day) after a competition ends; the duel winner stays 6 h | 🟡 | **P1** — GG freezes results; add a celebratory "final results / champion" screen that auto-enters the channel after close. |
| **Player profile — "Tale of the Tape"**: a random participant's card with total points, like fighters before a bout | Just before the competition | ⬜ | P2 — needs points (§7), or show "this month: X, best ever: Y, streak: Z" without points. |
| **Milestone celebrations**: auto takeovers at % of target (e.g. 25/50/75/100), **moved into 1st place**, **hit target**. Setting: All / Important only (1st place + target) / None | Per competition | 🟡 | **P1** — GG announcement rules are metric + threshold. Add *competition-scoped* built-in milestones with that one All/Important/None dropdown, so admins don't hand-build rules. |
| **Duel start announcement** | | ⬜ | P2 (with duels) |
| **Countdown screen** to an event or deadline | | ⬜ | **P1** — "2h 14m left in the month-end push". |
| **Prize wheel spin** broadcast live to TVs | | ⬜ | P2 (§7) |

### 5.3 Getting the picture onto the TV

| Feature | Spinify | GG | Pri |
|---|---|---|---|
| **No-login TV URL** per channel | | ✅ | display token |
| **TV code pairing**: open `tv.<host>` on the TV → it shows a short code → the admin types the code in "Verify TV code" → the TV launches the channel | | ⬜ | **P1** — ideal for self-hosted: the TV never needs a long token typed with a remote. Store `pairing_code (6 chars, 10 min TTL) → display_token`. The TV page polls until paired. |
| Android TV / Google TV app | Spinify TV on Google Play | ⬜ | P3 — a PWA with a manifest (full-screen, landscape, keep-awake) covers most of it. |
| Chromecast from a browser (multiple casts using multiple Chrome profiles) | Documented workaround | 🟡 | Document it; works today with the token URL. |
| Hardware guidance (stick PC, Chromebox, HDMI, Airtame) | | 🟡 | Add a deployment doc page. GG already notes the autoplay flag. |
| **Remote control from desktop**: change what a TV shows without touching it | "Control the TV anywhere" | 🟡 | P2 — GG displays poll, so let admins reassign a display to another channel from the Displays page and push a "reload now". |
| Update latency: new content can take ~10 min to join the rotation without a refresh | | ✅ | GG polling is better. Keep it. |

### 5.4 Org-level wall branding (Company Settings / Branding)

| Setting | GG | Pri |
|---|---|---|
| **Company logo** in the TV header and app, with crop and zoom | ⬜ | **P1** (planned "logo + accent") |
| **Slogan** | ⬜ | P2 |
| **Brand colours** (applied across the app) | 📋 | **P1** — accent + auto-contrast, as planned; add a secondary colour. |
| **TV font**: pick from a list | ⬜ | **P1** — bundle 5–6 open fonts locally (no Google Fonts CDN, for air-gap). |
| **TV panel opacity** slider (the glass cards over backgrounds) | ⬜ | **P1** — one CSS variable. |
| **"Competition ends in…" format** (e.g. "Ends in 3 days" vs a date) | ⬜ | P2 |
| **Currency symbol** | ✅ | |
| **Name display format** | ⬜ | P1 (§2) |
| Light / dark theme | 🟡 | tokens exist; toggle deferred |

---

## 6. Achievements & recognition (what triggers a celebration)

| Feature | Spinify | GG | Pri |
|---|---|---|---|
| **Achievement** = trigger (record type + filters, or leaderboard event) + recipients + theme (title and message with **merge tags**) + sound + channels + notifications | Interrupts the current slide on the TV | ✅ | GG announcement rules + takeover. |
| **Merge tags / variables** in title and message: owner name, record amount; for leaderboard achievements: amount changed, position, last position, % to target, score, units, "x of y participants" | | 🟡 | **P1** — e.g. `{first_name} just closed {amount}! Now {position} of {total}`. A small mustache-style renderer; big personalization win. |
| **Leaderboard-event triggers**: reaches % of target · reaches score · score increases | | 🟡 | P1 (see 5.2 milestones) |
| **Never retroactive** (a score already past the threshold won't fire) | | ✅ | Same rule in GG. |
| **Sound per achievement**: default sounds, upload, or "user's achievement sound" | | 🟡 | **P1** — ship a small bundled sound pack (gong, air horn, cash register, applause, crowd) + uploads. |
| **Theme per achievement**: background (image, video, AI), graphic (e.g. treasure chest), motivational text on/off | | 🟡 | P2 |
| **Display timing**: how long it stays in the rotation after firing; first-show duration vs repeat duration; "stop showing if the record no longer matches" | | 🟡 | GG lifetime 300 s / hold 10 s. Expose these per rule (P2). |
| **Replay an achievement** (re-fire with the person's *current* song, to new channels) | Also used to test TVs | ⬜ | **P1** — a "Replay on wall" button on the achievements feed. Great for testing, and for the manager who missed it. |
| **Enable/disable toggle**; **clone** | | ✅ / ⬜ | clone P1 |
| **Birthday & anniversary** built-in triggers (auto at 9 am, all day) | | ⬜ | P2 |
| **Gong**: anyone permitted rings it with who/what/message → instant takeover; the recipients list controls who may ring; 5-min cooldown from the app | | 🚫 | GG chose manager-only shout-outs. Consider an **org toggle** "agents can send peer shout-outs" (📋 peer kudos, Phase 4) with the same cooldown. |
| Pre-configured achievements per data source (Big Deal, Case Resolved, Call Made, Lead Qualified, Meeting Completed…) | | ⬜ | P2 — seed a few default rules when a connector is added. |
| Badge and tier achievements, created by default | | ⬜ | with §7 |
| Comments / reactions on achievements (activity feed, Chrome extension, mobile) | | ⬜ | P3 |
| AI-varied messages ("Dynamic Accolades"), AI "Recognition Agent" | | 🚫 | Needs an LLM. A non-AI substitute is **message variants**: 3–5 templates per rule, picked at random, so the wall doesn't repeat itself. P2. |

---

## 7. Gamification economy (points → tiers → badges → rewards)

Entirely new territory for GoalGetter (📋 "points, badges, levels, tiers",
Phase 4). This is what turns "a leaderboard" into "a game you're playing all
year".

| Feature | How Spinify does it | Pri | Design notes |
|---|---|---|---|
| **Points**: a cumulative lifetime total per user | Earned by **winning competitions** and **earning achievements**. Achievement points can be fixed or **from a record field × multiplier**. Competition reward = fixed or a multiplier of current points, to all who hit target or **by finishing position** | **P2** | A ledger table `points_entry(user, amount, reason, source_type, source_id, created_by)`; balance = sum. Never store a mutable total without the ledger. It keeps the audit story consistent with GG's trust principle. |
| **Manual point adjustment** with a reason | | P2 | a ledger row with `created_by` |
| **Reset all points** (new quarter) | Resets points and earned badges/tiers; keeps definitions | P2 | A "season" concept is cleaner: points per season + lifetime. |
| **Tiers** (levels/ranks) by minimum points: name, description, default set, first tier at 0 can't be deleted | Shown on the TV and in the app | P2 | Seed ~6 tiers (Rookie → Legend). Tier-up = a celebration takeover. |
| **Badges**: name, description, image; awarded **manually** or automatically when an achievement fires **N times within a period** (e.g. 10 deals in a day) | Shown on profiles; "badge earned" achievement | P2 | Ship a bundled SVG badge set so admins don't need artwork. |
| **Reward store**: admin-defined items with point prices and images; the player "buys" → points deducted → admin approves/rejects (refund on reject) → email to the admin; **multiple stores** per team/office, each with a manager | Pro plan | P3 | Store balance ≠ lifetime points (spent vs earned). Requests queue for managers. |
| **Prize wheel**: pick players, list prizes (repeat a prize to weight it), spin → broadcast live to channels → auto "winner" achievement | | P2 | Pure front-end fun, needs no economy. Great Friday-afternoon feature. |
| Hide points/tiers on a competition | "Show player stats" toggle | P2 | |
| Points export (CSV) | | P3 | |

---

## 8. Player & manager surfaces (off the TV)

| Feature | Spinify | GG | Pri |
|---|---|---|---|
| Player home / "Score Card": current competitions + position, tier, points, badges, performance-grid score | | 🟡 | GG agent dashboard. Add tier/points/badges when §7 lands. |
| **Past performance** per recurring competition: current vs first, vs previous, average, **hit-target count**, score vs target graph | | 🟡 | P2 — "you've hit target 7 of the last 10 weeks" is motivating. **Streaks** fall out of the same data. |
| Leaderboard graphs (actual vs target over time, predicted) | | 🟡 | GG sparklines. |
| **Performance grid**: 2×2 quadrants of activity vs outcome (from recurring, targeted comps) | Coaching tool | ⬜ | P3 |
| Tasks, notes, AI coaching agent | | ⬜ | out of scope for customization |
| Chrome extension / desktop notifications of achievements | | ⬜ | P3 — browser notifications from the web app cover it. |
| Mobile app (iOS/Android/Watch): personal stats, competitions, celebrate-from-phone → TV | | 🚫 | Responsive web / PWA. A "Ring it from my phone" page is the part worth having. |
| Microsoft Teams tab + Slack/Teams achievement posts | | 📋 | Phase 4 webhooks. |
| MCP / ChatGPT / Claude connectors | | ⬜ | Out of scope. |

---

## 9. Data & integrations (brief — you're ahead here)

- **Spinify's model:** push events (`/v1/events` with Leads, Deals, Accounts,
  Cases, Calls, Meetings, Emails, Trailing Revenue), a webhooks URL, CSV/FTP,
  Sheets/Excel pivot tables keyed by email, SQL (Postgres, MySQL, MSSQL,
  Snowflake, Redshift), Tableau, Power BI, and ~30 CRMs/diallers.
- **GoalGetter already covers** the same engines: sheets, SQL, webhook, JSON
  API and CRMs, with better data hygiene (quarantine, dedupe, settlement).
- **Ideas worth taking:**
  - **Dynamic targets** from a column (P2).
  - A **spreadsheet template** users can copy (the "email · amount · date ·
    type" + pivot-table pattern).
  - **Sample data mode** for designing walls before data flows (P2).

---

## 10. Things to deliberately *not* copy

- **AI everywhere.** Sidekick names, AI backgrounds, the recognition agent and
  the coaching agent all need an external LLM, which breaks the air-gap
  principle. Use templates, random variants and bundled media instead.
- **Agent self-entered scores** (Local Scores for players, Google Forms). They
  contradict "trust is the product". The *admin* manual-score / sample-data
  use is fine.
- **Seats, plans, reward-store-as-upsell.** No billing, per the README.
- **Hosted-only assumptions:** CDN fonts, the external RSS news service,
  YouTube dependence for all media. Every customization asset should be
  **uploadable and stored locally**, with URLs as an optional extra.

---

## 11. Suggested build order for the customization phase

Grouped so each step ships something visible on the wall.

1. **Org branding & wall look:** logo (crop), accent + secondary colour,
   TV font (bundled), panel opacity, name-display format. *Settings page + CSS
   variables on the display.*
2. **Player identity:** finish photos; built-in avatar library; uploaded
   walk-up **audio**; a self-service "My profile" page (photo, avatar, walk-up
   media, birthday); an org toggle "agents may set their own media".
3. **Screen styles:** a `style` field; ship Podium, Goal gauge (+ org-wide
   "Big Epic Goal"), Head-to-head polish, and the Race Track. Add
   per-competition background (upload, colour or gradient), highlight colour,
   font scale, top-N, hide target/scores. **Live 16:9 preview** in the editor.
4. **Moments:** Overtake banner, Winner/champion screen, competition milestone
   celebrations (All / Important / None), Countdown screen, Comparison screen,
   **Replay on wall**, merge tags in celebration text, a bundled sound pack.
5. **Display ops:** TV pairing code, keyboard pause/next, duplicate
   channel/competition, remote reassign + reload.
6. **Economy (Phase 4 proper):** points ledger → tiers → badges (bundled art)
   → prize wheel → (later) reward store.

### Data-model sketch for steps 1–4

- `organization`
  - `+ logo_image`, `+ accent_color`, `+ secondary_color`, `+ wall_font`
  - `+ wall_panel_opacity`, `+ name_display` (`first` / `first_initial` / `full` / `last`)
  - `+ allow_self_media`
- `user_account`
  - `+ avatar_kind` (`photo` / `library` / `initials`), `+ avatar_library_key`
  - `+ walkup_audio` (stored asset), `+ birthday_md`, `+ anniversary_md`
- `stored_asset`: generalize `stored_image` to cover `audio/mpeg` and
  full-size backgrounds.
  - Today images are forced to 400×400 JPEG. Backgrounds need 1920×1080, and
    animated GIFs must keep their animation.
- `screen` / `competition` display options
  - `+ style_key`, `+ background` (`kind` + asset / colour / gradient)
  - `+ highlight_color`, `+ font_scale`, `+ max_rows`
  - `+ show_target`, `+ show_scores`, `+ show_decimals`, `+ show_player_stats`
  - `+ overtake_screen` (`off` / `silent` / `sound`), `+ winner_screen_hours`
  - `+ milestones` (`all` / `important` / `none`), `+ profile_screen`
- `display_pairing(code, display_id, expires_at)`

---

## Open items that a Spinify trial account would settle

The public docs were enough for this list. A trial login would confirm:

- the exact **Gamification** page options
- the full **achievement type** list (it's in an iorad tutorial behind a login)
- the **message type** list (the same)
- how the live preview behaves

Worth doing before building step 3.
