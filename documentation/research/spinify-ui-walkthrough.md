# Spinify UI walkthrough — and how GoalGetter matches and beats it

Hands-on notes from clicking through a live Spinify admin account
(my.spinify.com), September 2026.

**How this was done.** The session was **look-only**:

- Nothing was saved, created, deleted, enabled or sent. Editors were opened
  and cancelled.
- Integrations were not opened. Integration behaviour comes from the public
  knowledge base; see [spinify-feature-inventory.md](spinify-feature-inventory.md).
- No real employee names appear below.

This doc complements the feature inventory:

| Doc | Covers |
|---|---|
| **Inventory** | *what* Spinify can do |
| **This doc** | *how it feels to use*, and a concrete customization spec: the Spinify baseline plus where GoalGetter goes further |

---

## Part 1 — What the UI actually looks like

### 1.1 Shell & navigation

- **Left rail with collapsible groups.** The admin view's full tree:

  | Group | Pages |
  |---|---|
  | Overview | |
  | Goals | Competitions · Metrics · Compare · Integration Dashboards |
  | Recognition | Announcements · Messages · Prize Wheels · Gong |
  | Playbooks | |
  | Channels | |
  | Reporting | Competition Results · Experiments |
  | Coaching | Score Cards · Coaching Sessions · Performance Grids |
  | Rewards | Badges · Tiers · Points · Store |
  | Team | Users · Teams · Offices |
  | Settings | Integrations · Mobile App · Company Settings · Branding |

- **The whole admin app wears the customer's brand.** The logo sits top-left,
  and the primary/secondary brand colours drive the buttons, rail highlight
  and table headers.
- **Top bar:** a help "?" menu (Academy, KB, support), the user menu (My User,
  settings, logout) and a persistent **"Ask me anything…"** AI chat pill in the
  bottom-right.
