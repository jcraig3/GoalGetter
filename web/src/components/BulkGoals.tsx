import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { api } from '../api';
import { useAuth } from '../auth';
import Avatar from './Avatar';
import Field from './Field';
import MetricValue from './MetricValue';
import Modal from './Modal';
import Select from './Select';
import { Tab } from './Tabs';

interface Option {
  id: number;
  name: string;
}

interface RosterRow {
  user_id: number;
  name: string;
  team_name: string | null;
  photo_digest: string | null;
  last_value: string;
  existing: { goal_id: number; target_value: string } | null;
}

interface Roster {
  group_name: string;
  metric_name: string;
  unit: string;
  decimal_places: number;
  unit_label: string | null;
  direction: string;
  period_label: string;
  last_period_label: string;
  suggested_target: string | null;
  people: RosterRow[];
}

const PERIODS = [
  { value: 'day', label: 'Today' },
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'quarter', label: 'This quarter' },
  { value: 'year', label: 'This year' },
];

/** "200.0000" → "200": the API's NUMERIC, as somebody would type it. */
const plain = (value: string) => String(Number(value));

/**
 * **One target for a team or an office, adjusted person by person** (6.12).
 *
 * Fill in the target once and everybody gets it; type over anybody's to give
 * them their own; untick anybody to leave them out. Last period's figure sits
 * beside each name, because the exceptions are argued from it. Somebody who
 * already has this goal is shown it, and saving changes it rather than giving
 * them a second one.
 */
