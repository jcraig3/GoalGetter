import { useCallback, useEffect, useMemo, useState } from 'react';

import { api } from '../api';
import { ChevronDownIcon } from './icons';
import { Tab } from './Tabs';
import Toggle from './Toggle';

interface Link {
  target: 'team' | 'office';
  id: number;
  name: string;
}

export interface Source {
  id: number;
  kind: 'team' | 'channel';
  name: string;
  membership: string | null;
  parent_id: number | null;
  people: number | null;
  standard_channels: number;
  linkable: boolean;
  gone: boolean;
  link: Link | null;
}

interface Named {
  id: number;
  name: string;
}

export interface MirrorPerson {
  user_id: number;
  name: string;
  email: string;
  status: Status;
  team_id: number | null;
  team: string | null;
  office: string | null;
  teams_team_id: number | null;
  teams_team: string | null;
  teams_choices: string[];
  teams_office: string | null;
  m365_office: string;
  sources: string[];
  office_differs_teams: boolean;
  office_differs_m365: boolean;
}

export type Status =
  | 'conflict'
  | 'moved_by_hand'
  | 'only_here'
  | 'would_move'
  | 'kept'
  | 'in_step'
  | 'not_linked'
  | 'not_in_m365';

export interface Mirror {
  available: boolean;
  auto: boolean;
  read_at: string | null;
  note: string | null;
  sources: Source[];
  teams: Named[];
  offices: Named[];
  people: MirrorPerson[];
  office_changes: { team: string; from_office: string | null; to_office: string }[];
  counts: Record<Status, number>;
  not_yet_here: number;
}

export const MIRROR_BASE = '/api/admin/directory/mirror';

/** What each status means, for the person reading the comparison. */
export const STATUS_LABEL: Record<Status, string> = {
  conflict: 'In two linked places',
  moved_by_hand: 'Moved by hand',
  only_here: 'Added here, not in Teams',
  would_move: 'Will move',
  kept: 'Kept here',
  in_step: 'In step',
  not_linked: 'Not in anything linked',
  not_in_m365: 'Not in Microsoft 365',
};

export const DECISIONS: Status[] = ['conflict', 'moved_by_hand', 'only_here'];

export type Act = (path: string, init: RequestInit) => Promise<void>;

/** The mirror's state and the one way to change it: every action answers with
 * the whole picture again, so nothing on the page can drift from the server. */
export function useMirror() {
  const [mirror, setMirror] = useState<Mirror | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Mirror>(MIRROR_BASE)
      .then(setMirror)
      .catch(() => setMirror(null))
      .finally(() => setLoaded(true));
  }, []);

  useEffect(load, [load]);

  const act: Act = useCallback(async (path, init) => {
    setBusy(true);
    setError(null);
    try {
      setMirror(await api<Mirror>(`${MIRROR_BASE}${path}`, init));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not do that.');
    } finally {
      setBusy(false);
    }
  }, []);

  return { mirror, loaded, error, busy, act };
}

type View = 'all' | 'teams' | 'channels';
type Sort = 'name' | 'people' | 'in_use';

function inUse(s: Source) {
  return s.link !== null;
}

function bySort(sort: Sort) {
  return (a: Source, b: Source) => {
    if (sort === 'people') return (b.people ?? -1) - (a.people ?? -1) || a.name.localeCompare(b.name);
    if (sort === 'in_use') return Number(inUse(b)) - Number(inUse(a)) || a.name.localeCompare(b.name);
    return a.name.localeCompare(b.name);
  };
}

/**
 * Every Microsoft Team and channel, and what each one is here.
 *
 * **Three ways in, one search box.** "All" is the tree — each Team with its
 * channels folded under it — for somebody who knows which Team they want.
 * "Teams" and "Channels" are flat lists for somebody who knows the name but not
 * where it lives. The search works in all three, and opens any Team whose
 * channel matched.
 *
 * **Standard channels are listed, not usable.** Everybody in a Team is in its
 * standard channels, so one could only ever repeat the Team. Showing them says
 * so where somebody goes looking; hiding them made it look as if channels were
 * not being read at all.
 */
