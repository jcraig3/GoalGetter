import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import { api } from '../api';
import { useAuth } from '../auth';
import Avatar from './Avatar';

interface Hit {
  id: number;
  name: string;
  detail: string | null;
  photo_digest?: string | null;
}

interface Results {
  people: Hit[];
  boards: Hit[];
  goals: Hit[];
  competitions: Hit[];
  channels: Hit[];
  teams?: Hit[];
  offices?: Hit[];
  rules?: Hit[];
  badges?: Hit[];
  metrics?: Hit[];
}

interface Row {
  key: string;
  group: string;
  label: string;
  detail?: string | null;
  to: string;
  face?: { name: string; digest: string | null | undefined };
  /** "Team", "Office", "Board"… on the row itself (P3-15). */
  kind?: string;
}

/** What each kind of result is, said on the row — a team and an office of
 *  the same name were two identical lines (P3-15). */
const KIND_WORD: Record<string, string> = {
  people: 'Person',
  boards: 'Board',
  goals: 'Goal',
  competitions: 'Contest',
  channels: 'Channel',
  teams: 'Team',
  offices: 'Office',
  rules: 'Rule',
  badges: 'Badge',
  metrics: 'Metric',
};

/** Where each kind of hit opens, and what its group is called. */
const KINDS: { kind: keyof Results; group: string; to: (id: number) => string }[] = [
  // A person opens their profile (9.3), where Edit is offered to whoever may.
  { kind: 'people', group: 'People', to: (id) => `/people/${id}` },
  { kind: 'boards', group: 'Leaderboards', to: (id) => `/leaderboards/${id}` },
  { kind: 'goals', group: 'Goals', to: (id) => `/goals/${id}` },
  { kind: 'competitions', group: 'Competitions', to: (id) => `/competitions/${id}` },
  { kind: 'channels', group: 'Channels', to: (id) => `/channels/${id}` },
  // Lists without a page per row: opened with the row picked out (7.9).
  { kind: 'teams', group: 'Teams', to: (id) => `/teams?focus=${id}` },
  { kind: 'offices', group: 'Offices', to: (id) => `/offices?focus=${id}` },
  { kind: 'rules', group: 'Celebration rules', to: (id) => `/celebrations?focus=${id}` },
  { kind: 'badges', group: 'Badges', to: (id) => `/points/setup?tab=badges&focus=${id}` },
  { kind: 'metrics', group: 'Metrics', to: (id) => `/metrics?focus=${id}` },
];

/**
 * Things to do and the settings' own tabs (7.9), offered to whoever can.
 * Matched by name like a page — "new" lists every action.
 */
export const ACTIONS: { label: string; to: string; capability: string; also?: string }[] = [
  { label: 'New goal', to: '/goals?new=1', capability: 'goals.manage' },
  { label: 'New leaderboard', to: '/leaderboards?new=1', capability: 'leaderboards.manage' },
  { label: 'New competition', to: '/competitions?new=1', capability: 'competitions.manage' },
  { label: 'New celebration rule', to: '/celebrations?new=1', capability: 'integrations.manage' },
  { label: 'New channel', to: '/channels?new=1', capability: 'integrations.manage' },
  // Other words for it (P4-11): "new" lists every action, and these two do
  // not say "new"; "password" found nothing at all.
  { label: 'Connect a TV', to: '/channels?connect=1', capability: 'integrations.manage', also: 'new tv display screen pair add' },
  { label: 'New team', to: '/teams?new=1', capability: 'teams.manage' },
  { label: 'New metric', to: '/metrics?new=1', capability: 'metrics.manage' },
  { label: 'Invite people', to: '/users?invite=1', capability: 'users.invite', also: 'new user person add temporary password' },
  // Everybody's: no capability needed.
  { label: 'Change your password', to: '/account', capability: '', also: 'password account reset' },
];

export const SETTINGS: { label: string; to: string; capability: string; also?: string }[] = [
  { label: 'General settings', to: '/settings?tab=general', capability: 'org.settings.edit' },
  { label: 'Branding', to: '/settings?tab=branding', capability: 'org.settings.edit' },
  { label: 'What people can set', to: '/settings?tab=people', capability: 'org.settings.edit' },
  { label: 'Sign-in & security', to: '/settings?tab=signin', capability: 'org.settings.edit', also: 'password two-step mfa sso' },
  { label: 'Hosting', to: '/settings?tab=hosting', capability: 'org.settings.edit', also: 'https web address proxy connection certificate' },
  { label: 'Roles', to: '/settings?tab=roles', capability: 'org.settings.edit' },
  { label: 'Activity & export', to: '/settings?tab=activity', capability: 'org.settings.edit' },
];

/** Contest states as words, for the line under a contest's name. */
const STATE: Record<string, string> = {
  draft: 'Draft',
  scheduled: 'Starting soon',
  active: 'Running',
  ended: 'Finishing',
  closed: 'Finished',
  cancelled: 'Cancelled',
};

/** The pages this person can open, matched by name — "set" finds Settings. */
export function matchPages<T extends { to: string; label: string; also?: string }>(
  pages: T[],
  text: string,
): T[] {
  const want = text.trim().toLowerCase();
  if (!want) return pages;
  return pages
    .filter((p) => `${p.label} ${p.also ?? ''}`.toLowerCase().includes(want))
    // Starting with it, then containing it, then only in the other words
    // (P5-11): "password" put Invite people above Change your password.
    .sort((a, b) => rank(a.label, want) - rank(b.label, want));
}

