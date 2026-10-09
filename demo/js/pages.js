/*
 * GoalGetter demo — behaviour for individual pages.
 *
 * Runs after demo.js has built the shell. Each page's function renders the
 * data-heavy parts (tables, boards, walls) from the shared fake roster so
 * every page tells the same story about the same people.
 */
(function () {
  'use strict';

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  let GG;
  let D;

  /* ------------------------------------------------------------------ *
   * Data helpers
   * ------------------------------------------------------------------ */
  function agents() {
    return D.PEOPLE.filter(function (p) { return p.role === 'Agent'; });
  }
  function team(name) {
    return D.TEAMS.find(function (t) { return t.name === name; });
  }
  function mark(t, size) {
    const s = size ? 'width:' + size + 'px;height:' + size + 'px;' : '';
    return '<span class="mark" style="' + s + 'background:' + t.color + '">' + t.short + '</span>';
  }
  function movement(m) {
    if (m === null || m === undefined) return '<span class="text-xs c-subtle">new</span>';
    if (m === 0) return '<span class="text-xs c-subtle" title="No change">–</span>';
    const up = m > 0;
    return '<span class="text-xs num ' + (up ? 'c-success' : 'c-danger') + '" title="' + (up ? 'Up ' : 'Down ') + Math.abs(m) + ' since last period">' + (up ? '▲' : '▼') + ' ' + Math.abs(m) + '</span>';
  }
  function rankTone(r) {
    return r === 1 ? 'c-gold' : r === 2 ? 'c-silver' : r === 3 ? 'c-bronze' : 'c-subtle';
  }

  const BOARDS = {
    revenue: { name: 'Revenue', key: 'revenue', unit: 'currency', scope: 'people', who: 'Everyone' },
    calls: { name: 'Calls', key: 'calls', unit: 'count', scope: 'people', who: 'Everyone' },
    appts: { name: 'Appointments set', key: 'appts', unit: 'count', scope: 'people', who: 'Everyone' },
    deals: { name: 'Deals closed', key: 'deals', unit: 'count', scope: 'people', who: 'Everyone' },
    teams: { name: 'Team revenue', key: 'revenue', unit: 'currency', scope: 'teams', who: 'Teams' },
    offices: { name: 'Office revenue', key: 'revenue', unit: 'currency', scope: 'offices', who: 'Offices' },
  };

  function entriesFor(boardId) {
    const b = BOARDS[boardId];
    let rows;
    if (b.scope === 'people') {
      rows = agents().map(function (p) {
        return { id: p.name, name: p.name, sub: p.team, value: p[b.key] };
      });
    } else {
      const groups = {};
      agents().forEach(function (p) {
        const k = b.scope === 'teams' ? p.team : p.office;
        groups[k] = (groups[k] || 0) + p[b.key];
      });
      rows = Object.keys(groups).map(function (k) {
        return {
          id: k,
          name: k,
          sub: b.scope === 'teams' ? team(k).office : D.TEAMS.filter(function (t) { return t.office === k; }).length + ' teams',
          value: groups[k],
          team: b.scope === 'teams' ? team(k) : null,
          office: b.scope === 'offices',
        };
      });
    }
    rows.sort(function (a, c) { return c.value - a.value; });
    rows.forEach(function (r, i) {
      r.rank = i + 1;
      r.movement = GG.movementFor(r.name, boardId);
    });
    return rows;
  }

  function viewerIdFor(boardId) {
    const s = BOARDS[boardId].scope;
    return s === 'people' ? D.VIEWER : s === 'teams' ? 'Avengers' : 'Gotham';
  }

  function faceFor(row, size) {
    if (row.team) return mark(row.team, size === 'lg' ? 56 : 32);
    if (row.office) return '<span class="avatar" style="background:var(--gg-surface-raised);color:var(--gg-text-muted)">' + GG.icon('building', 'sm') + '</span>';
    return GG.avatar(row.name, size);
  }

  function lbRow(r, viewerId, pinned) {
    const isViewer = r.id === viewerId;
    return (
      '<tr class="lb-row' + (isViewer ? ' is-viewer' : '') + (pinned ? ' is-pinned' : '') + '" data-id="' + esc(r.id) + '">' +
      '<td><span class="num font-medium ' + rankTone(r.rank) + '">' + r.rank + '</span></td>' +
      '<td><div class="who">' + faceFor(r) + '<div style="min-width:0"><p class="truncate name">' + esc(r.name) +
      (isViewer ? '<span class="text-xs c-muted" style="margin-left:.5rem">' + (r.team ? 'your team' : r.office ? 'your office' : 'you') + '</span>' : '') +
      '</p><p class="truncate sub">' + esc(r.sub) + '</p></div></div></td>' +
      '<td class="right c-content num">' + GG.fmt(r.value, r.unit) + '</td>' +
      '<td class="right">' + movement(r.movement) + '</td></tr>'
    );
  }

  /* ------------------------------------------------------------------ *
   * Leaderboards
   * ------------------------------------------------------------------ */
  function leaderboards() {
    const params = new URLSearchParams(location.search);
    let boardId = BOARDS[params.get('board')] ? params.get('board') : 'revenue';
    let rows = [];
    const list = $('#board-cards');
    const wrap = $('#lb-table');

    function renderCards() {
      list.innerHTML = Object.keys(BOARDS).map(function (id) {
        const b = BOARDS[id];
        const top = entriesFor(id)[0];
        const me = entriesFor(id).find(function (r) { return r.id === viewerIdFor(id); });
        return (
          '<button type="button" class="card p-4 board-card' + (id === boardId ? ' is-on' : '') + '" data-board="' + id + '">' +
          '<div class="row-between"><span class="c-content font-medium">' + b.name + '</span><span class="pill">' + b.who + '</span></div>' +
          '<p class="text-xs c-subtle mt-1">October · always live</p>' +
          '<div class="row mt-3" style="gap:.5rem">' + faceFor(top) +
          '<div class="grow" style="text-align:left"><p class="text-sm c-content truncate">' + esc(top.name) + '</p>' +
          '<p class="text-xs c-subtle">' + GG.fmt(top.value, b.unit) + ' · leading</p></div>' +
          '<span class="text-xs c-muted">' + (b.scope === 'people' ? 'You' : b.scope === 'teams' ? 'Avengers' : 'Gotham') + ' <strong class="c-content num">#' + me.rank + '</strong></span></div>' +
          '</button>'
        );
      }).join('');
    }

    function renderTable(flip) {
      const b = BOARDS[boardId];
      const viewerId = viewerIdFor(boardId);
      rows.forEach(function (r) { r.unit = b.unit; });
      const top = rows.slice(0, 10);
      const me = rows.find(function (r) { return r.id === viewerId; });
      const pinned = me && me.rank > 10 ? me : null;

      const before = {};
      if (flip) $$('tr[data-id]', wrap).forEach(function (tr) { before[tr.dataset.id] = tr.getBoundingClientRect().top; });

      wrap.innerHTML =
        '<div class="table-wrap"><table class="gg"><thead><tr><th style="width:3rem">#</th><th>Name</th><th class="right">Score</th><th class="right" style="width:5rem">Move</th></tr></thead><tbody>' +
        top.map(function (r) { return lbRow(r, viewerId); }).join('') +
        (pinned ? lbRow(pinned, viewerId, true) : '') +
        '</tbody></table>' +
        (rows.length > top.length ? '<p class="table-foot">Showing ' + top.length + ' of ' + rows.length + '.</p>' : '') +
        '</div>';

      $('#board-title').textContent = b.name + ' · October';
      $('#board-meta').textContent = b.who + ' · ' + (b.unit === 'currency' ? 'Sum of revenue' : 'Count') + ' · resets monthly';

      if (flip && !GG.reduceMotion) {
        $$('tr[data-id]', wrap).forEach(function (tr) {
          const was = before[tr.dataset.id];
          if (was === undefined) return;
          const now = tr.getBoundingClientRect().top;
          const dy = was - now;
          if (Math.abs(dy) < 1) return;
          tr.style.transform = 'translateY(' + dy + 'px)';
          tr.style.transition = 'none';
          tr.classList.add(dy > 0 ? 'flash-up' : 'flash-down');
          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              tr.style.transition = 'transform 600ms cubic-bezier(0.22, 1, 0.36, 1), background-color 1200ms ease-out';
              tr.style.transform = '';
              setTimeout(function () { tr.classList.remove('flash-up', 'flash-down'); }, 900);
            });
          });
        });
      }
    }

    function load(id) {
      boardId = id;
      rows = entriesFor(id);
      renderCards();
      renderTable(false);
    }

    function simulate() {
      const b = BOARDS[boardId];
      const bump = b.key === 'revenue' ? [1800, 7500] : b.key === 'calls' ? [6, 28] : [1, 3];
      const oldRank = {};
      rows.forEach(function (r) { oldRank[r.id] = r.rank; });
      const picks = rows.slice().sort(function () { return Math.random() - 0.5; }).slice(0, b.scope === 'people' ? 5 : 2);
      const me = rows.find(function (r) { return r.id === viewerIdFor(boardId); });
      if (me && picks.indexOf(me) < 0 && Math.random() < 0.7) picks.push(me);
      picks.forEach(function (r) {
        const mult = b.scope === 'people' ? 1 : 3;
        r.value += Math.round((bump[0] + Math.random() * (bump[1] - bump[0])) * mult);
      });
      rows.sort(function (a, c) { return c.value - a.value; });
      let moved = null;
      rows.forEach(function (r, i) {
        r.rank = i + 1;
        const delta = oldRank[r.id] - r.rank;
        r.movement = delta;
        if (delta > 0 && (!moved || delta > moved.delta)) moved = { name: r.name, delta: delta, rank: r.rank };
      });
      renderTable(true);
      $('#lb-live').textContent = 'Updated just now';
      if (moved) GG.toast(moved.name + ' moved up ' + moved.delta + ' to #' + moved.rank);
    }

    list.addEventListener('click', function (e) {
      const btn = e.target.closest('[data-board]');
      if (!btn) return;
      load(btn.dataset.board);
      history.replaceState(null, '', '?board=' + btn.dataset.board);
    });
    $('#simulate').addEventListener('click', simulate);

    let auto = null;
    $('#auto').addEventListener('click', function () {
      const on = this.getAttribute('aria-checked') === 'true';
      if (on) {
        auto = setInterval(simulate, 4500);
        simulate();
      } else {
        clearInterval(auto);
      }
    });

    load(boardId);
  }

  /* ------------------------------------------------------------------ *
   * Goals — live preview in the New goal form
   * ------------------------------------------------------------------ */
  function goals() {
    const form = $('#goal-form');
    if (!form) return;
    function update() {
      const metric = $('#g-metric').value;
      const target = Number(($('#g-target').value || '0').replace(/[^0-9.]/g, '')) || 0;
      const current = { Revenue: 48250, Calls: 412, 'Appointments set': 31, 'Deals closed': 14 }[metric];
      const money = metric === 'Revenue';
      const pct = target ? Math.round((current / target) * 100) : 0;
      const f = function (v) { return money ? '$' + Math.round(v).toLocaleString('en-US') : Math.round(v).toLocaleString('en-US'); };
      $('#gp-title').textContent = ($('#g-name').value || metric) + ' · ' + $('#g-who').value;
      $('#gp-values').innerHTML = f(current) + '<span class="c-muted"> of </span>' + (target ? f(target) : '—');
      $('#gp-pct').textContent = pct + '%';
      $('#gp-pct').className = 'num ' + (pct >= 100 ? 'c-success' : 'c-muted');
      const fill = $('#gp-fill');
      fill.style.width = Math.min(pct, 100) + '%';
      fill.classList.toggle('hit', pct >= 100);
      const status = pct >= 100 ? ['success', 'Hit'] : pct >= 66 ? ['success', 'Ahead'] : pct >= 55 ? ['', 'On track'] : ['warning', 'Behind'];
      $('#gp-status').className = 'pill ' + status[0];
      $('#gp-status').textContent = status[1];
      $('#gp-needs').textContent = target > current ? '· needs ' + f(target - current) + ' more' : '';
    }
    $$('input, select', form).forEach(function (i) { i.addEventListener('input', update); });
    $$('[data-g-target]').forEach(function (b) {
      b.addEventListener('click', function () {
        $('#g-target').value = b.dataset.gTarget;
        update();
      });
    });
    update();
  }

  /* ------------------------------------------------------------------ *
   * Competitions — the race fills in when it scrolls into view
   * ------------------------------------------------------------------ */
  function competitions() {
    const race = $('#race-lanes');
    if (race) {
      const field = agents().slice().sort(function (a, b) { return b.revenue - a.revenue; }).slice(0, 6);
      const target = 80000;
      race.innerHTML = field.map(function (p, i) {
        const pct = Math.min((p.revenue / target) * 100, 100);
        return (
          '<li class="race-row' + (p.name === D.VIEWER ? ' is-viewer' : '') + '">' +
          '<span class="num c-subtle ' + rankTone(i + 1) + '" style="width:1.25rem">' + (i + 1) + '</span>' +
          GG.avatar(p.name, 'xs') +
          '<span class="truncate text-sm" style="width:9rem">' + p.name + '</span>' +
          '<div class="progress grow" style="margin:0"><div class="progress-fill" data-w="' + pct.toFixed(1) + '"' + (i === 0 ? ' style="background:var(--gg-gold)"' : '') + '></div></div>' +
          '<span class="num text-sm c-muted" style="width:5rem;text-align:right">' + GG.fmt(p.revenue, 'currency') + '</span></li>'
        );
      }).join('') +
        '<li class="race-row is-viewer"><span class="num c-subtle" style="width:1.25rem">12</span>' + GG.avatar(D.VIEWER, 'xs') +
        '<span class="truncate text-sm" style="width:9rem">Peter Parker <span class="text-xs c-muted">you</span></span>' +
        '<div class="progress grow" style="margin:0"><div class="progress-fill" data-w="60.3"></div></div>' +
        '<span class="num text-sm c-muted" style="width:5rem;text-align:right">$48,250</span></li>';
      GG.observe(race);
    }
  }

  /* ------------------------------------------------------------------ *
   * Announcements — filters and reactions
   * ------------------------------------------------------------------ */
  function announcements() {
    const who = $('#f-who');
    const what = $('#f-what');
    function apply() {
      const q = who.value.trim().toLowerCase();
      const k = what.value;
      let shown = 0;
      $$('#feed > li').forEach(function (li) {
        const ok = (!k || li.dataset.kind === k) && (!q || li.textContent.toLowerCase().indexOf(q) >= 0);
        li.hidden = !ok;
        if (ok) shown += 1;
      });
      $('#feed-none').hidden = shown > 0;
    }
    if (who) {
      who.addEventListener('input', apply);
      what.addEventListener('change', apply);
    }
    document.addEventListener('click', function (e) {
      const r = e.target.closest('.react');
      if (!r) return;
      const on = r.getAttribute('aria-pressed') === 'true';
      r.setAttribute('aria-pressed', String(!on));
      const n = $('.n', r);
      n.textContent = Number(n.textContent) + (on ? -1 : 1);
      if (!on && !GG.reduceMotion) {
        r.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.25)' }, { transform: 'scale(1)' }], { duration: 300, easing: 'ease-out' });
      }
    });
  }

  /* ------------------------------------------------------------------ *
   * Users — a filterable roster
   * ------------------------------------------------------------------ */
  function users() {
    const body = $('#users-body');
    const seen = ['Just now', '4 min ago', '18 min ago', '1 h ago', '3 h ago', 'Yesterday', '2 days ago'];
    const invited = { 'Billy Batson': true, 'Derwin James': true };
    const q = $('#u-q');
    const role = $('#u-role');
    const teamSel = $('#u-team');
    const office = $('#u-office');

    teamSel.innerHTML = '<option value="">Every team</option>' + D.TEAMS.map(function (t) { return '<option>' + t.name + '</option>'; }).join('') + '<option value="none">No team</option>';
    office.innerHTML = '<option value="">Every office</option>' + D.OFFICES.map(function (o) { return '<option>' + o.name + '</option>'; }).join('');

    const pre = new URLSearchParams(location.search).get('q');
    if (pre) q.value = pre;

    const people = D.PEOPLE.slice().sort(function (a, b) {
      const order = { Admin: 0, Manager: 1, Agent: 2 };
      return order[a.role] - order[b.role] || a.name.localeCompare(b.name);
    });

    function render() {
      const term = q.value.trim().toLowerCase();
      const shown = people.filter(function (p) {
        return (!term || (p.name + ' ' + p.email).toLowerCase().indexOf(term) >= 0) &&
          (!role.value || p.role === role.value) &&
          (!teamSel.value || (teamSel.value === 'none' ? !p.team : p.team === teamSel.value)) &&
          (!office.value || p.office === office.value);
      });
      body.innerHTML = shown.map(function (p) {
        const t = p.team ? team(p.team) : null;
        const inv = invited[p.name];
        return (
          '<tr>' +
          '<td data-primary><div class="who">' + GG.avatar(p.name) + '<div style="min-width:0"><p class="name truncate">' + p.name +
          (p.name === D.VIEWER ? ' <span class="text-xs c-muted">you</span>' : '') + '</p><p class="sub truncate">' + p.email + '</p></div></div></td>' +
          '<td data-label="Role"><span class="pill' + (p.role === 'Admin' ? ' brand' : '') + '">' + p.role + '</span></td>' +
          '<td data-label="Team">' + (t ? '<span class="row" style="gap:.5rem">' + mark(t, 20) + '<span class="truncate">' + t.name + '</span></span>' : '<span class="c-subtle">—</span>') + '</td>' +
          '<td data-label="Office" class="c-muted">' + p.office + '</td>' +
          '<td data-label="Status">' + (inv ? '<span class="pill warning">Invited</span>' : '<span class="row text-xs c-muted" style="gap:.4rem"><span class="dot success"></span>Active</span>') + '</td>' +
          '<td data-label="Last seen" class="c-subtle text-xs">' + (inv ? 'Not yet' : seen[GG.hash(p.name) % seen.length]) + '</td>' +
          '<td data-actions class="right"><button class="icon-btn" aria-label="Edit ' + p.name + '" data-toast="Opens ' + p.name + '’s profile, role and team">' + GG.icon('pencil', 'sm') + '</button></td>' +
          '</tr>'
        );
      }).join('') || '<tr><td colspan="7" class="c-muted" style="padding:2rem;text-align:center">Nobody matches those filters.</td></tr>';
      $('#users-count').textContent = shown.length === people.length ? people.length + ' people' : shown.length + ' of ' + people.length + ' people';
    }
    [q, role, teamSel, office].forEach(function (c) { c.addEventListener('input', render); });
    $('#u-clear').addEventListener('click', function () {
      q.value = ''; role.value = ''; teamSel.value = ''; office.value = '';
      render();
    });
    render();
  }

  /* ------------------------------------------------------------------ *
   * Teams — rows that open to show members
   * ------------------------------------------------------------------ */
  function teams() {
    const list = $('#team-list');
    list.innerHTML = D.TEAMS.map(function (t, i) {
      const members = agents().filter(function (p) { return p.team === t.name; });
      const total = members.reduce(function (s, p) { return s + p.revenue; }, 0);
      return (
        '<li class="team-row">' +
        '<div class="team-grid">' +
        '<span class="row" style="gap:.5rem;min-width:0">' + mark(t) + '<span class="truncate c-content">' + t.name + '</span>' +
        (i === 1 ? '<span class="pill">from Microsoft Teams</span>' : '') + '</span>' +
        '<button type="button" class="members-btn text-caption c-subtle" aria-expanded="false">' +
        '<span class="avatar-stack">' + members.slice(0, 3).map(function (m) { return GG.avatar(m.name, 'xs'); }).join('') + '</span>' +
        members.length + ' agents' + GG.icon('chevron', 'xs') + '</button>' +
        '<select class="select office-sel" aria-label="Office for ' + t.name + '">' +
        D.OFFICES.map(function (o) { return '<option' + (o.name === t.office ? ' selected' : '') + '>' + o.name + '</option>'; }).join('') + '</select>' +
        '<span class="row" style="gap:.25rem;justify-content:flex-end">' +
        '<button class="icon-btn" aria-label="Edit ' + t.name + '" data-modal-open="team-modal">' + GG.icon('pencil', 'sm') + '</button>' +
        '<button class="icon-btn" aria-label="Archive ' + t.name + '" data-toast="' + t.name + ' archived — its history stays on every board">' + GG.icon('archive', 'sm') + '</button>' +
        '</span></div>' +
        '<div class="members" hidden><div class="members-inner">' +
        '<div class="row text-xs c-subtle" style="justify-content:space-between"><span>Manager</span><span class="num">Team revenue · October ' + GG.fmt(total, 'currency') + '</span></div>' +
        '<div class="row mt-2" style="gap:.5rem">' + GG.avatar(t.manager, 'xs') + '<span class="text-sm">' + t.manager + '</span><span class="pill">Manager</span></div>' +
        '<p class="text-xs c-subtle mt-3">Agents</p><ul class="member-grid">' +
        members.map(function (m) {
          return '<li class="row" style="gap:.5rem">' + GG.avatar(m.name, 'xs') + '<span class="text-sm truncate grow">' + m.name + '</span><span class="text-xs c-subtle num">' + GG.fmt(m.revenue, 'currency') + '</span></li>';
        }).join('') + '</ul></div></div>' +
        '</li>'
      );
    }).join('');

    list.addEventListener('click', function (e) {
      const btn = e.target.closest('.members-btn');
      if (!btn) return;
      const panel = btn.closest('.team-row').querySelector('.members');
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      panel.hidden = open;
      if (!open && !GG.reduceMotion) {
        panel.animate([{ opacity: 0, transform: 'translateY(-4px)' }, { opacity: 1, transform: 'none' }], { duration: 220, easing: 'ease-out' });
      }
    });
    list.addEventListener('change', function (e) {
      if (e.target.classList.contains('office-sel')) GG.toast('Moved to ' + e.target.value + ' — its boards follow');
    });
    const first = $('.members-btn', list);
    if (first) first.click();
  }

  /* ------------------------------------------------------------------ *
   * Offices — a bar per office
   * ------------------------------------------------------------------ */
  function offices() {
    const bars = $('#office-bars');
    if (!bars) return;
    const rows = entriesFor('offices');
    const max = rows[0].value;
    bars.innerHTML = rows.map(function (r) {
      return (
        '<li><div class="row-between text-sm"><span class="row" style="gap:.5rem"><span class="num font-medium ' + rankTone(r.rank) + '">' + r.rank + '</span>' + r.name + '</span>' +
        '<span class="num c-muted">' + GG.fmt(r.value, 'currency') + '</span></div>' +
        '<div class="progress"><div class="progress-fill" data-w="' + ((r.value / max) * 100).toFixed(1) + '"></div></div></li>'
      );
    }).join('');
    GG.observe(bars);
  }

  /* ------------------------------------------------------------------ *
   * The wall: scenes shared by the TV page, the channel preview and the
   * appearance preview.
   * ------------------------------------------------------------------ */
  const Wall = (function () {
    function face(name, cls) {
      return '<span class="' + (cls || 'face') + '" style="background:' + GG.avatarColour(name) + '">' + GG.initialsOf(name) + '</span>';
    }
    function top(key, n) {
      return agents().slice().sort(function (a, b) { return b[key] - a[key]; }).slice(0, n);
    }

    const SCENES = {
      podium: function () {
        const t = top('revenue', 8);
        const place = function (p, i, cls, d) {
          return '<div class="place ' + cls + ' anim" style="--d:' + d + 'ms">' + face(p.name) +
            '<div class="who truncate">' + p.name + '</div><div class="val">' + GG.fmt(p.revenue, 'currency') + '</div>' +
            '<div class="block" style="--d:' + (d + 150) + 'ms">' + (i + 1) + '</div></div>';
        };
        return (
          '<div class="scene-title anim">Revenue · October</div><div class="scene-sub anim" style="--d:80ms">Everyone · always live</div>' +
          '<div class="podium-wrap"><div class="podium">' + place(t[1], 1, 'p2', 250) + place(t[0], 0, 'p1', 100) + place(t[2], 2, 'p3', 400) + '</div>' +
          '<ul class="rest">' + t.slice(3).map(function (p, i) {
            return '<li class="wall-panel anim" style="--d:' + (450 + i * 90) + 'ms"><span class="r">' + (i + 4) + '</span>' + face(p.name, 'f') +
              '<span class="n">' + p.name + '</span><span class="v">' + GG.fmt(p.revenue, 'currency') + '</span>' +
              '<span class="mv">' + movement(GG.movementFor(p.name, 'revenue')) + '</span></li>';
          }).join('') + '</ul></div>'
        );
      },
      race: function () {
        const t = top('calls', 6);
        return (
          '<div class="scene-title anim">Halloween Call Blitz</div><div class="scene-sub anim" style="--d:80ms">First to 500 calls · ends Friday</div>' +
          '<div class="race">' + t.map(function (p, i) {
            const c = GG.avatarColour(p.name);
            return '<div class="lane anim' + (i === 0 ? ' lead' : '') + '" style="--d:' + (150 + i * 80) + 'ms"><span class="nm">' + p.name + '</span>' +
              '<div class="track"><span class="trail" style="--c:' + c + '" data-pct="' + (p.calls / 500) * 100 + '"></span>' +
              '<span class="runner" style="--c:' + c + '" data-pct="' + (p.calls / 500) * 100 + '">' + GG.initialsOf(p.name) + '</span>' +
              '<span class="finish chequered"></span></div><span class="val">' + p.calls + ' calls</span></div>';
          }).join('') + '</div>'
        );
      },
      gauge: function () {
        return (
          '<div class="scene-title anim">Q4 company revenue</div><div class="scene-sub anim" style="--d:80ms">Stark Industries · October to December</div>' +
          '<div class="gauge-wrap"><div class="gauge anim" style="--d:150ms"><svg viewBox="0 0 100 100"><defs><linearGradient id="gauge-grad" x1="0" x2="1"><stop offset="0" stop-color="#6366f1"/><stop offset="1" stop-color="#34d399"/></linearGradient></defs>' +
          '<circle class="track" cx="50" cy="50" r="42" fill="none" stroke-width="9"/>' +
          '<circle class="arc" cx="50" cy="50" r="42" fill="none" stroke-width="9" data-pct="68"/>' +
          '</svg><div class="center"><b>68%</b><span>$2.86M of $4.2M</span></div></div>' +
          '<div class="gauge-facts">' +
          '<div class="fact wall-panel anim" style="--d:250ms"><div class="k">On pace for</div><div class="v" style="color:var(--gg-success)">$4.41M</div></div>' +
          '<div class="fact wall-panel anim" style="--d:350ms"><div class="k">Expected by today</div><div class="v">61%</div></div>' +
          '<div class="fact wall-panel anim" style="--d:450ms"><div class="k">Top office</div><div class="v">Star City</div></div>' +
          '</div></div>'
        );
      },
      h2h: function () {
        return (
          '<div class="scene-title anim">Avengers vs. Justice League</div><div class="scene-sub anim" style="--d:80ms">Deals closed · ends tonight</div>' +
          '<div class="h2h"><div class="side anim" style="--d:150ms"><div class="tm" style="background:#b91c1c">AVG</div><div class="tn">Avengers</div><div class="sc">52</div></div>' +
          '<div class="vs anim" style="--d:250ms">VS</div>' +
          '<div class="side anim" style="--d:350ms"><div class="tm" style="background:#1d4ed8">JL</div><div class="tn">Justice League</div><div class="sc">49</div></div>' +
          '<div class="h2h-bar anim" style="--d:450ms"><span style="flex-grow:52;background:#b91c1c"></span><span style="flex-grow:49;background:#1d4ed8"></span></div></div>'
        );
      },
      announce: function () {
        return (
          '<div class="announce"><span class="tag anim">Announcement</span>' +
          '<h3 class="anim" style="--d:120ms">Town hall Friday at 3 PM</h3>' +
          '<p class="anim" style="--d:240ms">Tony is announcing the Q4 incentive trip. Pizza in the Gotham break room — remote folks, the link is in your inbox.</p></div>'
        );
      },
    };

    function trophySvg() {
      return (
        '<svg viewBox="0 0 120 120"><defs><linearGradient id="tg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fde68a"/><stop offset=".5" stop-color="#fbbf24"/><stop offset="1" stop-color="#b45309"/></linearGradient></defs>' +
        '<path d="M34 18h52v26c0 16-11.6 28-26 28S34 60 34 44V18Z" fill="url(#tg)"/>' +
        '<path d="M34 26H18v8c0 10 8 18 18 18M86 26h16v8c0 10-8 18-18 18" fill="none" stroke="url(#tg)" stroke-width="6" stroke-linecap="round"/>' +
        '<rect x="54" y="72" width="12" height="16" fill="#d97706"/><rect x="38" y="88" width="44" height="12" rx="3" fill="url(#tg)"/>' +
        '<path d="M60 30l3.5 7.2 7.9 1.1-5.7 5.6 1.3 7.8L60 48l-7 3.7 1.3-7.8-5.7-5.6 7.9-1.1Z" fill="#fff" opacity=".9"/></svg>'
      );
    }

    function confetti(n) {
      const colours = ['#fbbf24', '#34d399', '#6366f1', '#f472b6', '#38bdf8', '#f87171'];
      let html = '';
      for (let i = 0; i < n; i += 1) {
        const angle = Math.random() * Math.PI * 2;
        const dist = 12 + Math.random() * 26;
        html += '<i class="confetti" style="background:' + colours[i % colours.length] +
          ';--dx:' + (Math.cos(angle) * dist).toFixed(1) + 'em;--dy:' + (Math.sin(angle) * dist * 0.7 + 14).toFixed(1) +
          'em;--rot:' + Math.round(Math.random() * 720 - 360) + 'deg;--t:' + (1.8 + Math.random() * 1.6).toFixed(2) + 's;--delay:' + (0.6 + Math.random() * 0.5).toFixed(2) + 's"></i>';
      }
      return html;
    }

    function mount(stage, opts) {
      const names = opts.scenes;
      const slideMs = opts.slideMs || 7000;
      stage.classList.add('wall');
      stage.style.setProperty('--slide-ms', slideMs + 'ms');
      stage.innerHTML =
        '<div class="wall-bg"></div>' +
        (opts.chrome === false ? '' :
          '<div class="wall-chrome"><span class="org-logo"><span class="arc"></span>Stark</span><span class="chan">' + (opts.channel || 'Sales floor') + '</span><span class="clock"></span></div>') +
        names.map(function (n) { return '<section class="scene" data-scene="' + n + '">' + SCENES[n]() + '</section>'; }).join('') +
        '<div class="wall-dots">' + names.map(function () { return '<span><i></i></span>'; }).join('') + '</div>' +
        '<div class="overtake" aria-live="polite"></div>' +
        '<div class="celebrate" aria-live="polite"></div>';

      let i = -1;
      let timer = null;
      let paused = false;
      const scenes = $$('.scene', stage);
      const dots = $$('.wall-dots span', stage);

      function enter(scene) {
        $$('.runner, .trail', scene).forEach(function (r) {
          r.style.transition = 'none';
          if (r.classList.contains('runner')) r.style.left = '0';
          else r.style.width = '0';
        });
        const arc = $('.arc', scene);
        if (arc) { arc.style.transition = 'none'; arc.style.strokeDasharray = '0 999'; }
        void scene.offsetWidth;
        setTimeout(function () {
          $$('.runner, .trail', scene).forEach(function (r) {
            r.style.transition = '';
            const pct = Math.min(Number(r.dataset.pct), 100);
            if (r.classList.contains('runner')) r.style.left = 'calc(' + pct + '% * 0.86)';
            else r.style.width = 'calc(' + pct + '% * 0.86 + 1.1em)';
          });
          if (arc) {
            arc.style.transition = '';
            const len = 2 * Math.PI * 42;
            arc.style.strokeDasharray = (len * Number(arc.dataset.pct) / 100).toFixed(1) + ' 999';
          }
        }, 350);
      }

      function show(n) {
        i = (n + scenes.length) % scenes.length;
        scenes.forEach(function (s, k) { s.classList.toggle('on', k === i); });
        dots.forEach(function (d, k) {
          d.classList.toggle('on', k === i);
          d.classList.toggle('done', k < i);
          const bar = $('i', d);
          bar.style.animation = 'none';
          void bar.offsetWidth;
          bar.style.animation = '';
        });
        enter(scenes[i]);
        if (opts.onScene) opts.onScene(names[i]);
        schedule();
      }
      function schedule() {
        clearTimeout(timer);
        if (!paused) timer = setTimeout(function () { show(i + 1); }, slideMs);
      }
      function tickClock() {
        const c = $('.clock', stage);
        if (c) c.textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
      }
      tickClock();
      setInterval(tickClock, 15000);

      function celebrate(name, what, value) {
        const host = $('.celebrate', stage);
        host.innerHTML =
          '<div class="inner"><div class="glow"></div>' + confetti(44) +
          '<div class="trophy">' + trophySvg() + '<span class="shine"></span></div>' +
          '<div class="who">' + face(name) + '<h3>' + name + '</h3></div>' +
          '<p>' + what + '</p><div class="big">' + value + '</div></div>';
        void host.offsetWidth;
        host.classList.add('show');
        const wasPaused = paused;
        paused = true;
        clearTimeout(timer);
        setTimeout(function () {
          host.classList.remove('show');
          paused = wasPaused;
          schedule();
        }, 6500);
      }

      function overtake(text) {
        const b = $('.overtake', stage);
        b.innerHTML = '▲ ' + text;
        b.classList.add('show');
        setTimeout(function () { b.classList.remove('show'); }, 3600);
      }

      show(0);
      return {
        next: function () { show(i + 1); },
        prev: function () { show(i - 1); },
        go: function (n) { show(n); },
        toggle: function () {
          paused = !paused;
          stage.classList.toggle('paused', paused);
          if (paused) clearTimeout(timer); else schedule();
          return paused;
        },
        celebrate: celebrate,
        overtake: overtake,
      };
    }

    return { mount: mount };
  })();

  function channels() {
    const stage = $('#channel-stage');
    if (stage) {
      const wall = Wall.mount(stage, { scenes: ['podium', 'race', 'gauge', 'h2h', 'announce'], slideMs: 5000, channel: 'Sales floor' });
      $$('[data-slide]').forEach(function (b) {
        b.addEventListener('click', function () { wall.go(Number(b.dataset.slide)); });
      });
    }
    const code = $('#pair-code');
    if (code) {
      $('[data-modal-open="pair-modal"]').addEventListener('click', function () {
        const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
        let s = '';
        for (let k = 0; k < 6; k += 1) s += chars[Math.floor(Math.random() * chars.length)];
        code.textContent = s.slice(0, 3) + ' ' + s.slice(3);
      });
    }
  }

  function tvWall() {
    const stage = $('#wall-stage');
    const names = ['podium', 'race', 'gauge', 'h2h', 'announce'];
    let overtaken = false;
    const wall = Wall.mount(stage, {
      scenes: names,
      slideMs: 8000,
      channel: 'Sales floor · Gotham',
      onScene: function (n) {
        $$('[data-scene-btn]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.sceneBtn === n)); });
        if (n === 'podium' && !overtaken) {
          overtaken = true;
          setTimeout(function () { wall.overtake('Shohei Ohtani overtakes LaDainian Tomlinson for 1st'); }, 2600);
        }
      },
    });
    $('#w-prev').addEventListener('click', wall.prev);
    $('#w-next').addEventListener('click', wall.next);
    $('#w-pause').addEventListener('click', function () {
      const paused = wall.toggle();
      this.innerHTML = GG.icon(paused ? 'play' : 'pause');
      this.setAttribute('aria-label', paused ? 'Resume rotation' : 'Pause rotation');
    });
    $('#w-celebrate').addEventListener('click', function () {
      const wins = [
        ['Mike Trout', 'hit Revenue · October', '$69,400'],
        ['Peter Parker', 'hit Calls · October', '412 calls'],
        ['Kara Danvers', 'won the Fall Classic', '1st of 26'],
      ];
      const w = wins[Math.floor(Math.random() * wins.length)];
      wall.celebrate(w[0], w[1], w[2]);
    });
    $$('[data-scene-btn]').forEach(function (b) {
      b.addEventListener('click', function () { wall.go(names.indexOf(b.dataset.sceneBtn)); });
    });
    $('#w-full').addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (stage.requestFullscreen) stage.requestFullscreen();
    });
    setTimeout(function () {
      if (!sessionStorage.getItem('gg-celebrated')) {
        sessionStorage.setItem('gg-celebrated', '1');
        wall.celebrate('Mike Trout', 'hit Revenue · October', '$69,400');
      }
    }, 2500);
  }

  /* ------------------------------------------------------------------ *
   * Admin — tabs from the URL, live brand colour, inbox fixes
   * ------------------------------------------------------------------ */
  function admin() {
    const want = GG.tab && $('[data-tab-group="admin"][data-tab="' + GG.tab + '"]');
    if (want) GG.switchTab(want);

    document.addEventListener('gg:tab', function (e) {
      if (e.detail.group !== 'admin') return;
      const url = e.detail.tab === 'settings' ? location.pathname : '?tab=' + e.detail.tab;
      history.replaceState(null, '', url);
      $$('.nav-item[aria-current]').forEach(function (a) { a.removeAttribute('aria-current'); });
      const map = { settings: 'admin.html', appearance: 'admin.html?tab=appearance', inbox: 'admin.html?tab=inbox', assets: 'admin.html?tab=assets' };
      $$('.nav-item[href="' + map[e.detail.tab] + '"]').forEach(function (a) { a.setAttribute('aria-current', 'page'); });
    });

    $$('[data-brand]').forEach(function (sw) {
      sw.addEventListener('click', function () {
        const [base, hover, subtle] = sw.dataset.brand.split(',');
        const root = document.documentElement.style;
        root.setProperty('--gg-brand', base);
        root.setProperty('--gg-brand-hover', hover);
        root.setProperty('--gg-brand-subtle', subtle);
        $$('[data-brand]').forEach(function (s) { s.setAttribute('aria-pressed', String(s === sw)); });
        GG.toast('Brand colour applied to the whole app — try another');
      });
    });
    const reset = $('#brand-reset');
    if (reset) {
      reset.addEventListener('click', function () {
        ['--gg-brand', '--gg-brand-hover', '--gg-brand-subtle'].forEach(function (p) { document.documentElement.style.removeProperty(p); });
        $$('[data-brand]').forEach(function (s, k) { s.setAttribute('aria-pressed', String(k === 0)); });
      });
    }

    const prev = $('#appearance-stage');
    if (prev) Wall.mount(prev, { scenes: ['podium', 'gauge'], slideMs: 6000, channel: 'Preview' });

    $$('[data-bg]').forEach(function (b) {
      b.addEventListener('click', function () {
        const bg = $('#appearance-stage .wall-bg');
        if (bg) bg.style.background = b.dataset.bg;
        $$('[data-bg]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      });
    });

    document.addEventListener('click', function (e) {
      const fix = e.target.closest('[data-fix]');
      if (!fix) return;
      e.preventDefault();
      const li = fix.closest('li');
      GG.toast(fix.dataset.fix);
      const done = function () {
        li.remove();
        const left = $$('#inbox-list > li').length;
        $$('.nav-item .count').forEach(function (c) {
          if (left) c.textContent = left; else c.remove();
        });
        const badge = $('#inbox-tab-count');
        if (badge) badge.textContent = left || '';
        if (!left) $('#inbox-empty').hidden = false;
      };
      if (GG.reduceMotion) done();
      else li.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateX(24px)' }], { duration: 260, easing: 'ease-in' }).onfinish = done;
    });

    $$('[data-play-sound]').forEach(function (b) {
      b.addEventListener('click', function () {
        try {
          const ctx = new (window.AudioContext || window.webkitAudioContext)();
          const notes = b.dataset.playSound === 'fanfare' ? [523, 659, 784, 1047] : [784, 988];
          notes.forEach(function (f, k) {
            const o = ctx.createOscillator();
            const g = ctx.createGain();
            o.type = 'triangle';
            o.frequency.value = f;
            g.gain.setValueAtTime(0.0001, ctx.currentTime + k * 0.12);
            g.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + k * 0.12 + 0.02);
            g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + k * 0.12 + 0.35);
            o.connect(g).connect(ctx.destination);
            o.start(ctx.currentTime + k * 0.12);
            o.stop(ctx.currentTime + k * 0.12 + 0.4);
          });
        } catch (err) { /* no audio */ }
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * Integrations — "Sync now" and the mapping wizard
   * ------------------------------------------------------------------ */
  function integrations() {
    document.addEventListener('click', function (e) {
      const b = e.target.closest('[data-sync]');
      if (!b) return;
      const row = b.closest('li');
      const status = $('.sync-status', row);
      b.disabled = true;
      b.innerHTML = '<span class="spin"></span>Syncing';
      setTimeout(function () {
        b.disabled = false;
        b.textContent = 'Sync now';
        status.innerHTML = '<span class="pill success">Healthy</span>';
        $('.sync-when', row).textContent = 'Just now · ' + b.dataset.sync + ' rows';
        const dot = $('.dot', row);
        if (dot) dot.className = 'dot success';
        GG.toast('Synced — ' + b.dataset.sync + ' rows read, leaderboards updated');
      }, 1400);
    });
    if (location.hash === '#metrics') {
      const m = $('#metrics');
      if (m) setTimeout(function () { m.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 300);
    }
  }

  const PAGES = {
    leaderboards: leaderboards,
    goals: goals,
    competitions: competitions,
    announcements: announcements,
    users: users,
    teams: teams,
    offices: offices,
    channels: channels,
    'tv-wall': tvWall,
    admin: admin,
    integrations: integrations,
  };

  function run() {
    GG = window.GG;
    D = GG.data;
    const fn = PAGES[GG.page];
    try {
      if (fn) fn();
    } finally {
      GG.buildHotspots();
    }
  }

  window.GGWall = {
    mount: function (stage, opts) {
      GG = window.GG;
      D = GG.data;
      return Wall.mount(stage, opts);
    },
  };

  if (window.GG && window.GG.ready) run();
  else document.addEventListener('gg:ready', run);
})();
