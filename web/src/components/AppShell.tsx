import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';

import Avatar from './Avatar';
import CelebrationOverlay from './CelebrationOverlay';
import CommandPalette, { shortcutLabel } from './CommandPalette';
import NotificationBell from './NotificationBell';
import Toasts from './Toasts';
import ConfirmHost from './ConfirmHost';
import { NotificationProvider } from '../notifications';

import { useAuth } from '../auth';
import { useOrgAppearance } from '../orgAppearance';
import { useSiteIcon } from '../siteIcon';
import {
  BuildingIcon,
  ChartIcon,
  ChevronDownIcon,
  SparkIcon,
  CloseIcon,
  FlagIcon,
  HomeIcon,
  ImageIcon,
  InboxIcon,
  MedalIcon,
  MegaphoneIcon,
  MenuIcon,
  PencilIcon,
  PaletteIcon,
  PlugIcon,
  RulerIcon,
  SearchIcon,
  SettingsIcon,
  TargetIcon,
  TrophyIcon,
  TvIcon,
  UsersIcon,
} from './icons';
import { api } from '../api';

interface NavItem {
  to: string;
  label: string;
  Icon: (p: { className?: string }) => React.ReactElement;
  /** Capability required to see this link. Absent means everyone. */
  needs?: string;
}

/** How many open items there are, by link, for the count beside it. */
type Counts = Record<string, number>;

// Data, not markup. Adding a page is one entry here rather than edits in
// several places — and the visibility rules stay in one readable list instead
// of scattered conditionals.
//
// `needs` names a capability, not a role. When a fourth role appears, the
// server's capability map changes and this file does not.
//
// **Grouped by what an admin is doing** (review §4). It was two flat lists of
// 21, so where something lived had to be remembered rather than worked out.
// The first group is everyone's; each later one is a job — the wall, the
// people, the data — and shows only if its reader can open something in it.
const SECTIONS: { heading?: string; items: NavItem[] }[] = [
  {
    items: [
      { to: '/', label: 'Home', Icon: HomeIcon },
      {
        to: '/leaderboards',
        label: 'Leaderboards',
        Icon: TrophyIcon,
        needs: 'leaderboards.view',
      },
      { to: '/goals', label: 'Goals', Icon: TargetIcon, needs: 'goals.view' },
      { to: '/competitions', label: 'Competitions', Icon: FlagIcon },
      // No capability: everybody sees what the organization celebrates. That
      // is the entire point, and these rows are already on a wall screen
      // anyone can walk past.
      { to: '/announcements', label: 'Announcements', Icon: MegaphoneIcon },
      // No capability: everybody is on the points table, which is the point
      // of having one.
      { to: '/points', label: 'Points', Icon: SparkIcon },
      // Admin and manager, matching `reporting.view`. Agents are left out
      // because every answer on that page is a list of people to talk to.
      {
        to: '/reporting',
        label: 'Reporting',
        Icon: ChartIcon,
        needs: 'reporting.view',
      },
    ],
  },
  {
    heading: 'Wall',
    items: [
      // Admin, and the API agrees: every channel endpoint is
      // `require_role("admin")`. A nav entry that 403s is worse than no entry
      // — it advertises something and then blames the reader.
      {
        to: '/channels',
        label: 'TVs & Channels',
        Icon: TvIcon,
        needs: 'integrations.manage',
      },
      // Admin, not manager: a rule fires on every screen in the building every
      // time it matches, so the bar being too low is a decision with reach.
      {
        to: '/celebrations',
        label: 'Celebrations',
        Icon: MedalIcon,
        needs: 'integrations.manage',
      },
      {
        to: '/appearance',
        label: 'Appearance',
        Icon: PaletteIcon,
        needs: 'org.settings.edit',
      },
    ],
  },
  {
    heading: 'People',
    items: [
      { to: '/users', label: 'Users', Icon: UsersIcon, needs: 'users.view' },
      { to: '/teams', label: 'Teams', Icon: UsersIcon },
      {
        to: '/offices',
        label: 'Offices',
        Icon: BuildingIcon,
        needs: 'offices.manage',
      },
    ],
  },
  {
    heading: 'Data',
    items: [
      {
        to: '/integrations',
        label: 'Integrations',
        Icon: PlugIcon,
        needs: 'integrations.manage',
      },
      {
        to: '/metrics',
        label: 'Metrics',
        Icon: RulerIcon,
        needs: 'metrics.manage',
      },
      // `metrics.correct`, which **managers** hold and `metrics.manage`
      // (admin) does not imply the other way round — so the one role this
      // page exists for can reach it from here.
      {
        to: '/corrections',
        label: 'Corrections',
        Icon: PencilIcon,
        needs: 'metrics.correct',
      },
    ],
  },
  {
    heading: 'Organization',
    items: [
      // **What needs an admin, first in the group** (6.2), with a count
      // beside it so it is seen without being opened.
      {
        to: '/inbox',
        label: 'Inbox',
        Icon: InboxIcon,
        needs: 'org.settings.edit',
      },
      // **Every picture, video and sound in one place** (6.3), beside the
      // settings they are chosen from. At /library because /assets is the
      // build's own folder.
      {
        to: '/library',
        label: 'Assets',
        Icon: ImageIcon,
        needs: 'org.settings.edit',
      },
      {
        to: '/points/setup',
        label: 'Points setup',
        Icon: SparkIcon,
        needs: 'org.settings.edit',
      },
      {
        to: '/settings',
        label: 'Settings',
        Icon: SettingsIcon,
        needs: 'org.settings.edit',
      },
    ],
  },
];