export function SourceBrowser({ mirror, busy, act }: { mirror: Mirror; busy: boolean; act: Act }) {
  const [search, setSearch] = useState('');
  const [view, setView] = useState<View>('all');
  const [sort, setSort] = useState<Sort>('in_use');
  const [onlyInUse, setOnlyInUse] = useState(false);
  const [usableOnly, setUsableOnly] = useState(false);
  const [open, setOpen] = useState<Set<number>>(new Set());

  const teams = mirror.sources.filter((s) => s.kind === 'team');
  const channels = mirror.sources.filter((s) => s.kind === 'channel');
  const teamName = useMemo(() => new Map(teams.map((t) => [t.id, t.name])), [teams]);
  const q = search.trim().toLowerCase();
  const matches = (s: Source) => !q || s.name.toLowerCase().includes(q);
  const keep = (s: Source) => (!onlyInUse || inUse(s)) && (!usableOnly || s.linkable);

  const channelsOf = useMemo(() => {
    const out = new Map<number, Source[]>();
    for (const c of channels) {
      if (c.parent_id !== null) out.set(c.parent_id, [...(out.get(c.parent_id) ?? []), c]);
    }
    return out;
  }, [channels]);

  function choose(source: Source, value: string) {
    const [use_as, id] = value.split(':');
    void act(`/sources/${source.id}`, {
      method: 'PUT',
      body: JSON.stringify(
        use_as === 'nothing' ? { use_as } : { use_as, ...(id !== 'new' ? { id: Number(id) } : {}) },
      ),
    });
  }

  if (mirror.sources.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-edge px-4 py-6 text-center text-sm text-content-muted">
        Nothing read yet. Press <strong>Read from Microsoft Teams</strong> to list your Teams and
        their channels.
      </p>
    );
  }

  // The rows for the chosen view, already filtered and sorted.
  const tree =
    view === 'all'
      ? teams
          .map((team) => {
            const kids = (channelsOf.get(team.id) ?? []).filter(keep);
            const shownKids = matches(team) ? kids : kids.filter(matches);
            const show = (matches(team) || shownKids.length > 0) && (keep(team) || shownKids.length > 0);
            return { team, kids: shownKids, show, childMatched: q !== '' && kids.some(matches) };
          })
          .filter((row) => row.show)
          .sort((a, b) => bySort(sort)(a.team, b.team))
      : [];
  const flat = view === 'all' ? [] : (view === 'teams' ? teams : channels).filter((s) => matches(s) && keep(s)).sort(bySort(sort));

  const shown = view === 'all' ? tree.length : flat.length;
  const total = view === 'channels' ? channels.length : teams.length;
  const linked = mirror.sources.filter(inUse).length;
  const noChannels = channels.length === 0;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search Teams and channels"
          aria-label="Search Teams and channels"
          className="min-w-0 flex-1 rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content sm:max-w-xs"
        />
        <div className="flex gap-1" role="group" aria-label="Show">
          <Tab active={view === 'all'} onClick={() => setView('all')}>
            All
          </Tab>
          <Tab active={view === 'teams'} onClick={() => setView('teams')}>
            Teams ({teams.length})
          </Tab>
          <Tab active={view === 'channels'} onClick={() => setView('channels')}>
            Channels ({channels.length})
          </Tab>
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          aria-label="Sort by"
          className="rounded-md border border-edge bg-bg px-2 py-2 text-sm text-content"
        >
          <option value="in_use">In use first</option>
          <option value="name">Name A–Z</option>
          <option value="people">Most people</option>
        </select>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <label className="flex items-center gap-2 text-content-muted">
          <input type="checkbox" checked={onlyInUse} onChange={(e) => setOnlyInUse(e.target.checked)} />
          Only ones in use ({linked})
        </label>
        {view !== 'teams' && !noChannels && (
          <label className="flex items-center gap-2 text-content-muted">
            <input type="checkbox" checked={usableOnly} onChange={(e) => setUsableOnly(e.target.checked)} />
            Hide standard channels
          </label>
        )}
        <span className="ml-auto text-xs text-content-subtle">
          Showing {shown} of {total}
        </span>
      </div>

      {view === 'channels' && noChannels ? (
        <p className="rounded-md border border-dashed border-edge px-4 py-6 text-center text-sm text-content-muted">
          No channels read yet.{' '}
          {mirror.note ? 'See the note above for the permission it needs.' : 'Press Read from Microsoft Teams.'}
        </p>
      ) : shown === 0 ? (
        <p className="px-1 py-4 text-sm text-content-muted">Nothing matches.</p>
      ) : (
        <ul className="max-h-[32rem] divide-y divide-edge overflow-y-auto rounded-md border border-edge">
          {view === 'all'
            ? tree.map(({ team, kids, childMatched }) => {
                const all = channelsOf.get(team.id) ?? [];
                // Opened by hand, or because what the filters are looking for
                // is inside it.
                const expanded = open.has(team.id) || childMatched || (onlyInUse && kids.length > 0);
                return (
                  <li key={team.id}>
                    <SourceRow
                      source={team}
                      mirror={mirror}
                      busy={busy}
                      onChoose={choose}
                      detail={`Team${all.length ? ` · ${all.length} ${all.length === 1 ? 'channel' : 'channels'}` : ''}`}
                      toggle={
                        all.length > 0
                          ? {
                              open: expanded,
                              onToggle: () =>
                                setOpen((now) => {
                                  const next = new Set(now);
                                  if (next.has(team.id)) next.delete(team.id);
                                  else next.add(team.id);
                                  return next;
                                }),
                            }
                          : undefined
                      }
                    />
                    {expanded && kids.length > 0 && (
                      <ul className="border-t border-edge bg-bg/50">
                        {[...kids]
                          .sort((a, b) => Number(b.linkable) - Number(a.linkable) || bySort(sort)(a, b))
                          .map((c) => (
                            <li key={c.id} className="border-b border-edge last:border-0">
                              <SourceRow
                                source={c}
                                mirror={mirror}
                                busy={busy}
                                onChoose={choose}
                                detail={`${capitalise(c.membership ?? 'standard')} channel`}
                                nested
                              />
                            </li>
                          ))}
                      </ul>
                    )}
                  </li>
                );
              })
            : flat.map((s) => (
                <li key={s.id}>
                  <SourceRow
                    source={s}
                    mirror={mirror}
                    busy={busy}
                    onChoose={choose}
                    detail={
                      s.kind === 'team'
                        ? 'Team'
                        : `${capitalise(s.membership ?? 'standard')} channel in ${teamName.get(s.parent_id ?? -1) ?? 'a Team'}`
                    }
                  />
                </li>
              ))}
        </ul>
      )}
    </div>
  );
}

