/*
 * GoalGetter demo — shared runtime.
 *
 * Every tour page is a plain HTML file holding only its own content. This
 * script wraps that content in the app's shell (top bar, sidebar), adds the
 * tour bar and guide panel, and wires up the small interactions the pages
 * share: tabs, modals, toasts, theme, role, hotspots and transitions.
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ *
   * Icons — the app's own 24px stroke icons (web/src/components/icons.tsx)
   * ------------------------------------------------------------------ */
  const PATHS = {
    home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    trophy: '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4Z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    flag: '<path d="M5 21V4M5 4h10l-1.5 3L15 10H5"/>',
    megaphone: '<path d="M3 10v4a1 1 0 0 0 1 1h3l6 4V5L7 9H4a1 1 0 0 0-1 1Z"/><path d="M17 9a4 4 0 0 1 0 6M7 15l1 4h2"/>',
    spark: '<path d="M12 3l2.1 5.4L19.5 10l-5.4 2.1L12 17.5l-2.1-5.4L4.5 10l5.4-1.6L12 3Z"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    tv: '<rect x="2.5" y="5" width="19" height="12.5" rx="2"/><path d="M8 21h8M12 17.5V21"/>',
    medal: '<circle cx="12" cy="15" r="6"/><path d="M8.5 9.5 6 2.5h12l-2.5 7"/><path d="m12 12.5 1 2 2.2.3-1.6 1.5.4 2.2-2-1-2 1 .4-2.2-1.6-1.5 2.2-.3z"/>',
    palette: '<path d="M12 3a9 9 0 1 0 0 18c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1a1.5 1.5 0 0 1 1.06-2.56H16a5 5 0 0 0 5-5c0-4.42-4.03-8-9-8Z"/><circle cx="7.5" cy="12" r="1"/><circle cx="9.5" cy="8" r="1"/><circle cx="14" cy="7.5" r="1"/><circle cx="17" cy="11" r="1"/>',
    users: '<path d="M16 19v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 17.5V19"/><circle cx="10" cy="8" r="3.25"/><path d="M20 19v-1.5a3.5 3.5 0 0 0-2.75-3.42M15.5 5.2a3.25 3.25 0 0 1 0 5.6"/>',
    building: '<path d="M4 21V5.5A1.5 1.5 0 0 1 5.5 4h7A1.5 1.5 0 0 1 14 5.5V21"/><path d="M14 10h4.5A1.5 1.5 0 0 1 20 11.5V21M2.5 21h19"/><path d="M7 8h4M7 12h4M7 16h4"/>',
    plug: '<path d="M9 3v6M15 3v6M7 9h10v3a5 5 0 0 1-10 0V9ZM12 17v4"/>',
    ruler: '<rect x="2.5" y="7" width="19" height="10" rx="2"/><path d="M7 7v3M12 7v4M17 7v3"/>',
    pencil: '<path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3z"/><path d="M14.5 6.5l3 3"/>',
    inbox: '<path d="M3 13.5 5.5 5h13l2.5 8.5V19H3v-5.5Z"/><path d="M3 13.5h5l1.5 2.5h5l1.5-2.5h5"/>',
    image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.75"/><path d="m21 16-5-5-9 9"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.5-4.5"/>',
    bell: '<path d="M18 8.5a6 6 0 1 0-12 0c0 5-2 6.5-2 6.5h16s-2-1.5-2-6.5"/><path d="M10.5 19a1.8 1.8 0 0 0 3 0"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    chevron: '<path d="M6 9.5 12 15.5l6-6"/>',
    play: '<path d="M8 5.5l10 6.5-10 6.5V5.5Z" fill="currentColor"/>',
    pause: '<path d="M9.5 5v14M14.5 5v14" stroke-width="2.5"/>',
    speaker: '<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
    mail: '<path d="M3 6.5h18v11H3z"/><path d="m3.5 7 8.5 6 8.5-6"/>',
    database: '<ellipse cx="12" cy="5.5" rx="7.5" ry="3"/><path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13"/><path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3"/>',
    repeat: '<path d="M4 9V8a3 3 0 0 1 3-3h10l-2.5-2.5M20 15v1a3 3 0 0 1-3 3H7l2.5 2.5"/>',
    copy: '<rect x="9" y="9" width="11.5" height="11.5" rx="2"/><path d="M5.5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5v1"/>',
    trash: '<path d="M4 6.5h16"/><path d="M9.5 6.5V4.5A1 1 0 0 1 10.5 3.5h3a1 1 0 0 1 1 1v2"/><path d="M6.5 6.5 7.5 20a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4l1-13.5"/><path d="M10.5 10.5v7M13.5 10.5v7"/>',
    archive: '<path d="M3 7.5h18V5.5A1.5 1.5 0 0 0 19.5 4h-15A1.5 1.5 0 0 0 3 5.5v2Z"/><path d="M4.5 7.5V19a1.5 1.5 0 0 0 1.5 1.5h12A1.5 1.5 0 0 0 19.5 19V7.5"/><path d="M10 11.5h4"/>',
    key: '<path d="M14.5 3.5a5 5 0 1 0-4.2 7.7L4 17.5V21h3.5l1-1v-2h2v-2h1.8l1-1a5 5 0 0 0 1.2.2Z"/><path d="M16.5 7.5h.01"/>',
    // Demo-only glyphs, drawn in the same style.
    left: '<path d="M15 6l-6 6 6 6"/>',
    right: '<path d="M9 6l6 6-6 6"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z"/>',
    guide: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5v-13Z"/><path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5v-13Z"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.6 4.5M20 20v-4h-4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
  };

  function icon(name, cls) {
    return (
      '<svg class="icon ' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (PATHS[name] || '') +
      '</svg>'
    );
  }

  /* ------------------------------------------------------------------ *
   * Avatars — same deterministic colour as web/src/components/avatarColour.ts
   * ------------------------------------------------------------------ */
  function hash(text) {
    let value = 0x811c9dc5;
    for (let i = 0; i < text.length; i += 1) {
      value ^= text.charCodeAt(i);
      value = Math.imul(value, 0x01000193);
    }
    return value >>> 0;
  }
  function avatarColour(name) {
    const hue = (hash(name.trim().toLowerCase()) % 12) * 30;
    return 'hsl(' + hue + ' 58% 42%)';
  }
  function initialsOf(name) {
    return name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(function (p) { return p[0].toUpperCase(); })
      .join('');
  }
  function avatar(name, size) {
    return (
      '<span class="avatar ' + (size || '') + '" aria-hidden="true" style="background-color:' +
      avatarColour(name) + '">' + initialsOf(name) + '</span>'
    );
  }

  /* ------------------------------------------------------------------ *
   * The fictional organization
   * ------------------------------------------------------------------ */
  const ORG = { name: 'Stark Industries', short: 'Stark' };

  const OFFICES = [
    { name: 'Gotham', tz: 'America/New_York', city: 'Eastern time' },
    { name: 'Metropolis', tz: 'America/Chicago', city: 'Central time' },
    { name: 'Star City', tz: 'America/Los_Angeles', city: 'Pacific time' },
    { name: 'Central City', tz: 'America/Denver', city: 'Mountain time' },
  ];

  const TEAMS = [
    { name: 'Avengers', short: 'AVG', color: '#b91c1c', office: 'Gotham', manager: 'Steve Rogers' },
    { name: 'Justice League', short: 'JL', color: '#1d4ed8', office: 'Metropolis', manager: 'Diana Prince' },
    { name: 'Bolt Squad', short: 'BLT', color: '#0e7490', office: 'Star City', manager: 'Justin Herbert' },
    { name: 'Halo Crew', short: 'HLO', color: '#c2410c', office: 'Star City', manager: 'Tim Salmon' },
    { name: 'Speed Force', short: 'SPF', color: '#7c3aed', office: 'Central City', manager: 'Barry Allen' },
  ];

  // [revenue, deals closed, calls, appointments set]
  const AGENTS = [
    ['Peter Parker', 'Avengers', 48250, 14, 412, 31],
    ['Natasha Romanoff', 'Avengers', 61400, 18, 365, 28],
    ['Wanda Maximoff', 'Avengers', 39900, 11, 298, 22],
    ['Carol Danvers', 'Avengers', 55150, 16, 344, 26],
    ['Sam Wilson', 'Avengers', 28700, 8, 256, 17],
    ['Clark Kent', 'Justice League', 58900, 17, 389, 30],
    ['Bruce Wayne', 'Justice League', 66200, 19, 301, 24],
    ['Arthur Curry', 'Justice League', 31800, 9, 278, 19],
    ['Hal Jordan', 'Justice League', 44300, 13, 352, 27],
    ['Victor Stone', 'Justice League', 36500, 10, 330, 21],
    ['LaDainian Tomlinson', 'Bolt Squad', 71800, 21, 398, 33],
    ['Philip Rivers', 'Bolt Squad', 52700, 15, 421, 29],
    ['Antonio Gates', 'Bolt Squad', 47100, 14, 310, 23],
    ['Keenan Allen', 'Bolt Squad', 50600, 15, 376, 25],
    ['Derwin James', 'Bolt Squad', 33900, 10, 287, 18],
    ['Joey Bosa', 'Bolt Squad', 42800, 12, 305, 20],
    ['Mike Trout', 'Halo Crew', 69400, 20, 367, 32],
    ['Shohei Ohtani', 'Halo Crew', 74100, 22, 349, 34],
    ['Garret Anderson', 'Halo Crew', 38200, 11, 292, 21],
    ['Troy Glaus', 'Halo Crew', 35600, 10, 318, 19],
    ['Jered Weaver', 'Halo Crew', 45900, 13, 334, 24],
    ['Wally West', 'Speed Force', 41700, 12, 433, 26],
    ['Kara Danvers', 'Speed Force', 57300, 17, 358, 29],
    ['Dinah Lance', 'Speed Force', 34100, 10, 301, 20],
    ['Oliver Queen', 'Speed Force', 49800, 14, 326, 25],
    ['Billy Batson', 'Speed Force', 26400, 7, 244, 15],
  ];

  function officeOf(teamName) {
    const t = TEAMS.find(function (x) { return x.name === teamName; });
    return t ? t.office : '';
  }
  function emailOf(name) {
    return name.toLowerCase().replace(/[^a-z ]/g, '').replace(/\s+/g, '.') + '@stark.example';
  }

  const PEOPLE = AGENTS.map(function (a) {
    return {
      name: a[0], team: a[1], office: officeOf(a[1]), role: 'Agent',
      revenue: a[2], deals: a[3], calls: a[4], appts: a[5], email: emailOf(a[0]),
    };
  })
    .concat(TEAMS.map(function (t) {
      return { name: t.manager, team: t.name, office: t.office, role: 'Manager', email: emailOf(t.manager) };
    }))
    .concat([
      { name: 'Tony Stark', team: null, office: 'Gotham', role: 'Admin', email: emailOf('Tony Stark') },
      { name: 'Pepper Potts', team: null, office: 'Gotham', role: 'Admin', email: emailOf('Pepper Potts') },
    ]);

  const VIEWER = 'Peter Parker';

  /* Places moved since last period — stable per person and metric. */
  function movementFor(name, metric) {
    const h = hash(name + ':' + metric) % 9;
    if (h === 8) return null;
    return h - 4 > 0 ? h - 4 : h === 0 ? 0 : -(h % 3);
  }

  function fmt(value, unit) {
    if (unit === 'currency') return '$' + Math.round(value).toLocaleString('en-US');
    if (unit === 'duration') {
      const h = Math.floor(value / 60);
      return h + 'h ' + String(Math.round(value % 60)).padStart(2, '0') + 'm';
    }
    return Math.round(value).toLocaleString('en-US');
  }

  /* ------------------------------------------------------------------ *
   * The tour
   * ------------------------------------------------------------------ */
  const TOUR = [
    { id: 'home', file: 'home.html', title: 'Home', icon: 'home', blurb: 'Where things stand today' },
    { id: 'leaderboards', file: 'leaderboards.html', title: 'Leaderboards', icon: 'trophy', blurb: 'Live rankings for any metric' },
    { id: 'goals', file: 'goals.html', title: 'Goals', icon: 'target', blurb: 'Targets with pace, not just progress' },
    { id: 'competitions', file: 'competitions.html', title: 'Competitions', icon: 'flag', blurb: 'Time-boxed contests' },
    { id: 'announcements', file: 'announcements.html', title: 'Announcements', icon: 'megaphone', blurb: 'Wins, shout-outs and TV news' },
    { id: 'users', file: 'users.html', title: 'Users', icon: 'users', blurb: 'People, roles and access' },
    { id: 'teams', file: 'teams.html', title: 'Teams', icon: 'users', blurb: 'Groups that compete together' },
    { id: 'offices', file: 'offices.html', title: 'Offices', icon: 'building', blurb: 'Locations and time zones' },
    { id: 'channels', file: 'channels.html', title: 'TVs & Channels', icon: 'tv', blurb: 'What plays on the walls' },
    { id: 'tv-wall', file: 'tv-wall.html', title: 'The TV wall', icon: 'tv', blurb: 'Full-screen, across the room' },
    { id: 'reporting', file: 'reporting.html', title: 'Reporting', icon: 'chart', blurb: 'Who needs a conversation' },
    { id: 'integrations', file: 'integrations.html', title: 'Integrations & Metrics', icon: 'plug', blurb: 'Getting your data in' },
    { id: 'admin', file: 'admin.html', title: 'Admin & Settings', icon: 'settings', blurb: 'Branding, inbox, assets' },
  ];

  /* The app's real sidebar (web/src/components/AppShell.tsx), with the tour
     page each entry opens. `min` is the least role that sees it. */
  const SECTIONS = [
    {
      items: [
        { label: 'Home', icon: 'home', to: 'home.html', page: 'home' },
        { label: 'Leaderboards', icon: 'trophy', to: 'leaderboards.html', page: 'leaderboards' },
        { label: 'Goals', icon: 'target', to: 'goals.html', page: 'goals' },
        { label: 'Competitions', icon: 'flag', to: 'competitions.html', page: 'competitions' },
        { label: 'Announcements', icon: 'megaphone', to: 'announcements.html', page: 'announcements' },
        { label: 'Points', icon: 'spark', to: null },
        { label: 'Reporting', icon: 'chart', to: 'reporting.html', page: 'reporting', min: 'manager' },
      ],
    },
    {
      heading: 'Wall',
      items: [
        { label: 'TVs & Channels', icon: 'tv', to: 'channels.html', page: 'channels', also: ['tv-wall'], min: 'admin' },
        { label: 'Celebrations', icon: 'medal', to: null, min: 'admin' },
        { label: 'Appearance', icon: 'palette', to: 'admin.html?tab=appearance', page: 'admin:appearance', min: 'admin' },
      ],
    },
    {
      heading: 'People',
      items: [
        { label: 'Users', icon: 'users', to: 'users.html', page: 'users', min: 'manager' },
        { label: 'Teams', icon: 'users', to: 'teams.html', page: 'teams' },
        { label: 'Offices', icon: 'building', to: 'offices.html', page: 'offices', min: 'admin' },
      ],
    },
    {
      heading: 'Data',
      items: [
        { label: 'Integrations', icon: 'plug', to: 'integrations.html', page: 'integrations', min: 'admin' },
        { label: 'Metrics', icon: 'ruler', to: 'integrations.html#metrics', min: 'admin' },
        { label: 'Corrections', icon: 'pencil', to: null, min: 'manager' },
      ],
    },
    {
      heading: 'Organization',
      items: [
        { label: 'Inbox', icon: 'inbox', to: 'admin.html?tab=inbox', page: 'admin:inbox', min: 'admin', count: 3 },
        { label: 'Assets', icon: 'image', to: 'admin.html?tab=assets', page: 'admin:assets', min: 'admin' },
        { label: 'Points setup', icon: 'spark', to: null, min: 'admin' },
        { label: 'Settings', icon: 'settings', to: 'admin.html', page: 'admin:settings', min: 'admin' },
      ],
    },
  ];

  const RANK = { agent: 0, manager: 1, admin: 2 };

  /* ------------------------------------------------------------------ *
   * Small utilities
   * ------------------------------------------------------------------ */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function el(html) {
    const t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
  }
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem('ggdemo:' + key);
      localStorage.setItem('ggdemo:' + key, value);
    } catch (e) { /* private mode */ }
    return null;
  }
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ------------------------------------------------------------------ *
   * Theme & role
   * ------------------------------------------------------------------ */
  function currentTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  }
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    store('theme', theme);
    $$('[data-theme-toggle]').forEach(function (b) {
      b.innerHTML = icon(theme === 'light' ? 'moon' : 'sun');
      b.setAttribute('aria-label', theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme');
    });
  }
  function currentRole() {
    return store('role') || 'admin';
  }
  function setRole(role) {
    store('role', role);
    document.body.dataset.role = role;
    $$('.role-switch button').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.role === role));
    });
    renderNav();
  }

  /* ------------------------------------------------------------------ *
   * Toasts
   * ------------------------------------------------------------------ */
  function toast(message) {
    let host = $('.toasts');
    if (!host) {
      host = el('<div class="toasts" role="status" aria-live="polite"></div>');
      document.body.appendChild(host);
    }
    const t = el('<div class="toast"><span class="tick">' + icon('check', 'sm') + '</span><span></span></div>');
    t.lastElementChild.textContent = message;
    host.appendChild(t);
    setTimeout(function () {
      t.classList.add('is-leaving');
      setTimeout(function () { t.remove(); }, 200);
    }, 2800);
  }

  /* ------------------------------------------------------------------ *
   * Shell
   * ------------------------------------------------------------------ */
  const page = document.body.dataset.page;
  const tab = new URLSearchParams(location.search).get('tab');
  const pageKey = page === 'admin' ? 'admin:' + (tab || 'settings') : page;
  const stepIndex = TOUR.findIndex(function (t) { return t.id === page; });

  function navItemHtml(item) {
    const active = item.page === pageKey || (item.also || []).indexOf(page) >= 0;
    const href = item.to || '#';
    return (
      '<li><a class="nav-item" href="' + href + '"' +
      (item.to ? '' : ' data-not-in-tour="' + item.label + '"') +
      (active ? ' aria-current="page"' : '') + '>' +
      icon(item.icon) + '<span class="label">' + item.label + '</span>' +
      (item.count ? '<span class="count num" aria-label="' + item.count + ' open">' + item.count + '</span>' : '') +
      '</a></li>'
    );
  }

  function navHtml() {
    const role = RANK[currentRole()];
    return SECTIONS.map(function (section) {
      const shown = section.items.filter(function (i) { return RANK[i.min || 'agent'] <= role; });
      if (shown.length === 0) return '';
      const list = '<ul class="nav-list">' + shown.map(navItemHtml).join('') + '</ul>';
      if (!section.heading) return '<div>' + list + '</div>';
      return (
        '<div><button type="button" class="nav-heading" aria-expanded="true">' +
        section.heading + icon('chevron', 'xs') + '</button>' + list + '</div>'
      );
    }).join('');
  }

  function renderNav() {
    $$('[data-nav]').forEach(function (n) { n.innerHTML = navHtml(); });
  }

  function tourBarHtml() {
    const step = TOUR[stepIndex];
    const prev = TOUR[stepIndex - 1];
    const next = TOUR[stepIndex + 1];
    const menu = TOUR.map(function (t, i) {
      return (
        '<a href="' + t.file + '"' + (i === stepIndex ? ' aria-current="page"' : '') +
        (i < stepIndex ? ' class="done"' : '') + '><span class="n">' + (i + 1) + '</span>' +
        '<span>' + t.title + '<br><span class="c-subtle text-xs">' + t.blurb + '</span></span></a>'
      );
    }).join('');
    const role = currentRole();
    return (
      '<div class="tourbar" style="--tour-progress:' + (((stepIndex + 1) / TOUR.length) * 100) + '%">' +
      '<a class="tour-home" href="../index.html" aria-label="Back to the GoalGetter overview">' +
      '<span class="logo">' + icon('target') + '</span><span class="word">GoalGetter</span>' +
      '<span class="demo-tag">Demo</span></a>' +
      '<div class="tour-step">' +
      '<button type="button" class="tour-step-btn" aria-haspopup="true" aria-expanded="false" data-tour-menu>' +
      '<span class="num">' + (stepIndex + 1) + '<span class="of"> of ' + TOUR.length + '</span></span>' +
      '<strong class="truncate">' + step.title + '</strong>' + icon('chevron', 'sm') + '</button>' +
      '<nav class="tour-menu" aria-label="Tour pages" hidden>' + menu + '</nav></div>' +
      '<div class="tour-controls">' +
      '<div class="role-switch" role="group" aria-label="View as">' +
      '<span class="lbl">View as</span>' +
      ['agent', 'manager', 'admin'].map(function (r) {
        return '<button type="button" data-role="' + r + '" aria-pressed="' + (r === role) + '">' +
          r[0].toUpperCase() + r.slice(1) + '</button>';
      }).join('') +
      '</div>' +
      '<button type="button" class="tour-btn square" data-theme-toggle></button>' +
      '<button type="button" class="tour-btn" data-guide-toggle aria-label="Toggle the guide">' + icon('guide') + '<span class="txt">Guide</span></button>' +
      (prev
        ? '<a class="tour-btn square" href="' + prev.file + '" aria-label="Previous: ' + prev.title + '">' + icon('left') + '</a>'
        : '<a class="tour-btn square" href="../index.html" aria-label="Back to the overview">' + icon('left') + '</a>') +
      (next
        ? '<a class="tour-btn primary" href="' + next.file + '"><span class="txt">Next</span>' + icon('right') + '</a>'
        : '<a class="tour-btn primary" href="../index.html#get-started"><span class="txt">Finish</span>' + icon('check') + '</a>') +
      '</div></div>'
    );
  }

  function topBarHtml() {
    return (
      '<header class="app-topbar">' +
      '<button class="icon-btn menu-btn" aria-label="Open navigation" data-drawer-open>' + icon('menu') + '</button>' +
      '<a href="home.html" class="app-brand" aria-label="GoalGetter, home">' +
      '<span class="org-logo" aria-hidden="true"><span class="arc"></span>Stark</span>' +
      '<span class="product">GoalGetter</span></a>' +
      '<div class="topbar-actions">' +
      '<button type="button" class="search-btn" aria-label="Search" data-palette-open>' + icon('search', 'sm') +
      '<span class="label">Search</span><kbd>' + (navigator.platform.indexOf('Mac') >= 0 ? '⌘K' : 'Ctrl K') + '</kbd></button>' +
      '<div class="bell" style="position:relative">' +
      '<button type="button" class="icon-btn" aria-label="Notifications, 3 unread" aria-expanded="false" data-bell>' + icon('bell') +
      '<span class="badge num">3</span></button>' + bellHtml() + '</div>' +
      '<a class="account-link" href="#" data-not-in-tour="Your account">' + avatar(VIEWER) +
      '<span class="label">' + VIEWER + '</span></a>' +
      '</div></header>'
    );
  }

  function bellHtml() {
    const items = [
      ['Shohei Ohtani', '<strong>Shohei Ohtani</strong> passed you on <span class="c-content">Revenue · October</span>', '4 min ago', true],
      ['Natasha Romanoff', '<strong>Natasha Romanoff</strong> recognised you: “Closed the Oscorp renewal in one call.”', '22 min ago', true],
      ['Peter Parker', 'You hit <strong>Calls · This week</strong> — 250 of 250', '1 h ago', true],
      ['Steve Rogers', '<strong>Steve Rogers</strong> started <span class="c-content">Fall Classic</span>', 'Yesterday', false],
    ];
    return (
      '<div class="popover" hidden data-bell-pop role="dialog" aria-label="Notifications">' +
      '<header><span class="text-h3">Notifications</span><button class="link" data-mark-read>Mark all read</button></header><ul>' +
      items.map(function (n) {
        return '<li' + (n[3] ? ' class="unread"' : '') + '>' + avatar(n[0]) +
          '<div class="grow"><p class="text-sm c-muted">' + n[1] + '</p><p class="text-xs c-subtle mt-1">' + n[2] + '</p></div></li>';
      }).join('') + '</ul></div>'
    );
  }

  function guideHtml(tpl) {
    const step = TOUR[stepIndex];
    const next = TOUR[stepIndex + 1];
    const prev = TOUR[stepIndex - 1];
    const intro = $('.intro', tpl.content);
    const who = $('.who', tpl.content);
    const steps = $$('ol > li', tpl.content);
    return (
      '<div class="guide-inner">' +
      '<div class="guide-head"><div><p class="guide-kicker">Step ' + (stepIndex + 1) + ' of ' + TOUR.length + '</p>' +
      '<h2>' + step.title + '</h2></div>' +
      '<button class="guide-close" data-guide-toggle aria-label="Hide the guide">' + icon('close') + '</button></div>' +
      (intro ? '<p class="guide-intro">' + intro.innerHTML + '</p>' : '') +
      (who ? '<div class="guide-who">' + who.innerHTML + '</div>' : '') +
      '<ol class="guide-steps">' +
      steps.map(function (li, i) {
        return (
          '<li class="guide-step" data-step="' + i + '">' +
          '<button type="button" aria-expanded="false"><span class="num">' + (i + 1) + '</span>' +
          '<span>' + li.dataset.title + '</span></button>' +
          '<div class="body"><div>' + li.innerHTML + '</div></div></li>'
        );
      }).join('') +
      '</ol>' +
      '<div class="guide-nav">' +
      (next
        ? '<a class="guide-next" href="' + next.file + '"><small>Next up</small><strong>' + next.title + icon('right', 'sm') + '</strong></a>'
        : '<a class="guide-next" href="../index.html#get-started"><small>That is the tour</small><strong>Back to the overview' + icon('right', 'sm') + '</strong></a>') +
      (prev ? '<a class="guide-prev" href="' + prev.file + '">← Back to ' + prev.title + '</a>' : '<a class="guide-prev" href="../index.html">← Back to the overview</a>') +
      '</div></div>'
    );
  }

  function buildShell() {
    const main = $('#main');
    const wallOnly = document.body.dataset.shell === 'wall';
    const tpl = $('#guide');

    const frame = el('<div class="app-frame"></div>');
    const shell = el('<div class="app-shell"></div>');

    if (wallOnly) {
      shell.appendChild(main);
    } else {
      shell.appendChild(el(topBarHtml()));
      const body = el('<div class="app-body"></div>');
      body.appendChild(el('<nav class="app-sidebar" aria-label="Main" data-nav></nav>'));
      body.appendChild(main);
      shell.appendChild(body);
    }
    frame.appendChild(shell);

    if (tpl) {
      frame.appendChild(el('<aside class="guide" aria-label="Tour guide">' + guideHtml(tpl) + '</aside>'));
    }

    document.body.insertBefore(el(tourBarHtml()), document.body.firstChild);
    document.body.insertBefore(frame, document.body.children[1]);
    document.body.appendChild(el('<div class="guide-scrim" data-guide-toggle></div>'));
    document.body.appendChild(el(
      '<div class="drawer" data-drawer><div class="scrim" data-drawer-close></div>' +
      '<nav aria-label="Main"><div style="display:flex;justify-content:flex-end;margin-bottom:.5rem">' +
      '<button class="icon-btn" data-drawer-close aria-label="Close navigation">' + icon('close') + '</button></div>' +
      '<div data-nav></div></nav></div>'
    ));
    document.body.appendChild(el(
      '<div class="modal-host" hidden data-palette><div class="scrim" data-palette-close></div>' +
      '<div class="palette" role="dialog" aria-label="Search"><input type="text" placeholder="Jump to a page, a person or a board…" aria-label="Search">' +
      '<ul></ul></div></div>'
    ));

    renderNav();
    setTheme(currentTheme());
    document.body.dataset.role = currentRole();
    if (store('guide') === 'off') document.body.classList.add('guide-collapsed');
  }

  /* ------------------------------------------------------------------ *
   * Guide & hotspots
   * ------------------------------------------------------------------ */
  function activateStep(i, opts) {
    const steps = $$('.guide-step');
    steps.forEach(function (s, n) {
      s.classList.toggle('is-active', n === i);
      $('button', s).setAttribute('aria-expanded', String(n === i));
    });
    $$('.hs-active').forEach(function (t) { t.classList.remove('hs-active'); });
    const tpl = $('#guide');
    const li = tpl ? $$('ol > li', tpl.content)[i] : null;
    const target = li && li.dataset.target ? $(li.dataset.target) : null;
    if (target) {
      void target.offsetWidth;
      target.classList.add('hs-active');
      if (opts && opts.scroll) {
        target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
      }
    }
    const step = steps[i];
    if (step && opts && opts.scrollGuide) {
      step.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest' });
    }
  }

  let hotspotsBuilt = false;
  function buildHotspots() {
    const tpl = $('#guide');
    if (!tpl || hotspotsBuilt) return;
    hotspotsBuilt = true;
    $$('ol > li', tpl.content).forEach(function (li, i) {
      const target = li.dataset.target ? $(li.dataset.target) : null;
      if (!target) return;
      target.classList.add('hs-target');
      const dot = el('<button type="button" class="hs-dot" style="--i:' + i + '" aria-label="Tour note ' + (i + 1) + ': ' + li.dataset.title + '">' + (i + 1) + '</button>');
      dot.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (window.innerWidth < 1280) document.body.classList.add('guide-open');
        activateStep(i, { scrollGuide: true });
      });
      target.appendChild(dot);
    });
    $$('.guide-step > button').forEach(function (b, i) {
      b.addEventListener('click', function () {
        const open = b.parentElement.classList.contains('is-active');
        if (open) {
          b.parentElement.classList.remove('is-active');
          b.setAttribute('aria-expanded', 'false');
          $$('.hs-active').forEach(function (t) { t.classList.remove('hs-active'); });
        } else {
          if (window.innerWidth < 1280) document.body.classList.remove('guide-open');
          activateStep(i, { scroll: true });
        }
      });
    });
    if ($('.guide-step')) {
      $('.guide-step').classList.add('is-active');
      $('.guide-step > button').setAttribute('aria-expanded', 'true');
    }
  }

  /* ------------------------------------------------------------------ *
   * Command palette
   * ------------------------------------------------------------------ */
  function paletteEntries() {
    const pages = TOUR.map(function (t) { return { label: t.title, href: t.file, kind: 'Page', icon: t.icon }; });
    const people = PEOPLE.map(function (p) {
      return { label: p.name, href: 'users.html?q=' + encodeURIComponent(p.name), kind: p.team || p.role, person: true };
    });
    const boards = [
      { label: 'Revenue · This month', href: 'leaderboards.html?board=revenue', kind: 'Leaderboard', icon: 'trophy' },
      { label: 'Calls · This week', href: 'leaderboards.html?board=calls', kind: 'Leaderboard', icon: 'trophy' },
      { label: 'Fall Classic', href: 'competitions.html', kind: 'Competition', icon: 'flag' },
    ];
    return pages.concat(boards, people);
  }

  function openPalette() {
    const host = $('[data-palette]');
    const input = $('input', host);
    const list = $('ul', host);
    const all = paletteEntries();
    let active = 0;
    let shown = [];
    function render() {
      const q = input.value.trim().toLowerCase();
      shown = all.filter(function (e) { return !q || e.label.toLowerCase().indexOf(q) >= 0 || e.kind.toLowerCase().indexOf(q) >= 0; }).slice(0, 9);
      active = Math.min(active, Math.max(shown.length - 1, 0));
      list.innerHTML = shown.length
        ? shown.map(function (e, i) {
          return '<li><a href="' + e.href + '"' + (i === active ? ' class="is-active"' : '') + '>' +
            (e.person ? avatar(e.label, 'xs') : icon(e.icon, 'sm')) + '<span>' + e.label + '</span><span class="kind">' + e.kind + '</span></a></li>';
        }).join('')
        : '<li class="c-subtle text-sm" style="padding:.75rem">Nothing by that name.</li>';
    }
    input.value = '';
    input.oninput = function () { active = 0; render(); };
    input.onkeydown = function (e) {
      if (e.key === 'ArrowDown') { active = Math.min(active + 1, shown.length - 1); render(); e.preventDefault(); }
      if (e.key === 'ArrowUp') { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
      if (e.key === 'Enter' && shown[active]) { location.href = shown[active].href; }
    };
    render();
    host.hidden = false;
    input.focus();
  }

  /* ------------------------------------------------------------------ *
   * Modals
   * ------------------------------------------------------------------ */
  let lastFocus = null;
  function openModal(id) {
    const host = document.getElementById(id);
    if (!host) return;
    lastFocus = document.activeElement;
    host.hidden = false;
    const first = $('input, select, textarea, button:not([data-modal-close])', host);
    if (first) first.focus();
  }
  function closeModals() {
    $$('.modal-host').forEach(function (h) { h.hidden = true; });
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  /* ------------------------------------------------------------------ *
   * Shared widgets
   * ------------------------------------------------------------------ */
  function sparkline(values, opts) {
    const w = 100, h = 28;
    const target = opts && opts.target;
    const max = Math.max.apply(null, values.concat(target || 0));
    const min = 0;
    const x = function (i) { return (i / (values.length - 1)) * w; };
    const y = function (v) { return h - ((v - min) / (max - min || 1)) * (h - 2) - 1; };
    const pts = values.map(function (v, i) { return x(i).toFixed(1) + ',' + y(v).toFixed(1); });
    return (
      '<svg class="sparkline" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" role="img" aria-label="' + ((opts && opts.label) || 'Trend') + '">' +
      (target ? '<line class="target" x1="0" x2="100" y1="' + y(target) + '" y2="' + y(target) + '" vector-effect="non-scaling-stroke"/>' : '') +
      '<polygon class="area" points="0,' + h + ' ' + pts.join(' ') + ' ' + w + ',' + h + '"/>' +
      '<polyline class="line" points="' + pts.join(' ') + '" vector-effect="non-scaling-stroke"/></svg>'
    );
  }

  function hydrate(root) {
    root = root || document;
    $$('[data-avatar]', root).forEach(function (a) {
      const name = a.dataset.avatar;
      a.classList.add('avatar');
      a.style.backgroundColor = avatarColour(name);
      a.setAttribute('aria-hidden', 'true');
      a.textContent = initialsOf(name);
    });
    $$('[data-icon]', root).forEach(function (i) {
      i.outerHTML = icon(i.dataset.icon, i.className);
    });
    $$('[data-spark]', root).forEach(function (s) {
      const values = s.dataset.spark.split(',').map(Number);
      s.innerHTML = sparkline(values, { target: s.dataset.target ? Number(s.dataset.target) : null, label: s.dataset.label });
    });
    $$('.toggle', root).forEach(function (t) {
      t.setAttribute('role', 'switch');
      if (!t.hasAttribute('aria-checked')) t.setAttribute('aria-checked', 'false');
    });
    observe(root);
  }

  /* Progress fills, count-ups and reveals start when they scroll into view. */
  let io = null;
  function observe(root) {
    const targets = $$('.progress-fill[data-w], [data-count-to], .reveal', root);
    if (!('IntersectionObserver' in window) || reduceMotion) {
      targets.forEach(play);
      return;
    }
    if (!io) {
      io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            play(entry.target);
            io.unobserve(entry.target);
          }
        });
      }, { rootMargin: '0px 0px -40px 0px' });
    }
    targets.forEach(function (t) { io.observe(t); });
  }
  function play(t) {
    if (t.classList.contains('progress-fill')) {
      t.style.width = Math.min(Number(t.dataset.w), 100) + '%';
    } else if (t.hasAttribute('data-count-to')) {
      countUp(t);
    } else {
      t.classList.add('is-in');
    }
  }
  function countUp(node) {
    const to = Number(node.dataset.countTo);
    const prefix = node.dataset.prefix || '';
    const suffix = node.dataset.suffix || '';
    if (reduceMotion) {
      node.textContent = prefix + to.toLocaleString('en-US') + suffix;
      return;
    }
    const start = performance.now();
    const dur = 1100;
    function frame(now) {
      const p = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      node.textContent = prefix + Math.round(to * eased).toLocaleString('en-US') + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /* Countdowns: data-ends-in="hours" from page load. */
  function startCountdowns() {
    const nodes = $$('[data-ends-in]');
    if (!nodes.length) return;
    const t0 = Date.now();
    nodes.forEach(function (n) { n._end = t0 + Number(n.dataset.endsIn) * 3600 * 1000; });
    function tick() {
      const now = Date.now();
      nodes.forEach(function (n) {
        let s = Math.max(0, Math.floor((n._end - now) / 1000));
        const d = Math.floor(s / 86400); s -= d * 86400;
        const h = Math.floor(s / 3600); s -= h * 3600;
        const m = Math.floor(s / 60); s -= m * 60;
        n.textContent = (d ? d + 'd ' : '') + h + 'h ' + String(m).padStart(2, '0') + 'm ' + String(s).padStart(2, '0') + 's';
      });
    }
    tick();
    setInterval(tick, 1000);
  }

  function switchTab(btn) {
    const group = btn.dataset.tabGroup;
    const name = btn.dataset.tab;
    $$('[data-tab-group="' + group + '"]').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.tab === name));
    });
    $$('[data-panel-group="' + group + '"]').forEach(function (p) {
      const on = p.dataset.panel === name;
      p.hidden = !on;
      if (on) {
        p.style.animation = 'none';
        void p.offsetWidth;
        p.style.animation = 'gg-reveal 320ms cubic-bezier(0.22, 1, 0.36, 1)';
        observe(p);
      }
    });
    document.dispatchEvent(new CustomEvent('gg:tab', { detail: { group: group, tab: name } }));
  }

  /* ------------------------------------------------------------------ *
   * Page transitions
   * ------------------------------------------------------------------ */
  const crossDocVT = 'onpagereveal' in window && CSS.supports && CSS.supports('view-transition-name: none');

  function isInternal(a) {
    if (!a || !a.href || a.target === '_blank' || a.hasAttribute('download')) return false;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return false;
    if (url.pathname === location.pathname && url.hash && url.search === location.search) return false;
    return /\.html$|\/$/.test(url.pathname);
  }

  /* ------------------------------------------------------------------ *
   * Events
   * ------------------------------------------------------------------ */
  function wire() {
    document.addEventListener('click', function (e) {
      const t = e.target;
      const closest = function (s) { return t.closest ? t.closest(s) : null; };

      const notIn = closest('[data-not-in-tour]');
      if (notIn) {
        e.preventDefault();
        toast(notIn.dataset.notInTour + ' is in the full app — it is not part of this tour.');
        return;
      }

      if (closest('[data-theme-toggle]')) {
        setTheme(currentTheme() === 'light' ? 'dark' : 'light');
        return;
      }
      const roleBtn = closest('.role-switch button');
      if (roleBtn) {
        setRole(roleBtn.dataset.role);
        toast('Now viewing as ' + (roleBtn.dataset.role === 'admin' ? 'an admin' : 'a' + (roleBtn.dataset.role === 'agent' ? 'n agent' : ' manager')) + ' — the sidebar shows what that role can open.');
        return;
      }
      if (closest('[data-guide-toggle]')) {
        if (window.innerWidth >= 1280) {
          document.body.classList.toggle('guide-collapsed');
          store('guide', document.body.classList.contains('guide-collapsed') ? 'off' : 'on');
        } else {
          document.body.classList.toggle('guide-open');
        }
        return;
      }
      const menuBtn = closest('[data-tour-menu]');
      const menu = $('.tour-menu');
      if (menuBtn) {
        menu.hidden = !menu.hidden;
        menuBtn.setAttribute('aria-expanded', String(!menu.hidden));
        return;
      }
      if (menu && !menu.hidden && !closest('.tour-menu')) {
        menu.hidden = true;
        $('[data-tour-menu]').setAttribute('aria-expanded', 'false');
      }

      const bellBtn = closest('[data-bell]');
      const pop = $('[data-bell-pop]');
      if (bellBtn) {
        pop.hidden = !pop.hidden;
        bellBtn.setAttribute('aria-expanded', String(!pop.hidden));
        return;
      }
      if (closest('[data-mark-read]')) {
        $$('.popover li.unread').forEach(function (li) { li.classList.remove('unread'); });
        const badge = $('.bell .badge');
        if (badge) badge.remove();
        toast('All caught up');
        return;
      }
      if (pop && !pop.hidden && !closest('[data-bell-pop]')) pop.hidden = true;

      if (closest('[data-drawer-open]')) { $('[data-drawer]').classList.add('is-open'); return; }
      if (closest('[data-drawer-close]')) { $('[data-drawer]').classList.remove('is-open'); return; }
      if (closest('[data-palette-open]')) { openPalette(); return; }
      if (closest('[data-palette-close]')) { $('[data-palette]').hidden = true; return; }

      const heading = closest('.nav-heading');
      if (heading) {
        heading.setAttribute('aria-expanded', String(heading.getAttribute('aria-expanded') !== 'true'));
        return;
      }

      const opener = closest('[data-modal-open]');
      if (opener) { e.preventDefault(); openModal(opener.dataset.modalOpen); return; }
      if (closest('[data-modal-close]') || (t.classList && t.classList.contains('scrim') && closest('.modal-host:not([data-palette])'))) {
        e.preventDefault();
        closeModals();
        return;
      }

      const tabBtn = closest('[data-tab-group]');
      if (tabBtn && tabBtn.dataset.tab) { switchTab(tabBtn); return; }

      const toggle = closest('.toggle');
      if (toggle) {
        toggle.setAttribute('aria-checked', String(toggle.getAttribute('aria-checked') !== 'true'));
        if (toggle.dataset.toast) toast(toggle.dataset.toast);
        return;
      }

      const toaster = closest('[data-toast]');
      if (toaster && toaster.tagName !== 'FORM') {
        e.preventDefault();
        toast(toaster.dataset.toast);
        return;
      }

      const a = closest('a');
      if (a && isInternal(a) && !crossDocVT && !e.metaKey && !e.ctrlKey && !e.shiftKey && !reduceMotion) {
        e.preventDefault();
        document.body.classList.add('is-leaving');
        setTimeout(function () { location.href = a.href; }, 150);
      }
    });

    document.addEventListener('submit', function (e) {
      const form = e.target;
      if (form.dataset.toast) {
        e.preventDefault();
        closeModals();
        toast(form.dataset.toast);
      }
    });

    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const host = $('[data-palette]');
        if (host && host.hidden) openPalette();
        else if (host) host.hidden = true;
      }
      if (e.key === 'Escape') {
        closeModals();
        const host = $('[data-palette]');
        if (host) host.hidden = true;
        document.body.classList.remove('guide-open');
        const d = $('[data-drawer]');
        if (d) d.classList.remove('is-open');
        const pop = $('[data-bell-pop]');
        if (pop) pop.hidden = true;
        const menu = $('.tour-menu');
        if (menu) menu.hidden = true;
      }
      if (e.target.matches && e.target.matches('input, textarea, select')) return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === 'ArrowRight') {
        const next = TOUR[stepIndex + 1];
        if (next) location.href = next.file;
      }
      if (e.key === 'ArrowLeft') {
        const prev = TOUR[stepIndex - 1];
        if (prev) location.href = prev.file;
      }
    });

    // Returning via the back button must not leave the page faded out.
    window.addEventListener('pageshow', function () { document.body.classList.remove('is-leaving'); });
  }

  /* ------------------------------------------------------------------ *
   * Public API for pages.js
   * ------------------------------------------------------------------ */
  window.GG = {
    icon: icon,
    avatar: avatar,
    avatarColour: avatarColour,
    initialsOf: initialsOf,
    hash: hash,
    fmt: fmt,
    toast: toast,
    sparkline: sparkline,
    hydrate: hydrate,
    observe: observe,
    openModal: openModal,
    closeModals: closeModals,
    switchTab: switchTab,
    buildHotspots: buildHotspots,
    movementFor: movementFor,
    reduceMotion: reduceMotion,
    data: { ORG: ORG, OFFICES: OFFICES, TEAMS: TEAMS, PEOPLE: PEOPLE, VIEWER: VIEWER, TOUR: TOUR },
    page: page,
    tab: tab,
  };

  function init() {
    if (stepIndex < 0) return;
    if (!crossDocVT) document.body.classList.add('no-vt');
    buildShell();
    hydrate(document);
    // Pages render their own content first (pages.js calls this when done);
    // the load event is a fallback so hotspots appear regardless.
    window.addEventListener('load', buildHotspots);
    startCountdowns();
    wire();
    document.title = TOUR[stepIndex].title + ' · GoalGetter demo';
    window.GG.ready = true;
    document.dispatchEvent(new CustomEvent('gg:ready'));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