export default function AppShell() {
  const { user, can } = useAuth();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  // The browser tab shows the organization's logo when one is set, and the
  // Goals target otherwise.
  const logo = useOrgAppearance()?.logo ?? null;
  useSiteIcon(logo ? `/api/images/${logo}` : null);

  // Navigating on mobile should close the drawer, or it covers the page you
  // just asked for.
  useEffect(() => setDrawerOpen(false), [location.pathname]);

  // The inbox's count, asked again on every page change and whenever the
  // inbox itself fixes something — cheap, and never more than a page stale.
  const [counts, setCounts] = useState<Counts>({});
  const admin = can('org.settings.edit');
  useEffect(() => {
    if (!admin) return;
    let alive = true;
    const ask = () =>
      api<{ count: number }>('/api/inbox')
        .then((found) => alive && setCounts({ '/inbox': found.count }))
        .catch(() => undefined);
    void ask();
    window.addEventListener('gg:inbox-changed', ask);
    return () => {
      alive = false;
      window.removeEventListener('gg:inbox-changed', ask);
    };
  }, [admin, location.pathname]);

  const visible = (items: NavItem[]) =>
    items.filter((i) => !i.needs || can(i.needs));

  // **Ctrl+K (⌘K) from anywhere** (6.16): the palette to jump to a person, a
  // board, a goal or a page by name. Taken from the browser, whose own use of
  // the key — its search bar — is a click away anyway.
  const [palette, setPalette] = useState(false);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setPalette((was) => !was);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  useEffect(() => setPalette(false), [location.pathname]);
  const pages = SECTIONS.flatMap(({ items }) => visible(items)).map(({ to, label }) => ({ to, label }));

  return (
    <NotificationProvider>
      <div className="min-h-screen bg-bg">
        {/* Keyboard users land here first; without it, reaching page content
          means tabbing through every nav link on every navigation. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface-raised focus:px-3 focus:py-2 focus:text-content"
        >
          Skip to content
        </a>

        <TopBar
          userName={user?.full_name ?? ''}
          photoDigest={user?.photo_digest}
          onMenu={() => setDrawerOpen(true)}
          onSearch={() => setPalette(true)}
        />

        <div className="flex">
          {/* Desktop sidebar. Hidden below lg, where the drawer takes over. */}
          <nav
            aria-label="Main"
            className="sticky top-14 hidden h-[calc(100vh-3.5rem)] w-60 shrink-0 overflow-y-auto border-r border-edge px-3 py-4 lg:block"
          >
            <NavSections visible={visible} counts={counts} />
          </nav>

          {drawerOpen && (
            <div className="fixed inset-0 z-40 lg:hidden">
              <button
                aria-label="Close navigation"
                onClick={() => setDrawerOpen(false)}
                className="absolute inset-0 bg-black/60"
              />
              <nav
                aria-label="Main"
                className="absolute inset-y-0 left-0 w-64 overflow-y-auto border-r border-edge bg-surface px-3 py-4"
              >
                <div className="mb-2 flex justify-end">
                  <button
                    onClick={() => setDrawerOpen(false)}
                    aria-label="Close navigation"
                    className="rounded-md p-2 text-content-muted hover:bg-surface-hover hover:text-content"
                  >
                    <CloseIcon />
                  </button>
                </div>
                <NavSections visible={visible} counts={counts} />
              </nav>
            </div>
          )}

          {/* Capped and centred: past ~1440px, long tables become hard to track
            across because the eye loses the row. */}
          <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-6">
            <div className="mx-auto max-w-[1440px]">
              <Outlet />
            </div>
          </main>
        </div>

        {/* Above everything, and outside <main> so it is not inside the region
          the skip link jumps to. */}
        <CommandPalette open={palette} onClose={() => setPalette(false)} pages={pages} />
        <CelebrationOverlay />
        <Toasts />
        <ConfirmHost />
      </div>
    </NotificationProvider>
  );
}