function rank(label: string, want: string): number {
  const text = label.toLowerCase();
  return text.startsWith(want) ? 0 : text.includes(want) ? 1 : 2;
}

/** "Ctrl K", or "⌘K" on a Mac — said the way the keyboard in front of you says it. */
export function shortcutLabel(): string {
  const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
  return mac ? '⌘K' : 'Ctrl K';
}

/**
 * **Jump to anything** (6.16): a person, a board, a goal, a contest, a
 * channel or a page, by typing its name. Ctrl+K (⌘K) from anywhere, or the
 * search button in the top bar.
 *
 * The server narrows every kind by the rule its own list uses, so nothing
 * appears here that its page would hide. Arrow keys move, Enter opens,
 * Escape closes.
 */
export default function CommandPalette({
  open,
  onClose,
  pages,
}: {
  open: boolean;
  onClose: () => void;
  /** The navigation this person can see, so a page is a result too. */
  pages: { to: string; label: string }[];
}) {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [text, setText] = useState('');
  const [results, setResults] = useState<Results | null>(null);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setText('');
    setResults(null);
    setActive(0);
    // After paint, so the focus lands on an input that exists.
    window.setTimeout(() => input.current?.focus(), 0);
  }, [open]);

  // A moment after typing stops, not on every key.
  useEffect(() => {
    const q = text.trim();
    if (!open || !q) {
      setResults(null);
      return;
    }
    let stale = false;
    const timer = window.setTimeout(() => {
      api<Results>(`/api/search?q=${encodeURIComponent(q)}`)
        .then((found) => !stale && setResults(found))
        .catch(() => !stale && setResults(null));
    }, 150);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [text, open]);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    for (const kind of KINDS) {
      for (const hit of results?.[kind.kind] ?? []) {
        out.push({
          key: `${kind.kind}-${hit.id}`,
          group: kind.group,
          label: hit.name,
          detail: kind.kind === 'competitions' ? (STATE[hit.detail ?? ''] ?? hit.detail) : hit.detail,
          to: kind.to(hit.id),
          face: kind.kind === 'people' ? { name: hit.name, digest: hit.photo_digest } : undefined,
          kind: KIND_WORD[kind.kind],
        });
      }
    }
    // Pages last when searching — somebody typing a name wants the thing —
    // and the whole list before anything is typed.
    for (const page of matchPages(pages, text).slice(0, text.trim() ? 4 : 12)) {
      out.push({ key: `page-${page.to}`, group: 'Pages', label: page.label, to: page.to });
    }
    // Only once something is typed: before that, the pages are the menu.
    if (text.trim()) {
      const mine = (list: typeof ACTIONS) => list.filter((a) => !a.capability || can(a.capability));
      for (const action of matchPages(mine(ACTIONS), text)) {
        out.push({ key: `do-${action.to}`, group: 'Actions', label: action.label, to: action.to });
      }
      for (const tab of matchPages(mine(SETTINGS), text).slice(0, 3)) {
        out.push({ key: `set-${tab.to}`, group: 'Settings', label: tab.label, to: tab.to });
      }
    }
    return out;
  }, [results, pages, text, can]);

  useEffect(() => setActive(0), [rows.length]);

  if (!open) return null;

  function go(row: Row | undefined) {
    if (!row) return;
    onClose();
    void navigate(row.to);
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((i) => Math.min(rows.length - 1, i + 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      go(rows[active]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]">
      <button aria-label="Close search" onClick={onClose} className="absolute inset-0 bg-black/60" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Go to"
        className="relative w-full max-w-xl overflow-hidden rounded-lg border border-edge bg-surface shadow-2xl"
      >
        <input
          ref={input}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-results"
          aria-activedescendant={rows[active] ? `palette-${rows[active]!.key}` : undefined}
          aria-label="Search people, boards, goals, pages and actions"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder="Search people, teams, boards, goals, settings or “new”…"
          className="w-full border-b border-edge bg-transparent px-4 py-3 text-content outline-none placeholder:text-content-subtle"
        />
        <ul id="palette-results" role="listbox" className="max-h-[60vh] overflow-y-auto py-1">
          {rows.map((row, index) => (
            <li key={row.key} role="presentation">
              {(index === 0 || rows[index - 1]!.group !== row.group) && (
                <p className="px-4 pb-1 pt-3 text-caption uppercase tracking-wide text-content-subtle">
                  {row.group}
                </p>
              )}
              <div
                id={`palette-${row.key}`}
                role="option"
                aria-selected={index === active}
                onMouseEnter={() => setActive(index)}
                onClick={() => go(row)}
                className={`mx-2 flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm ${
                  index === active ? 'bg-brand-subtle text-content' : 'text-content-muted'
                }`}
              >
                {row.face && <Avatar name={row.face.name} digest={row.face.digest} />}
                <span className="min-w-0 flex-1 truncate text-content">{row.label}</span>
                {row.detail && (
                  <span className="shrink-0 truncate text-xs text-content-subtle">{row.detail}</span>
                )}
                {row.kind && (
                  <span className="shrink-0 rounded border border-edge px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-content-subtle">
                    {row.kind}
                  </span>
                )}
              </div>
            </li>
          ))}
          {text.trim() && results && rows.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-content-muted">
              Nothing called &ldquo;{text.trim()}&rdquo;.
            </li>
          )}
        </ul>
        <p className="border-t border-edge px-4 py-2 text-xs text-content-subtle">
          ↑ ↓ to move · Enter to open · Esc to close
        </p>
      </div>
    </div>
  );
}