- **Loading states:** a spinner plus a rotating motivational quote ("Dream big,
  work hard, stay focused"). It's cute, but pages often take 2–4 s to show
  content.
- **List pages share one pattern:**
  - a filter card on the left (search, sort, status, period type, type, score type)
  - result cards or tables on the right
  - a primary CTA in the brand accent, top-right

### 1.2 Overview (admin home)

"Team Overview" is a manager dashboard, not a scoreboard:

- **% of participants on pace** (large number) + change vs last period
- health chips:
  - competitions healthy
  - need a nudge
  - no target set
  - reps below pace
- **"What's new?"** carousel of recent celebrations ("X just reached the
  target in Y")
- **Coaching gaps**: everyone below pace, *with exactly what's missing*
  ("17 Closed Deals"), plus a Coach button per row
- **All competitions** table with filter pills:
  - vs target / vs previous run / no baseline
  - per-row on-pace bar, vs-last, hit rate

**Takeaway:** the manager landing page answers "who needs help right now?".
GoalGetter's "needs attention" list is the same idea. Spinify just makes it
the hero.

### 1.3 Competitions list

Each competition is a **card**:

- header: icon (from the design), name, a chip with the data source
  (e.g. "GoogleSheet", "SequelSummary" for SQL), description line
- meta row:
  - score type
  - participant count (person icon for individual, group icon for team)
  - **competition type** (Value / Count / Chase the Leader …)
  - **design name** (Sunny, Along the Wire, Goal stats, Progress gauge …)
- a period progress bar (start date — period — end date)
- actions: 👁 report · ✎ edit · ⌄ expand · ⋮ more

**Create Competition** is a split button: **Quick Create** or **Advanced
Create**.

### 1.4 Create competition — step 1: pick a *type* (25)

A card grid. Each card has an icon, a name and one line of "what it's for":

- **Scoring:** Value · Count · Average · All in One (NEW)
- **Ranking modes:**
  - Chase the Leader
  - Golf Score (lowest wins)
  - Golf Score Zeros are Last
  - Largest Single Score
  - Smallest Single Score
- **Structure:** Head-to-Head · East vs. West (regions) · Elimination
- **Themed presets:** each is a preconfigured combination of the above
  - Most No's · Morning Rush (first hour of each day) · EOD Blitz
  - Shoot the Moon (VIP deals) · EPIC Revenue Goal
  - Quota Crusher (biggest improvement on target) · FOMO · Boss Level
  - Obstacle Crushing (stale deals) · Shark Week · Word of Mouth · Talk Time

**Observation:** half the "types" are really *templates*, a mechanic plus a
suggested filter and name. That's a smart way to inspire admins without
inventing new engines.

### 1.5 Step 2: pick a *design* (~230)

- **One very long page** (~41,000 px tall), grouped:

  | Group | Designs |
  |---|---|
  | Standard | 81 |
  | Goal Stats | 55 |
  | Goal Tracker | 15 |
  | Head To Head | 30 |
  | Podium | 19 |
  | Fun | ~28 |

  A "Coming Soon…" group follows.
- Each design is a thumbnail + name + one line. Hover shows a **Create**
  button.
- **Fun designs are real game boards.** Avatars move by % to target:
  Carnival (duck shooting), Maze, Birds Nest, Rabbit Hole, Hit the Track
  (race cars), On the Court (basketball), Spini-Cross (motocross), Creepy
  Crawlers, Duckie Races, Emoji-Sprint, Greener Pastures, Reef Racers,
  Football Fever, Hole in 1, Horse Racing, Hot-air balloons, Poker Face,
  Lift Off, Pizza Party, Soccer…
- **Standard and Goal Stats designs are mostly the same layout** re-skinned
  with different photo backgrounds and palettes (Sunset Field, Paris,
  Underwater, Retro, Toon, Borealis…).
- **Pain point:** there's no search, no filter by colour or layout, no
  favourites and no "recently used". You scroll a wall of 230 thumbnails.

### 1.6 The editor (7-step wizard)

- **Layout:**
  - a step list on the left: Overview → Competition → Players → TV →
    Announcements → Gamification → Theme
  - the form in the centre
  - a sticky action column on the right: **+ Add Competition · Save Draft ·
    Cancel · Back · Next**
- **Validation:** a yellow toast ("Some fields are missing or invalid") plus
  red inline text. Next is blocked until the step is valid.
- **No live TV preview** anywhere in the wizard. The Theme step shows only
  a static thumbnail.

| Step | Fields (exactly as seen) |
|---|---|
| **Overview** | Sidekick AI name suggestions (Playful / Balanced / Serious; "MY FAVORITE" chip) · Name · Description · Duration: One Off / Daily / Weekly / Two Weekly / Monthly / Quarterly · start/end date + hour + minute · "Start and end on a weekday" · shows "Recurring in N days" + timezone |
| **Competition** | Target: **No Target / Same For Everyone / Individual** · Set Target · **Target Name** (the TV column label) · Target Type: Currency / Number / Percent / **Time (s → MM:SS / HH:MM / HH:MM:SS)** · Order: Highest→Lowest / Lowest→Highest / Lowest→Highest with 0s last · **Allow ties** · Metric source: *Spinify* (Gamification Points, Local Scores) or *Connected Apps* (preconfigured filters like Calls Made, Deals Won; custom filters; Excel / Google Sheet / SQL data) |
| **Players** | Office filter · **Individual / Teams** toggle · multi-select with search, checkboxes, "Done" / "Clear selection" · **+ Add all** · per-row **Visible** checkbox + **Permissions: Player / Spectator** · "Allow all users with a Player license to see this competition" · "Players will only see their own participant" |
| **TV** | **Channel Display Speed** slider (stored as *seconds per participant*, so a longer list gets more time) · **Font Size** slider (Standard → Largest) · channel picker + "Add to all channels" |
| **Announcements** | **Milestone Celebrations: None / Important Only / All** · "Send email to participants when competition starts" · **Overtake Animation: With sound / Without sound / Disabled** · **Winner Screen**: hours to stay in channel after end (default 3) · seconds per show (default 45) · **Trophy Type** (16: balloons, chest, confetti, medal, money, gong, star, trophy, pot, bow tie, champagne, crown, cupcake, laurel, lollipop, party hat) · Show Motivational Text |
| **Gamification** | Order participants by Name / Position / Score · **Participants per screen** (you click 1–8 person icons) · Show all participants · Show "% of target" label · Show target to players on desktop · Show scores · Show decimals · Show participants with 0 · **Points**: All Players (who reach target) *or* By Positions; Fixed *or* Based on Score; default 10 |
| **Theme** | Background (see below) · **Theme Colors: Primary / Secondary / Tertiary** (swatch + edit + clear) · Theme (design) re-picker modal with a group filter. **Fun designs hide the background and colour options.** |

**Background picker** (a modal with 5 tabs):

| Tab | What it offers |
|---|---|
| Sidekick AI | text prompt → generated image, with a personality |
| Image | **~65 categories**, each with 8–59 images |
| Video | 19 categories: Awards, Cars, Cities, Clean, Equalizers, Fire, Frosted Glass, Geometry, Ink, Nature, Paper, People, Sci-Fi, Space, Technology, Water, Waterfalls, Waves, Winter |
| YouTube | a video ID |
| Upload | 1920×1080, < 5 MB |

The Image categories span:

- **holidays:** Christmas, Halloween, Easter, Cinco de Mayo, St Patrick's,
  Valentine's, Thanksgiving, New Years, Mother's and Father's Day, Earth Hour
- **sports:** American Sports, Soccer, March Madness, Car and Horse Racing,
  Extreme Sports, Tournament, Tug of War
- **industries:** Real Estate, Recruitment, Call center, Construction
- **moods:** Success, Money, Luxury, Gold, Celebrations, Teamwork, Innovation
- **places and nature:** Beach, Space, Winter, Fireworks, Flowers, Dogs,
  Baby Animals
- **"Corporate Colors" and "Textures"** for brand-neutral boards

### 1.7 Competition report (the 👁 view)

A per-competition analytics page:

- total + **Predicted** end score + "most X made" (top participant)
- **Score vs Predicted line chart** across past runs
- **Impact** (total score over the last N competitions, or last 90 / 365 days)
- **Lifetime insights:**
  - all-time highest (with date)
  - average
  - **current vs first** and **current vs previous**, each tagged
    *GOOD* / *NEEDS IMPROVEMENT*
- **player cards:** rank, "Previously #2", score, all-time high, average,
  deltas, **"VS player below"**, predictive score
- **comments** thread with quick-reply chips ("I knew you could do it!",
  "IMPRESSIVE!!") + GIF

### 1.8 Channels & TV

- **Channels list:** name, copy-TV-URL, and per row: 🖥 launch, ✎ edit,
  🗑 delete, ⋮ more.
- **🖥 Launch:** opens a **"Verify TV Channel"** dialog: "Go to
  tv.spinify.com on your TV and enter the code".
- **TV side (`tv.spinify.com`):** a full-screen branded page ("Celebrate the
  good!", animated confetti) showing a **4-character code** in big tiles.
  The admin types it against a channel and the TV starts playing. There's no
  login on the TV. (A code was shown; it was left unused.)
- **Channel editor:**
  - Sidekick name suggestions
  - Name · **RSS Feed Ticker** URL
  - **TV URL** checkbox, with a red warning not to post it publicly
  - **Channel Display Language** (8 locales)
  - **Screen Order:** a source filter (All / Only Competitions /
    Achievements / Dashboards / Compare Screens / Recognition Agents /
    Images / YouTubes), then a grouped searchable picker, "Add All Screens",
    an ordered table, Clear All and **Shuffle Screens**
  - Save / Cancel / Delete
- **Probable bug:** two channels opened with an *empty* screen list in the
  editor, even though the account has lots of content. Either those channels
  are empty, or the editor doesn't hydrate the existing order. If it's the
  latter, saving would wipe the rotation. Worth remembering as a failure mode
  to design against: **never render an editor whose state hasn't loaded.**

### 1.9 Recognition

- **Announcements (analytics):**
  - filters: timeframe, type (Performance / Competition / Gong / Rewards /
    Rep Milestones / Recognition Agent)
  - Overview (celebrations announced, points awarded, most announced, most
    celebrated), Latest Celebrations, **Activity Feed**
- **Manage Announcements (the rules):** two tables, Recognition Agents (AI)
  and Custom Announcements.
  - Columns: Title · Record Type · Points · **Enabled toggle** · actions
    (achievement log, edit, ⋮)
  - Defaults include: Badge, Tier, Birthday, Gong, Prize Wheel, Big Deal
    Alert, Lead Created, Lead Qualified, Resolve a Case, plus
    competition-change rules
- **Achievement editor (one long form):**
  - **Trigger.** A preconfigured list:
    - activity: Account Created, Calls Made, Cases Closed, Deals Won,
      Emails Sent, Leads Qualified, Meetings Completed, Trailing Revenue
    - competition: *Reaches % of Target*, *Reaches Score*, *Score Increases*
    - spreadsheet: Excel / Sheet score increases
    - other: Badge, Birthday, Gong, Local Scores, Tier, Work Anniversary
    - custom "Any X" record filters, including SQL
    - **filters:** field + operator (is true, >, <, ≥, ≤, is current day,
      within last 24 h), "Add Filter", "Add Filter Logic" (AND/OR expression)
  - **Owner field**, i.e. who gets credit.
  - **Recipients:** all users or a custom list.
  - **Theme:**
    - Title / Description / Message with **ADD TAG** merge variables
      (`{{User.DisplayName}}`, `{{Deal.Name}}`) and a magic-wand AI rewrite
    - "Enable AI Recognition Agent"
    - Trophy Type (17 incl. none), Show Motivational Text
    - **Entrance Animation: None / Slide / Bounce / Fade / Zoom / Flip**
  - **Background:** from the library, or **"URL from Record Fields"** (the
    record supplies the image, e.g. a property photo).
  - **Achievement Branding:** primary + secondary colour.
  - **Announcement:**
    - **Warm Up Video**: None / custom YouTube / library, including
      "Breaking News – Happy / Epic / Modern", "Special Report", "Path to
      Success"
    - **Sound:** None, *User's Achievement Sound*, upload, or 12 named
      effects (Cheerful Clapping, Cheering Crowd, Tremendous Trumpets,
      Blasting Bugle…)
  - **Duration:**
    - how long it stays in rotation (1 min → Forever)
    - "stop showing if the filter no longer matches"
    - seconds per show
    - seconds on *first* show
  - **Gamification:** points per achievement, or from a record field.
  - **Notifications:** on-screen popup / desktop push / mobile / email, each
    Off / Owner / Recipients.
  - **Channels** + Enable toggle · Save / Cancel.
  - Again **no live preview.** You design a full-screen celebration blind.
- **Messages:** Active / Expired tabs, a table of title · thumbnail · type ·
  created · starts · ends.
  - **Nine types:** Announcement (focused on a player), Countdown, Web,
    YouTube, Image, Meme, Motivational Quotes, Weather, Twitter.
  - **Real-world signal:** this org's messages are almost all *Image* slides,
    one per rep or team ("King ___", "The ___ Cartel"). **Admins are
    hand-making "player spotlight cards" in an image editor** because there's
    no template for it.
- **Gong:** Sidekick templates → recipient type (User / Team) → office →
  person → Title / Message, and a big illustrated gong to click.
- **Prize Wheels:** Active / Completed tabs; title · prizes · participants ·
  created.

### 1.10 Rewards

- **Badges:** an analytics-first page. Filters: office / team / user /
  timeframe. Overview: last badge earned, most earned, total awarded,
  average per rep, top earner, plus Top Players and Most Earned Badges panels.
  "Manage Badges" leads to the definitions.
- **Tiers:** a table of image · name · description · minimum points ·
  **point reward**. The defaults are animals:

  | Tier | Beetle | Butterfly | Mouse | Owl | Whale | Moose | Lion | Giraffe | Elephant | Cobra |
  |---|---|---|---|---|---|---|---|---|---|---|
  | Min points | 0 | 50 | 100 | 500 | 1K | 2.5K | 5K | 10K | 50K | 100K |

- **Points:** a **ledger**, one row per award: user, source (which
  competition), points, date. Filter by office and user.
- **Store:** a separate full-page mini-site ("Exchange your Points and get
  your Rewards!", confetti hero, "you have N PTS", a 3-step
  pick → exchange → get icon strip, All / Enabled / Disabled, Add Reward).
  Empty in this account.
- **Score Cards (under Coaching):** ranked photo cards with rank badge,
  **tier**, lifetime points and reward points, plus CSV export.
  - **Real-world signal:** the top ~dozen reps are *all* in the top tier,
    with ~165K–178K points against a 100K ceiling. **The tier ladder
    saturates within months**, and lifetime points equal reward points
    because nothing is ever spent. The economy has stalled.

### 1.11 Team, settings, branding

- **Users:**
  - count pills: All · Admins · Players · Fans
  - **seats used / allowed**
  - a table of avatar · name · role · email · **per-integration mapping
    icons**
  - row actions: edit · stats · send invite · delete
- **User editor ("Edit: name"):**
  - **Basic info:** photo (click to edit), first, last, **Nickname**, next
    birthday
  - **Employee info:** email, **work anniversary**, time zone,
    license (Admin / Player / Fan), role (Super Admin / Manager / Marketing /
    Participant / Player / Fan)
  - **Celebration Video:** None / Custom Sound (upload) / Music Video
    (library or YouTube URL)
  - **Celebration GIF** (for Slack and Teams)
  - **Channels / Offices / Teams for the Overview page** (limits what that
    user's home shows)
  - **Fun Competition Avatars:** 26 families, each with a chosen piece:
    Basketball, Bikes, Bugs, Candies, Cars, Cupcakes, Diamonds, Donuts,
    Emoji, Farm Animals, Fish, Football, Golf, Gummi Bears, Horse Racing,
    Hot Air Balloons, Jungle Animals, Lil Monsters, Lollipops, Ocean
    Animals, Party Balloons, Pizza, Planes, Poker Chips, Rockets, Soccer
- **Teams:** avatar · name · member count, with edit / delete.
- **Company Settings:**
  - company name + **logo** (1000×1000, < 5 MB)
  - **currency** (16)
  - **player name display** (First / First + initial / Full / Last /
    *Nickname*)
  - **competition end-time format** on the TV (Default / Simple / Full Text /
    Off, with a live sample bar "COMPETITION ENDS IN A DAY")
  - **TV box transparency** slider **with a live preview** over a sample
    background, plus a "Try a different background" link
  - **TV font** (Montserrat, Raleway, Mukta Mahee, Ubuntu, Indie Flower)
  - **weekend birthday and anniversary rule** (Friday before / actual day /
    Monday after)
  - send invite emails on create
  - **default competition reward points**
  - "Reset points and badges for all users"
- **Branding (a separate page):** slogan · brand logo (again) · **Brand
  Primary + Secondary colour**.
- **Mobile App:** a promo page (Chrome extension + mobile apps).

---

## Part 2 — What Spinify gets right (keep these)

1. **Design first, numbers second.** Picking a type, then a design, before
   any data makes building a competition feel like building a game.
2. **Mechanics as named presets.** "Golf Score", "Morning Rush", "Quota
   Crusher" and "Most No's" teach admins *what's possible* in one line each.
3. **Target Name = the TV column label.** One field, directly visible on the
   wall.
4. **Time as a first-class unit** (seconds → MM:SS / HH:MM:SS). Call centres
   need talk-time and wrap-time boards.
5. **Low-is-good sorting with "zeros last".** An easily missed detail that
   golf-score boards need.
6. **Screen time scales with participants.** Display speed is "seconds per
   participant", so a 40-person board isn't flashed for the same 10 s as a
   4-person one.
7. **The interstitial trio** (overtake, winner, milestones), each with a
   *simple* control: None / Important / All, and sound on/off.
8. **Trophy + motivational text + entrance animation** as reusable
   celebration building blocks.
9. **Warm-up video before a celebration** ("Breaking News" sting →
   announcement). It builds anticipation.
10. **Background from a record field.** The property photo on a real-estate
    sale, the product image on a deal.
11. **4-character TV pairing.** No typing URLs on a TV remote.
12. **Per-user flair lives on the user.** Sound, music video, GIF, nickname,
    birthday, anniversary and a fun avatar per game family.
13. **Company-level TV typography and glass opacity, with a live sample.**
14. **Weekend rule for birthdays.** A thoughtful edge case.
15. **Reports that compare runs:** current vs first, vs previous, predicted,
    "VS player below".
16. **Points as a ledger** with a source for every award.

## Part 3 — Where Spinify is weak (our openings)

| Weakness | Evidence | GoalGetter answer |
|---|---|---|
| **No live preview** in the competition wizard or the achievement editor | Theme step = a static thumbnail; the achievement form is ~40 fields designed blind | **Live 16:9 preview pane** on every editor that affects the wall, rendering the real display component with sample or real data. Toggle "sample data / live data". Buttons to "preview milestone / overtake / winner". |
| **230-design wall** with no search, filter or favourites | One 41,000 px scroll | **Composable styles.** A handful of *layouts* × *themes* × *backgrounds*, filterable by layout / mood / colour; favourites; "used recently"; "org defaults". Far fewer things to build, and more combinations for users. |
| **Customization is scattered** | Logo in both Company Settings *and* Branding; font and opacity in Company Settings; colours in Branding; per-competition colours in the Theme step; per-achievement colours elsewhere | **One "Appearance" system with inheritance:** Org theme → Channel → Screen/Competition → Celebration, each level showing "inherited from org" with a reset-to-inherited control. |
| **Fun designs drop all theming** | Fun styles hide the background and colour options | Every layout (including game boards) reads the same theme tokens; the game art is layered over themed surfaces. |
| **Tier ladder saturates** | Top reps at 165K+ with a 100K top tier; lifetime = reward points | **Seasons + prestige:** tiers reset per season (quarter), a lifetime "prestige star" count, and tier thresholds that auto-suggest from the org's point distribution. Show "next tier in N points" on player cards. |
| **Economy with nothing to spend** | Empty store | Ship a *starter catalog* (non-monetary rewards: "pick the playlist", "wear jeans Friday", "prime parking") and let the prize wheel pull from store items. |
| **Admins hand-make player-spotlight images** | Nearly every message is a custom Image of one rep or team | A **Player Spotlight screen type**: pick a person or team, and the layout pulls photo, nickname, stats, badges, tier and recent wins, with themed backgrounds. No image editor needed. |
| **Editor may render before it loads** (the empty channel screen list) | Seen on two channels | Editors show a skeleton until the data is loaded, and disable Save until they're "dirty and loaded". Destructive diffs ("this will remove 12 screens") need confirmation. |
| **Validation by toast** | "Some fields are missing", then hunting for the red text | Step list shows ✓ / ! per step; Next jumps to the first invalid field; inline hints before submit. |
| **AI everywhere, as the main way to get variety** | Sidekick on every form | Air-gapped alternatives: template libraries, random message *variants*, a name generator from word lists, bundled media. |
| **Slow loads with filler quotes** | 2–4 s spinners | Local, self-hosted, small payloads; skeletons over spinners. |

---

## Part 4 — Customization spec for GoalGetter

The goal: **at minimum match every Spinify customization option**, organised
so it's easier to use, and extended where it helps.

### 4.1 The model: four layers with inheritance

```
ORG THEME ──▶ CHANNEL ──▶ SCREEN (leaderboard / goal / competition / spotlight / …) ──▶ MOMENT (celebration, overtake, winner, milestone)
  brand,        overrides     layout + theme + background +             trophy, animation, sound, warm-up,
  fonts,        for this TV   display options                           text template, duration
  defaults      (e.g. office
                colours, language)
PERSON (orthogonal): photo/avatar, nickname, walk-up sound/video, fun-avatar picks, birthday/anniversary
```

- Every field at a lower layer is **"Inherit" by default** and shows the
  inherited value greyed out, with a "Customize" control to break
  inheritance and a "Reset" control to restore it.
- Stored as sparse JSON overrides (`appearance` column) on each entity.
  Resolved at render time in one pure function, `resolveAppearance(org,
  channel, screen, moment)`, which is easy to test and to cache.
- A **Theme preset** is just a named bundle of these tokens. Presets can be
  saved at org level, exported and imported as JSON, and shared between
  GoalGetter installs. Spinify has no equivalent.

### 4.2 Org theme (Settings → Appearance)

| Setting | Spinify has | GoalGetter: match | GoalGetter: beyond |
|---|---|---|---|
| Logo | ✓ (twice) | one logo, cropped, for app + wall | **light and dark variants**; a small "mark" for tight spaces; wall logo position (TL / TR / hidden) |
| Slogan | ✓ | ✓ shown in the wall header/footer | rotating slogans list |
| Brand colours | primary + secondary | primary + secondary | + **accent / success / warning**, all auto-contrast-checked (WCAG) with a warning when text fails |
| App theme | brand colours re-skin the admin | ✓ | light / dark / system for the app, independent of the wall |
| Wall font | 5 fonts | bundle ~8 open fonts locally (air-gap) | separate **display font** (numbers, names) and **body font**; **upload a font** (.woff2) |
| Panel ("glass") opacity | slider + live sample | ✓ with live sample | + blur amount, corner radius, panel colour |
| Name display | First / First+L / Full / Last / Nickname | ✓ same 5 | per-channel override (e.g. full names on the internal floor TV, initials on the lobby TV) |
| End-time format | Default / Simple / Full / Off | ✓ | position (header / footer), countdown style (days / clock) |
| Currency | 16 | org currency (have) | compact numbers toggle ("$1.2M") |
| Weekend birthday rule | Fri / day / Mon | ✓ | also holidays via an optional holiday list |
| Default reward points | ✓ | ✓ | |
| Wall footer | footer type (Default / Simple / Full / Off) | ✓ | footer content: slogan, clock, ticker, logo |

### 4.3 Channel (per TV playlist)

| Setting | Spinify | Match | Beyond |
|---|---|---|---|
| Name, screen order, shuffle | ✓ | ✓ (have ordering) | **weights** (show X twice as often) instead of duplicates; **schedule windows** per screen (e.g. Morning Rush only 8–9 am; hide on weekends) |
| Screen-source filter | ✓ | ✓ | smart playlists ("all active competitions in office X") that update automatically |
| RSS ticker | ✓ | **manual ticker items** (air-gap) + optional internal RSS | ticker speed and colour |
| Language | 8 locales | later (i18n) | |
| TV URL / no-login | ✓ + IP list | ✓ have (token + IP allowlist) | |
| **TV pairing code** | 4-char | ✓ 4–6 char code, 10-min TTL | show **device name** + last seen; "reassign this TV to channel Y" remotely; "reload TV now" |
| Channel theme override | ✗ | ✓ | e.g. a branch office TV in its own colours while inheriting the org logo |

### 4.4 Screen / competition appearance

**Layouts** (build once; every theme applies):

| Layout | Replaces Spinify group | Notes |
|---|---|---|
| **List** | Standard (81) | variants: bars, table, "spotlight" (list + highlighted card) |
| **Podium** | Podium (19) | top 3 + optional list below |
| **Head-to-head** | Head to Head (30) | individuals *or* teams (crests) |
| **Goal gauge / big number / thermometer** | Goal Tracker (15) | org-wide "Big Epic Goal" |
| **Goal stats grid** | Goal Stats (55) | everyone's own progress-to-goal, no ranking |
| **Game board** | Fun (~28) | a track/path engine with pluggable *board art* + per-person *tokens* (the fun avatars). One engine, many boards: race track, pool, maze, sky, court… |
| **Comparison** | Compare | 2–4 metrics side by side |
| **Player spotlight** *(new)* | hand-made Image messages | photo, stats, badges, tier, streak |
| **Countdown** | Countdown message | |

**Per-screen options.** Everything Spinify has on its TV / Gamification /
Theme steps, grouped into four panels.

*Data display:*
- sort (name / position / score)
- rows per screen (1–N) with auto-paging
- show all or top N
- show target, show "% of target" label, show scores, decimals, zero
  scorers
- show player stats panel
- unit format, including **duration formats**
- **target label**

*Timing:*
- dwell = base + **per-row seconds** (Spinify's per-participant idea), with
  a live "≈ 42 s on screen" readout
- page-flip speed

*Look:*
- layout · theme preset · primary / secondary / tertiary colour
- background:
  - solid, gradient, **bundled library** (~150 images and ~20 loop videos,
    categorised)
  - upload (image or video)
  - YouTube
  - **from record field**
  - **randomise per recurrence**
- **background dim / blur** (Spinify has none)
- font scale · panel opacity override

*Privacy (new):*
- show names as the org format / initials only / anonymous ranks
- hide below rank N ("only show the top 10 on the lobby TV")

**Editor UX:**
- The layout gallery is filterable (layout / mood / colour), searchable, with
  favourites and org-default presets.
- A **live 16:9 preview** sits beside the form throughout, with play buttons
  for each moment (overtake, milestone, winner).

### 4.5 Moments (celebrations, overtakes, winners, milestones)

| Option | Spinify | Match | Beyond |
|---|---|---|---|
| Overtake banner | with sound / silent / off | ✓ | cooldown (don't show more than once per N min); minimum rank to trigger (top 5 only) |
| Winner screen | hours in channel, seconds per show, trophy, motivational text | ✓ | **podium finale** (top 3 animated), confetti style |
| Milestones | None / Important / All | ✓ | custom milestone %s (e.g. 50 / 90 / 100 / 150) |
| Trophy | 16 types | ship ~16 bundled SVG trophies | org-uploaded trophy art |
| Entrance animation | None / Slide / Bounce / Fade / Zoom / Flip | ✓ | respects `prefers-reduced-motion` on the admin preview |
| Warm-up video | library + YouTube | bundled 3–5 "breaking news" stings + upload | **per-moment intro sound** |
| Sound | person's sound / upload / 12 effects | bundled effect pack + upload + person's walk-up | **volume normalisation** so one loud clip doesn't blow out the room; quiet hours (no sound 12–1 pm) |
| Text template | merge tags + AI rewrite | merge tags with **autocomplete and a live preview** | **3–5 variants picked at random** (the air-gapped answer to AI) |
| Duration controls | in-rotation lifetime, first show, repeat show, stop-if-unmatched | ✓ (have lifetime / hold; expose them) | |
| Background | library / record field | ✓ | person's own "celebration background" option |
| Replay | ✓ | ✓ | "preview on this TV only" for testing |

### 4.6 Person (profile & flair)

| Field | Spinify | Match | Beyond |
|---|---|---|---|
| Photo | upload | ✓ (in progress: tenant photo + custom) | crop and position; **frame or border by tier** |
| Built-in avatars | 160+ | ship a generated SVG avatar set (local) | avatar builder (hair / skin / accessories), deterministic from name |
| Nickname | ✓ | ✓ preferredName | nickname *on the wall*, controlled by the org name-display setting |
| Walk-up sound | upload MP3 ≤ 3 MB | ✓ (URL today, **add upload**) | trim start / end in the browser; volume |
| Music video | library + YouTube | ✓ YouTube + offsets (have) | curated default list |
| Celebration GIF | for Slack / Teams | later, with Slack / Teams | |
| Birthday / anniversary | ✓ | ✓ month/day only | opt-out per person (privacy) |
| Fun avatars | 26 families | one token per board family | tokens unlockable by tier or badges (cosmetic rewards, a reason to earn points) |
| Home content scope | channels / offices / teams for the Overview | | agent picks "my" leaderboards to pin |
| **Self-service vs admin-set** | both | org toggle per field: *agent may edit* / *admin only* | approval queue for uploaded media (avoids inappropriate clips on the floor TV) |

### 4.7 Gamification economy (when you get there)

- **Ledger** like Spinify's, plus **seasons**. Quarterly tiers reset, with a
  lifetime prestige count.
- **Tier ladder:**
  - auto-suggested from the point distribution, or the default animals
  - **tier point reward** (Spinify has this)
  - a tier-up is a moment
- **Badges:** manual, or "achievement fired N times within period"
  (Spinify's model), with a bundled badge art set.
- **Store:** request → approve → fulfil (refund on reject), with a starter
  catalog.
- **Cosmetic unlocks:** tokens, frames and backgrounds by tier. This gives
  points a use even without a store.
- **Prize wheel:** can draw from store items.

---

## Part 5 — Suggested build order

1. **Appearance foundation:**
   - an `appearance` JSON column on org, channel and screen
   - `resolveAppearance()`
   - Settings → Appearance: logo, colours, fonts, panel opacity, name
     format, end-time format, all with a **live preview**
2. **Live preview component.** Render the real wall component at 16:9 inside
   editors, with sample data.
3. **Layouts:** List (have) → Podium → Goal gauge / Big Epic Goal → Goal
   stats grid → Comparison → Player spotlight → Game board engine (race
   track first).
4. **Moments:** overtake, winner, milestones (None / Important / All),
   trophies, entrance animations, bundled sound pack, merge tags +
   variants, replay.
5. **Person flair:** uploaded walk-up audio, avatar set, fun tokens,
   birthday / anniversary, self-service toggles + media approval.
6. **Display ops:** pairing code, remote reassign / reload, schedule
   windows, weights.
7. **Economy:** ledger + seasons → tiers → badges → cosmetic unlocks →
   store → wheel.

---

## Appendix — Accounts & safety log for this session

- Viewed only. A new-competition wizard was filled with a placeholder name,
  a local-score metric and one participant (the account owner) to reach
  later steps. **It was cancelled; a Draft filter afterwards confirmed
  nothing was saved.**
- Opened and cancelled: one channel editor (×2), one achievement editor, the
  user's own profile editor, the background and theme pickers, and seven
  "Verify TV Channel" dialogs (no code entered).
- Visited in passing: Company Settings, Branding and the Mobile page (no
  edits).
- The Integrations list page was loaded once by a mis-click while expanding
  the menu. Nothing on it was clicked, and it was left immediately.