/** Which headings this person has folded, kept in this browser per person. */
function useFolded(userId: number | undefined): [Set<string>, (heading: string) => void] {
  const key = `gg:nav-folded:${userId ?? 'anon'}`;
  const [folded, setFolded] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(window.localStorage.getItem(key) ?? '[]') as string[]);
    } catch {
      return new Set();
    }
  });
  function toggle(heading: string) {
    setFolded((was) => {
      const next = new Set(was);
      if (next.has(heading)) next.delete(heading);
      else next.add(heading);
      try {
        window.localStorage.setItem(key, JSON.stringify([...next]));
      } catch {
        // A private window: folded for this visit only.
      }
      return next;
    });
  }
  return [folded, toggle];
}

/**
 * The navigation, in groups that fold (8.4).
 *
 * At 900 px tall five groups and twenty-odd links scrolled. Each heading folds
 * its group, remembered per person; the group holding the page you are on
 * stays open whatever, so the current page is never hidden from you.
 */
function NavSections({
  visible,
  counts,
}: {
  visible: (items: NavItem[]) => NavItem[];
  counts: Counts;
}) {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const [folded, toggle] = useFolded(user?.id);
  return (
    <>
      {SECTIONS.map(({ heading, items }) => {
        const shown = visible(items);
        if (shown.length === 0) return null;
        const here = shown.some((item) => item.to !== '/' && pathname.startsWith(item.to));
        const open = !heading || here || !folded.has(heading);
        return (
          <div key={heading ?? 'main'}>
            {heading && (
              <button
                type="button"
                onClick={() => toggle(heading)}
                aria-expanded={open}
                disabled={here}
                className="mt-6 flex w-full items-center justify-between px-3 text-caption uppercase tracking-wide text-content-subtle hover:text-content disabled:hover:text-content-subtle"
              >
                {heading}
                {!here && (
                  <ChevronDownIcon className={`size-3 transition-transform ${open ? '' : '-rotate-90'}`} />
                )}
              </button>
            )}
            {open && <NavSection items={shown} counts={counts} />}
          </div>
        );
      })}
    </>
  );
}

