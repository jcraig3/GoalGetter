/* GoalGetter product page (../index.html).
 * Uses the icons, avatars and fictional data from demo.js and the TV wall
 * renderer from pages.js, so the page shows the same things the tour does. */
(function () {
  'use strict';

  const $ = function (s, r) { return (r || document).querySelector(s); };
  const $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let GG;

  /* ---------- Icons and avatars ---------- */

  function hydrate(root) {
    $$('[data-icon]', root).forEach(function (el) {
      const tmp = document.createElement('span');
      tmp.innerHTML = GG.icon(el.dataset.icon, el.className);
      el.replaceWith(tmp.firstChild);
    });
    $$('[data-avatar]', root).forEach(function (el) {
      const tmp = document.createElement('span');
      tmp.innerHTML = GG.avatar(el.dataset.avatar, el.dataset.size || '');
      el.replaceWith(tmp.firstChild);
    });
  }

  /* ---------- Theme ---------- */

  function currentTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  }
  function paintThemeButtons() {
    const light = currentTheme() === 'light';
    $$('[data-theme-toggle]').forEach(function (b) {
      b.innerHTML = GG.icon(light ? 'moon' : 'sun');
      b.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
    });
    $$('[data-theme-toggle-text]').forEach(function (b) {
      b.textContent = light ? 'Switch to dark theme' : 'Switch to light theme';
    });
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.content = light ? '#fafafa' : '#0b0e14';
  }
  function toggleTheme() {
    const next = currentTheme() === 'light' ? 'dark' : 'light';
    const apply = function () {
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('ggdemo:theme', next); } catch (e) { /* private mode */ }
      paintThemeButtons();
    };
    if (document.startViewTransition && !reduceMotion) document.startViewTransition(apply);
    else apply();
  }

  /* ---------- Nav: scroll state, scroll spy, mega menu, drawer ---------- */

  function nav() {
    const bar = $('#nav');
    const onScroll = function () { bar.classList.toggle('scrolled', window.scrollY > 8); };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });

    const links = $$('.nav-links > a[href^="#"]');
    const spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        links.forEach(function (a) { a.classList.toggle('is-current', a.getAttribute('href') === '#' + e.target.id); });
      });
    }, { rootMargin: '-45% 0px -50% 0px' });
    links.forEach(function (a) {
      const s = $(a.getAttribute('href'));
      if (s) spy.observe(s);
    });

    const megaBtn = $('[data-mega]');
    const mega = $('#mega');
    function setMega(open) {
      mega.hidden = !open;
      megaBtn.setAttribute('aria-expanded', String(open));
    }
    megaBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      setMega(mega.hidden);
    });
    document.addEventListener('click', function (e) {
      if (!mega.hidden && !mega.contains(e.target)) setMega(false);
    });

    const burger = $('[data-burger]');
    const drawer = $('#drawer');
    const copy = $('[data-copy-of]', drawer);
    copy.innerHTML = $(copy.dataset.copyOf).innerHTML;
    function setDrawer(open) {
      drawer.hidden = !open;
      burger.setAttribute('aria-expanded', String(open));
      burger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
      burger.innerHTML = GG.icon(open ? 'close' : 'menu');
    }
    burger.addEventListener('click', function () { setDrawer(drawer.hidden); });
    drawer.addEventListener('click', function (e) {
      if (e.target.closest('a')) setDrawer(false);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (!mega.hidden) { setMega(false); megaBtn.focus(); }
      if (!drawer.hidden) { setDrawer(false); burger.focus(); }
    });
    window.addEventListener('resize', function () {
      if (window.innerWidth >= 1024 && !drawer.hidden) setDrawer(false);
    });
  }

  /* ---------- Hero: a leaderboard that keeps moving ---------- */

  function rankTone(r) {
    return r === 1 ? 'c-gold' : r === 2 ? 'c-silver' : r === 3 ? 'c-bronze' : '';
  }

  function heroBoard() {
    const list = $('#hero-board');
    if (!list) return;
    const pick = ['Shohei Ohtani', 'LaDainian Tomlinson', 'Mike Trout', 'Natasha Romanoff', 'Bruce Wayne', 'Peter Parker'];
    const rows = pick.map(function (name, i) {
      const p = GG.data.PEOPLE.find(function (x) { return x.name === name; }) || {};
      return { name: name, team: p.team || '', value: 71000 - i * 3600 + Math.round(Math.random() * 900), move: 0 };
    });

    function render() {
      list.innerHTML = rows.map(function (r, i) {
        const m = r.move > 0 ? '<span class="m up">▲ ' + r.move + '</span>' : r.move < 0 ? '<span class="m down">▼ ' + -r.move + '</span>' : '<span class="m">–</span>';
        return (
          '<li data-name="' + r.name + '" class="' + (r.name === GG.data.VIEWER ? 'me' : '') + (r.flash ? ' up' : '') + '">' +
          '<span class="r ' + rankTone(i + 1) + '">' + (i + 1) + '</span>' + GG.avatar(r.name) +
          '<span class="n">' + r.name + (r.name === GG.data.VIEWER ? ' <span class="c-subtle">· you</span>' : '') + '<small>' + r.team + '</small></span>' +
          '<span class="v">' + GG.fmt(r.value, 'currency') + '</span>' + m + '</li>'
        );
      }).join('');
    }
    render();

    const win = $('#hero-win');
    const winText = $('#hero-win-text');

    function tick() {
      const before = {};
      $$('li', list).forEach(function (li) { before[li.dataset.name] = li.getBoundingClientRect().top; });
      const oldRank = {};
      rows.forEach(function (r, i) { oldRank[r.name] = i; r.flash = false; });

      // Favour climbers from lower down so the order actually changes.
      const k = 1 + Math.floor(Math.random() * (rows.length - 1));
      const gap = rows[k - 1].value - rows[k].value;
      rows[k].value += Math.max(gap + 200 + Math.round(Math.random() * 1400), 400);
      rows.forEach(function (r, i) { if (i !== k && Math.random() < 0.4) r.value += Math.round(Math.random() * 600); });
      rows.sort(function (a, b) { return b.value - a.value; });
      rows.forEach(function (r, i) {
        r.move = oldRank[r.name] - i;
        if (r.move > 0) r.flash = true;
      });
      render();

      if (!reduceMotion) {
        $$('li', list).forEach(function (li) {
          const dy = before[li.dataset.name] - li.getBoundingClientRect().top;
          if (!dy) return;
          li.animate([{ transform: 'translateY(' + dy + 'px)' }, { transform: 'none' }], { duration: 700, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' });
        });
      }

      const climber = rows.find(function (r) { return r.move > 0; });
      if (climber && win) {
        const rank = rows.indexOf(climber) + 1;
        winText.textContent = rank === 1 ? climber.name + ' took first place' : climber.name + ' moved up to #' + rank;
        win.classList.remove('show');
        void win.offsetWidth;
        win.classList.add('show');
        clearTimeout(tick.hide);
        tick.hide = setTimeout(function () { win.classList.remove('show'); }, 2600);
      }
    }

    let timer = null;
    const io = new IntersectionObserver(function (entries) {
      const visible = entries[0].isIntersecting;
      clearInterval(timer);
      if (visible && !reduceMotion) timer = setInterval(tick, 3400);
    });
    io.observe(list);
    setTimeout(function () { if (win) win.classList.add('show'); }, 1400);
    setTimeout(function () { if (win) win.classList.remove('show'); }, 4200);
  }

  function featureBoard() {
    const list = $('#feat-board');
    if (!list) return;
    const top = GG.data.PEOPLE.filter(function (p) { return p.role === 'Agent'; })
      .sort(function (a, b) { return b.calls - a.calls; }).slice(0, 7);
    list.innerHTML = top.map(function (p, i) {
      return (
        '<li class="' + (p.name === GG.data.VIEWER ? 'me' : '') + '"><span class="r ' + rankTone(i + 1) + '">' + (i + 1) + '</span>' +
        GG.avatar(p.name, 'xs') + '<span class="n">' + p.name + '</span><span class="v">' + p.calls + '</span></li>'
      );
    }).join('');
  }

  /* ---------- Feature card spotlight ---------- */

  function spotlight() {
    $$('.feat').forEach(function (card) {
      card.addEventListener('pointermove', function (e) {
        const r = card.getBoundingClientRect();
        card.style.setProperty('--mx', (e.clientX - r.left) + 'px');
        card.style.setProperty('--my', (e.clientY - r.top) + 'px');
      });
    });
  }

  /* ---------- Reveal on scroll and counters ---------- */

  function countUp(el) {
    const to = Number(el.dataset.countTo);
    if (reduceMotion) { el.textContent = to; return; }
    const start = performance.now();
    const dur = 1100;
    (function frame(now) {
      const t = Math.min((now - start) / dur, 1);
      el.textContent = Math.round(to * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(frame);
    })(start);
  }

  function reveals() {
    const io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        const el = e.target;
        if (el.classList.contains('reveal')) el.classList.add('is-in');
        if (el.dataset.countTo) countUp(el);
        $$('.progress-fill[data-w]', el).forEach(function (f) { f.style.width = f.dataset.w + '%'; });
        io.unobserve(el);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });
    $$('.reveal, [data-count-to]').forEach(function (el) { io.observe(el); });
  }

  /* ---------- TV wall preview ---------- */

  function tv() {
    const stage = $('#site-stage');
    if (!stage || !window.GGWall) return;
    stage.classList.add('stage');
    let wall = null;
    const winners = [
      ['Shohei Ohtani', 'hit Revenue · October', '$74,100'],
      ['Wally West', 'hit Calls · This week', '433 calls'],
      ['Justin Herbert', 'hit Deals · October', '18 deals'],
      ['Diana Prince', 'closed the biggest deal of the quarter', '$21,400'],
    ];
    let w = 0;
    const io = new IntersectionObserver(function (entries) {
      if (!entries[0].isIntersecting || wall) return;
      wall = window.GGWall.mount(stage, { scenes: ['podium', 'race', 'gauge', 'h2h', 'announce'], slideMs: 6500, channel: 'Sales floor' });
      setTimeout(function () { wall.overtake('Mike Trout passed LaDainian Tomlinson for 2nd'); }, 2600);
    }, { threshold: 0.25 });
    io.observe(stage);

    $('#tv-celebrate').addEventListener('click', function () {
      if (!wall) wall = window.GGWall.mount(stage, { scenes: ['podium', 'race', 'gauge', 'h2h', 'announce'], slideMs: 6500, channel: 'Sales floor' });
      const x = winners[w % winners.length];
      w += 1;
      wall.celebrate(x[0], x[1], x[2]);
    });
  }

  /* ---------- Roles ---------- */

  function roles() {
    const tabs = $$('[data-role-tab]');
    function select(tab, focus) {
      tabs.forEach(function (t) {
        const on = t === tab;
        t.setAttribute('aria-selected', String(on));
        t.tabIndex = on ? 0 : -1;
        $('#' + t.getAttribute('aria-controls')).hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach(function (t, i) {
      t.tabIndex = i === 0 ? 0 : -1;
      t.addEventListener('click', function () { select(t); });
      t.addEventListener('keydown', function (e) {
        const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
        if (!d) return;
        e.preventDefault();
        select(tabs[(i + d + tabs.length) % tabs.length], true);
      });
    });

    $$('[data-as-role]').forEach(function (a) {
      a.addEventListener('click', function () {
        try { localStorage.setItem('ggdemo:role', a.dataset.asRole); } catch (e) { /* private mode */ }
      });
    });
  }

  /* ---------- Tour list ---------- */

  function tourList() {
    const list = $('#tour-list');
    if (!list) return;
    list.innerHTML = GG.data.TOUR.map(function (t, i) {
      return (
        '<li class="reveal" style="--d:' + (i % 3) * 70 + 'ms"><a href="demo/' + t.file + '"><span class="n">' + (i + 1) + '</span>' +
        '<span class="t"><b>' + t.title + '</b><small>' + t.blurb + '</small></span>' + GG.icon('right', 'sm') + '</a></li>'
      );
    }).join('');
  }

  /* ---------- Boot ---------- */

  function init() {
    GG = window.GG;
    if (!GG) {
      document.documentElement.classList.add('no-gg');
      return;
    }
    hydrate(document);
    paintThemeButtons();
    $$('[data-theme-toggle], [data-theme-toggle-text]').forEach(function (b) { b.addEventListener('click', toggleTheme); });
    nav();
    heroBoard();
    featureBoard();
    tourList();
    spotlight();
    roles();
    reveals();
    tv();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