function capitalise(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function SourceRow({
  source,
  mirror,
  busy,
  onChoose,
  detail,
  nested = false,
  toggle,
}: {
  source: Source;
  mirror: Mirror;
  busy: boolean;
  onChoose: (source: Source, value: string) => void;
  detail: string;
  nested?: boolean;
  toggle?: { open: boolean; onToggle: () => void };
}) {
  const value = source.link ? `${source.link.target}:${source.link.id}` : 'nothing';
  // One team or office follows one source, so what is taken is not offered.
  const takenTeams = new Set(
    mirror.sources.filter((s) => s.link?.target === 'team' && s.id !== source.id).map((s) => s.link!.id),
  );
  const takenOffices = new Set(
    mirror.sources.filter((s) => s.link?.target === 'office' && s.id !== source.id).map((s) => s.link!.id),
  );

  return (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-2 py-2 pr-3 text-sm ${
        nested ? 'pl-10' : 'pl-3'
      } ${source.link ? 'border-l-2 border-brand' : 'border-l-2 border-transparent'}`}
    >
      <span className="flex w-5 shrink-0 justify-center">
        {toggle && (
          <button
            type="button"
            onClick={toggle.onToggle}
            aria-expanded={toggle.open}
            aria-label={`${toggle.open ? 'Hide' : 'Show'} channels in ${source.name}`}
            className="rounded p-0.5 text-content-subtle hover:bg-surface-hover hover:text-content"
          >
            <ChevronDownIcon className={`size-3.5 transition-transform ${toggle.open ? '' : '-rotate-90'}`} />
          </button>
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className={`block truncate ${source.gone ? 'text-content-muted line-through' : 'text-content'}`}>
          {source.name}
        </span>
        <span className="block truncate text-xs text-content-subtle">
          {detail}
          {source.people !== null && ` · ${source.people} ${source.people === 1 ? 'person' : 'people'}`}
          {source.gone && <span className="text-warning"> · no longer in Microsoft Teams</span>}
        </span>
      </span>
      {source.linkable ? (
        <select
          value={value}
          disabled={busy || (source.gone && !source.link)}
          onChange={(e) => onChoose(source, e.target.value)}
          aria-label={`Use ${source.name} as`}
          className={`w-full rounded-md border bg-bg px-2 py-1 text-sm sm:w-60 ${
            source.link ? 'border-brand text-content' : 'border-edge text-content-muted'
          }`}
        >
          <option value="nothing">Not used</option>
          <optgroup label="A team">
            <option value="team:new">New team “{source.name}”</option>
            {mirror.teams
              .filter((t) => !takenTeams.has(t.id))
              .map((t) => (
                <option key={t.id} value={`team:${t.id}`}>
                  Team: {t.name}
                </option>
              ))}
          </optgroup>
          <optgroup label="An office">
            <option value="office:new">New office “{source.name}”</option>
            {mirror.offices
              .filter((o) => !takenOffices.has(o.id))
              .map((o) => (
                <option key={o.id} value={`office:${o.id}`}>
                  Office: {o.name}
                </option>
              ))}
          </optgroup>
        </select>
      ) : (
        <span
          className="w-full text-xs text-content-subtle sm:w-60 sm:text-right"
          title="Everybody in the Team is in its standard channels, so it cannot sort anybody. Use the Team, or a private channel."
        >
          Same people as the Team
        </span>
      )}
    </div>
  );
}

function differs(p: MirrorPerson) {
  return (
    (p.status !== 'in_step' && p.status !== 'not_linked' && p.status !== 'not_in_m365') ||
    p.office_differs_teams ||
    p.office_differs_m365
  );
}

type Filter = 'differences' | 'decisions' | 'moves' | 'everyone';

/** Here compared with Microsoft 365, and the one button that acts on it. */
export function Comparison({ mirror, busy, act }: { mirror: Mirror; busy: boolean; act: Act }) {
  const [filter, setFilter] = useState<Filter>('differences');
  const [search, setSearch] = useState('');
  const decisions = DECISIONS.reduce((n, s) => n + (mirror.counts[s] ?? 0), 0);
  const moves = mirror.counts.would_move ?? 0;
  const changes = moves + mirror.office_changes.length;
  const q = search.trim().toLowerCase();

  const shown = mirror.people.filter(
    (p) =>
      (filter === 'everyone'
        ? true
        : filter === 'decisions'
          ? DECISIONS.includes(p.status)
          : filter === 'moves'
            ? p.status === 'would_move'
            : differs(p)) &&
      (!q || p.name.toLowerCase().includes(q) || p.email.toLowerCase().includes(q)),
  );
  const differences = mirror.people.filter(differs).length;

  if (!mirror.sources.some((s) => s.link)) {
    return (
      <p className="rounded-md border border-dashed border-edge px-4 py-6 text-center text-sm text-content-muted">
        Nothing is in use yet. Choose a team or office for a Microsoft Team or channel first, and
        everybody's place is compared here.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-content-muted">
        Where each person is in GoalGetter, where Microsoft Teams puts them, and the office their
        Microsoft 365 profile names.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search people"
          aria-label="Search people"
          className="min-w-0 flex-1 rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content sm:max-w-xs"
        />
        <div className="flex flex-wrap gap-1" role="group" aria-label="Show">
          <Tab active={filter === 'differences'} onClick={() => setFilter('differences')}>
            Differences ({differences})
          </Tab>
          <Tab active={filter === 'decisions'} onClick={() => setFilter('decisions')}>
            Needs a decision ({decisions})
          </Tab>
          <Tab active={filter === 'moves'} onClick={() => setFilter('moves')}>
            Will move ({moves})
          </Tab>
          <Tab active={filter === 'everyone'} onClick={() => setFilter('everyone')}>
            Everyone ({mirror.people.length})
          </Tab>
        </div>
      </div>

      {shown.length === 0 ? (
        <p className="py-4 text-sm text-content-muted">
          {filter === 'differences' && !q ? 'Everybody matches Microsoft 365.' : 'Nobody here.'}
        </p>
      ) : (
        <ul className="max-h-[28rem] divide-y divide-edge overflow-y-auto rounded-md border border-edge">
          <li className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.7fr)_auto] gap-3 bg-surface-raised px-3 py-2 text-xs text-content-subtle md:grid">
            <span>Person</span>
            <span>Here</span>
            <span>Microsoft Teams</span>
            <span>M365 office</span>
            <span className="w-44 text-right">Status</span>
          </li>
          {shown.map((p) => (
            <PersonRow key={p.user_id} person={p} busy={busy} act={act} />
          ))}
        </ul>
      )}

      {mirror.office_changes.length > 0 && (
        <div className="text-sm">
          <p className="text-content">Applying also puts these teams in an office:</p>
          <ul className="mt-1 space-y-0.5 text-content-muted">
            {mirror.office_changes.map((c) => (
              <li key={c.team}>
                {c.team}: {c.from_office ?? 'No office'} → {c.to_office}
              </li>
            ))}
          </ul>
        </div>
      )}
      {mirror.not_yet_here > 0 && (
        <p className="text-xs text-content-subtle">
          {mirror.not_yet_here} {mirror.not_yet_here === 1 ? 'person' : 'people'} in linked Teams
          have no GoalGetter account yet — they join once approved.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-4 border-t border-edge pt-3">
        <button
          type="button"
          disabled={busy || changes === 0}
          onClick={() => void act('/apply', { method: 'POST' })}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {changes === 0 ? 'Nothing to apply' : `Apply ${changes} ${changes === 1 ? 'change' : 'changes'}`}
        </button>
        <Toggle
          label="Keep in step on every directory sync"
          hint="Moves only people the mirror placed. Hand moves are always left alone."
          checked={mirror.auto}
          disabled={busy}
          onChange={(on) => void act('/auto', { method: 'PUT', body: JSON.stringify({ on }) })}
        />
      </div>
    </div>
  );
}

function place(team: string | null, office: string | null) {
  if (!team && !office) return 'No team';
  return [team ?? 'No team', office].filter(Boolean).join(' · ');
}

function PersonRow({ person: p, busy, act }: { person: MirrorPerson; busy: boolean; act: Act }) {
  const tone =
    p.status === 'in_step'
      ? 'text-success'
      : DECISIONS.includes(p.status)
        ? 'text-warning'
        : p.status === 'would_move'
          ? 'text-brand'
          : 'text-content-muted';
  const teamsPlace =
    p.status === 'conflict' || p.teams_choices.length > 1
      ? p.teams_choices.join(' or ')
      : p.teams_team || p.teams_office
        ? place(p.teams_team, p.teams_office)
        : '—';

  return (
    <li className="grid grid-cols-1 gap-1 px-3 py-2 text-sm md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.7fr)_auto] md:items-center md:gap-3">
      <span className="min-w-0">
        <span className="block truncate text-content">{p.name}</span>
        {p.sources.length > 0 && (
          <span className="block truncate text-xs text-content-subtle">in {p.sources.join(', ')}</span>
        )}
      </span>
      <span className="truncate text-content-muted">
        <span className="text-content-subtle md:hidden">Here: </span>
        {place(p.team, p.office)}
      </span>
      <span className={`truncate ${p.office_differs_teams ? 'text-warning' : 'text-content-muted'}`}>
        <span className="text-content-subtle md:hidden">Teams: </span>
        {teamsPlace}
      </span>
      <span className={`truncate ${p.office_differs_m365 ? 'text-warning' : 'text-content-muted'}`}>
        <span className="text-content-subtle md:hidden">M365 office: </span>
        {p.m365_office || '—'}
      </span>
      <span className="flex flex-wrap items-center gap-2 md:w-44 md:justify-end">
        <span className={`text-xs ${tone}`}>{STATUS_LABEL[p.status]}</span>
        {(p.status === 'moved_by_hand' || p.status === 'only_here') && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void act(`/people/${p.user_id}/follow`, { method: 'POST' })}
            className="text-xs text-brand hover:underline disabled:opacity-60"
          >
            Follow Teams
          </button>
        )}
        {DECISIONS.includes(p.status) && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void act(`/people/${p.user_id}/keep`, { method: 'POST' })}
            className="text-xs text-brand hover:underline disabled:opacity-60"
          >
            Keep here
          </button>
        )}
        {p.status === 'kept' && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void act(`/people/${p.user_id}/keep`, { method: 'DELETE' })}
            className="text-xs text-content-muted hover:text-content disabled:opacity-60"
          >
            Undo
          </button>
        )}
      </span>
    </li>
  );
}