function NavSection({ items, counts }: { items: NavItem[]; counts: Counts }) {
  return (
    <ul className="mt-2 space-y-0.5">
      {items.map(({ to, label, Icon }) => (
        <li key={to}>
          <NavLink
            to={to}
            // `end` on "/" so Home isn't highlighted on every route — NavLink
            // treats "/" as a prefix of everything otherwise — and on Points,
            // which would otherwise light up beside Points setup.
            end={to === '/' || to === '/points'}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? 'bg-brand-subtle text-content'
                  : 'text-content-muted hover:bg-surface-hover hover:text-content'
              }`
            }
          >
            <Icon />
            <span className="flex-1">{label}</span>
            {(counts[to] ?? 0) > 0 && (
              <span
                className="rounded-full bg-brand px-1.5 text-xs font-medium tabular-nums text-white"
                aria-label={`${counts[to]} open`}
              >
                {counts[to]}
              </span>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function TopBar({
  userName,
  photoDigest,
  onMenu,
  onSearch,
}: {
  userName: string;
  photoDigest?: string | null;
  onMenu: () => void;
  onSearch: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-edge bg-surface px-4 sm:px-6">
      <button
        onClick={onMenu}
        aria-label="Open navigation"
        className="rounded-md p-2 text-content-muted hover:bg-surface-hover hover:text-content lg:hidden"
      >
        <MenuIcon />
      </button>

      {/* The logo and the name lead home, as on most sites. */}
      <Link to="/" className="flex items-center gap-3 rounded-md hover:opacity-90" aria-label="GoalGetter, home">
        <OrgLogo />
        <span className="font-semibold text-content">GoalGetter</span>
      </Link>

      <div className="ml-auto flex items-center gap-2">
        {/* The palette, for the mouse — and the shortcut, said where somebody
            will see it (6.16). */}
        <button
          type="button"
          onClick={onSearch}
          aria-label="Search"
          aria-keyshortcuts="Control+K Meta+K"
          className="flex items-center gap-2 rounded-md border border-edge px-2 py-1.5 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content sm:px-3"
        >
          <SearchIcon className="size-4" />
          <span className="hidden sm:inline">Search</span>
          <kbd className="hidden rounded border border-edge px-1 font-sans text-xs text-content-subtle md:inline">
            {shortcutLabel()}
          </kbd>
        </button>

        {/* Left of the account link, because it is the thing people reach for
            repeatedly and the account link is the thing they reach for once. */}
        <NotificationBell />

        {/* The way into everything about you. A link rather than a dropdown:
            there would be exactly two items in it and Sign out is already
            visible, so a menu would add focus trapping, click-outside and
            escape handling to save one click nobody was making. */}
        <NavLink
          to="/account"
          // Named, because below `sm` it is only a face — and a link that is
          // only an image read as nothing to a screen reader (QA-23).
          aria-label="Your account"
          className={({ isActive }) =>
            `flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
              isActive
                ? 'bg-brand-subtle text-content'
                : 'text-content-muted hover:bg-surface-hover hover:text-content'
            }`
          }
        >
          <Avatar name={userName} digest={photoDigest} />
          <span className="hidden sm:inline">{userName}</span>
        </NavLink>
      </div>
    </header>
  );
}


/**
 * The company's own mark, left of the product's name.
 *
 * **Beside "GoalGetter" rather than instead of it.** This is a tool a company
 * runs, not one they wrote: replacing the product name would leave nobody able
 * to say what they are looking at, and an unbranded header leaves a deployment
 * feeling like something rented. Both, in that order, is the honest answer.
 *
 * One logo, for light and dark alike: a second "for dark backgrounds" was
 * dropped as more than anybody needed.
 */
function OrgLogo() {
  const appearance = useOrgAppearance();
  const logo = appearance?.logo ?? null;

  // Nothing uploaded is the ordinary case, not a failure: most deployments
  // never set one, and the header reads perfectly well without it.
  if (!logo) return null;

  return (
    <img
      src={`/api/images/${logo}`}
      alt=""
      aria-hidden="true"
      className="h-7 w-auto max-w-32 shrink-0 object-contain"
    />
  );
}