export default function BulkGoals({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (said: string) => Promise<void>;
}) {
  const { user, can } = useAuth();
  const isAdmin = can('org.settings.edit');

  const [metrics, setMetrics] = useState<Option[]>([]);
  const [teams, setTeams] = useState<Option[]>([]);
  const [offices, setOffices] = useState<Option[]>([]);
  const [metricId, setMetricId] = useState('');
  const [groupType, setGroupType] = useState<'team' | 'office'>('team');
  const [groupId, setGroupId] = useState('');
  const [periodType, setPeriodType] = useState('month');

  const [roster, setRoster] = useState<Roster | null>(null);
  const [loading, setLoading] = useState(false);
  const [everyone, setEveryone] = useState('');
  //: A person's own target, where it differs from everyone's. Absent follows it.
  const [own, setOwn] = useState<Record<number, string>>({});
  const [left, setLeft] = useState<Set<number>>(new Set());
  const [name, setName] = useState('');
  const [recurring, setRecurring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      api<Option[]>('/api/metrics'),
      api<Option[]>('/api/teams'),
      isAdmin ? api<Option[]>('/api/offices') : Promise.resolve([]),
    ])
      .then(([m, t, o]) => {
        setMetrics(m);
        // A manager sets targets for their own team, so that is the only one
        // offered rather than a list where every other choice is refused.
        setTeams(isAdmin ? t : t.filter((team) => team.id === user?.team_id));
        setOffices(o);
        setMetricId((v) => v || String(m[0]?.id ?? ''));
        // Chosen, not assumed (Q2-14): an admin starts on "Choose a team…",
        // not on whichever sorts first; a manager has one team, theirs.
        setGroupId((v) => v || (isAdmin ? '' : String(user?.team_id ?? '')));
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load the options.'));
  }, [isAdmin, user?.team_id]);

  // The roster follows the choices above it.
  useEffect(() => {
    if (!metricId || !groupId) return;
    let stale = false;
    setLoading(true);
    api<Roster>('/api/goals/bulk/roster', {
      method: 'POST',
      body: JSON.stringify({
        metric_id: Number(metricId),
        group_type: groupType,
        group_id: Number(groupId),
        period_type: periodType,
      }),
    })
      .then((next) => {
        if (stale) return;
        setRoster(next);
        setOwn({});
        setLeft(new Set());
        setEveryone(next.suggested_target ? plain(next.suggested_target) : '');
        setError(null);
      })
      .catch((e) => !stale && setError(e instanceof Error ? e.message : 'Could not load the people.'))
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
  }, [metricId, groupType, groupId, periodType]);

  function chooseGroup(type: 'team' | 'office') {
    setGroupType(type);
    setGroupId('');
    setRoster(null);
  }

  const format = roster && {
    unit: roster.unit,
    decimal_places: roster.decimal_places,
    unit_label: roster.unit_label,
  };

  /** What each included person will be set to, and what that does. */
  const plan = useMemo(() => {
    if (!roster) return [];
    return roster.people.map((person) => {
      const target = (own[person.user_id] ?? everyone).trim();
      const included = !left.has(person.user_id);
      const valid = Number(target) > 0;
      const change = !included
        ? 'left out'
        : !valid
          ? 'needs a target'
          : !person.existing
            ? 'new'
            : Number(person.existing.target_value) === Number(target)
              ? 'unchanged'
              : 'update';
      return { person, target, included, valid, change };
    });
  }, [roster, own, left, everyone]);

  const counts = {
    new: plan.filter((p) => p.change === 'new').length,
    update: plan.filter((p) => p.change === 'update').length,
    missing: plan.filter((p) => p.change === 'needs a target').length,
    out: plan.filter((p) => p.change === 'left out').length,
  };
  const ready = counts.missing === 0 && counts.new + counts.update > 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!roster || !ready) return;
    setBusy(true);
    setError(null);
    try {
      const done = await api<{ created: number; updated: number }>('/api/goals/bulk', {
        method: 'POST',
        body: JSON.stringify({
          metric_id: Number(metricId),
          group_type: groupType,
          group_id: Number(groupId),
          period_type: periodType,
          name: name.trim() || null,
          recurring,
          rows: plan
            .filter((p) => p.included && p.valid)
            .map((p) => ({ user_id: p.person.user_id, target_value: p.target })),
        }),
      });
      await onSaved(summary(done.created, done.updated, roster.group_name));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set those goals.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Set goals for a group"
      description="One target for everybody, with anybody's own number where it should differ."
      onClose={onClose}
      wide
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <Select
            label="Metric"
            value={metricId}
            onChange={setMetricId}
            options={metrics.map((m) => ({ value: String(m.id), label: m.name }))}
          />
          <div>
            <span className="block text-sm text-content-muted">For</span>
            <div className="mt-1 flex gap-2">
              <Tab active={groupType === 'team'} onClick={() => chooseGroup('team')}>
                A team
              </Tab>
              {isAdmin && (
                <Tab active={groupType === 'office'} onClick={() => chooseGroup('office')}>
                  An office
                </Tab>
              )}
            </div>
          </div>
          <Select
            label="Period"
            value={periodType}
            onChange={setPeriodType}
            options={PERIODS}
          />
        </div>

        <Select
          label={groupType === 'team' ? 'Team' : 'Office'}
          value={groupId}
          onChange={setGroupId}
          options={[
            { value: '', label: groupType === 'team' ? 'Choose a team…' : 'Choose an office…' },
            ...(groupType === 'team' ? teams : offices).map((g) => ({
              value: String(g.id),
              label: g.name,
            })),
          ]}
        />

        <Field
          label="Target for everyone"
          value={everyone}
          onChange={setEveryone}
          numeric={{ decimals: 4, min: 0 }}
          hint={
            roster?.suggested_target
              ? `Suggested from ${roster.group_name}'s ${roster.last_period_label}: a little past the typical figure. Type over anybody's below to give them their own.`
              : 'Type over anybody’s below to give them their own.'
          }
        />

        {/* **Only the people who are selling** (8.2): the grid ticked all 93,
            including everyone at $0 last period and Jarvis Bot. */}
        {roster && roster.people.some((p) => !Number(p.last_value ?? 0)) && (
          <button
            type="button"
            onClick={() =>
              setLeft(new Set(roster.people.filter((p) => !Number(p.last_value ?? 0)).map((p) => p.user_id)))
            }
            className="text-sm text-brand hover:underline"
          >
            Leave out the {roster.people.filter((p) => !Number(p.last_value ?? 0)).length} who recorded nothing in{' '}
            {roster.last_period_label}
          </button>
        )}

        {roster && format && (
          <div className="overflow-hidden rounded-lg border border-edge">
            <table className="w-full text-sm">
              <thead className="bg-surface text-left text-xs text-content-subtle">
                <tr>
                  <th className="w-10 px-3 py-2">
                    <span className="sr-only">Include</span>
                  </th>
                  <th className="px-3 py-2 font-medium">Person</th>
                  <th className="px-3 py-2 text-right font-medium">{roster.last_period_label}</th>
                  <th className="w-40 px-3 py-2 font-medium">Target</th>
                  <th className="hidden w-36 px-3 py-2 font-medium sm:table-cell">
                    <span className="sr-only">What saving does</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-edge">
                {plan.map(({ person, included, change }) => (
                  <tr key={person.user_id} className={included ? '' : 'opacity-50'}>
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label={`Include ${person.name}`}
                        checked={included}
                        onChange={(e) =>
                          setLeft((was) => {
                            const next = new Set(was);
                            if (e.target.checked) next.delete(person.user_id);
                            else next.add(person.user_id);
                            return next;
                          })
                        }
                        className="accent-brand"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <Avatar name={person.name} digest={person.photo_digest} />
                        <span className="min-w-0">
                          <span className="block truncate text-content">{person.name}</span>
                          {groupType === 'office' && person.team_name && (
                            <span className="block truncate text-xs text-content-subtle">
                              {person.team_name}
                            </span>
                          )}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right text-content-muted">
                      <MetricValue value={person.last_value} format={format} />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        inputMode="decimal"
                        aria-label={`Target for ${person.name}`}
                        disabled={!included}
                        value={own[person.user_id] ?? ''}
                        placeholder={everyone || '—'}
                        onChange={(e) => {
                          const value = e.target.value.replace(/[^0-9.]/g, '');
                          setOwn((was) => {
                            const next = { ...was };
                            if (value === '') delete next[person.user_id];
                            else next[person.user_id] = value;
                            return next;
                          });
                        }}
                        className={`w-full rounded-md border bg-bg px-2 py-1 text-right tabular-nums text-content outline-none focus:border-brand ${
                          own[person.user_id] !== undefined ? 'border-brand' : 'border-edge'
                        }`}
                      />
                    </td>
                    <td className="hidden px-3 py-2 text-xs sm:table-cell">
                      <Change change={change} existing={person.existing} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {roster.people.length === 0 && (
              <p className="px-3 py-6 text-center text-sm text-content-muted">
                Nobody working is in {roster.group_name}.
              </p>
            )}
          </div>
        )}
        {loading && !roster && <p className="text-sm text-content-muted">Loading the people…</p>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Name"
            value={name}
            onChange={setName}
            required={false}
            hint="Optional, and the same on every goal made here."
          />
          <label className="flex items-start gap-2 self-center text-sm text-content-muted">
            <input
              type="checkbox"
              checked={recurring}
              onChange={(e) => setRecurring(e.target.checked)}
              className="mt-0.5 accent-brand"
            />
            <span>
              Repeat every period
              <span className="block text-xs text-content-subtle">
                For the new goals. Each person&rsquo;s can be changed on its own afterwards.
              </span>
            </span>
          </label>
        </div>

        {error && (
          <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={busy || !ready}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Set goals'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Cancel
          </button>
          {roster && (
            <span className="text-xs text-content-muted" data-testid="bulk-summary">
              {counts.missing > 0
                ? `${counts.missing} ${counts.missing === 1 ? 'person needs' : 'people need'} a target.`
                : plannedWords(counts)}
            </span>
          )}
        </div>
      </form>
    </Modal>
  );
}

function Change({
  change,
  existing,
}: {
  change: string;
  existing: RosterRow['existing'];
}) {
  if (change === 'new') return <span className="text-success">New goal</span>;
  if (change === 'update')
    return <span className="text-warning">Changes from {Number(existing!.target_value).toLocaleString()}</span>;
  if (change === 'unchanged') return <span className="text-content-subtle">Already set</span>;
  if (change === 'needs a target') return <span className="text-content-subtle">No target yet</span>;
  return <span className="text-content-subtle">Left out</span>;
}

/** "Makes 8 goals and changes 2. 1 left out." */
export function plannedWords(counts: { new: number; update: number; out: number }): string {
  const parts: string[] = [];
  if (counts.new) parts.push(`makes ${counts.new} goal${counts.new === 1 ? '' : 's'}`);
  if (counts.update) parts.push(`changes ${counts.update}`);
  const said = parts.length ? `Saving ${parts.join(' and ')}.` : 'Nothing to change.';
  return counts.out ? `${said} ${counts.out} left out.` : said;
}

/** The toast after saving. */
export function summary(created: number, updated: number, group: string): string {
  const parts: string[] = [];
  if (created) parts.push(`${created} goal${created === 1 ? '' : 's'} set`);
  if (updated) parts.push(`${updated} changed`);
  return `${parts.join(', ') || 'Nothing changed'} for ${group}`;
}
