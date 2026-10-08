import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import MediaField from '../components/MediaField';
import { toast } from '../toast';
import { recordable } from '../recordable';
import EmptyState from '../components/EmptyState';
import Field, { forInput } from '../components/Field';
import MessageField from '../components/MessageField';
import IconButton from '../components/IconButton';
import {
  PauseIcon,
  PencilIcon,
  PlayIcon,
  TrashIcon,
} from '../components/icons';
import MetricValue from '../components/MetricValue';
import Modal from '../components/Modal';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import MissingHint from '../components/MissingHint';
import CelebrationPreview, { startingNow, type CelebrationShape } from '../components/CelebrationPreview';
import type { Celebration } from './celebrationQueue';
import PreviewOnTv from '../components/PreviewOnTv';
import SoundPicker, { DefaultSounds } from '../components/SoundPicker';
import { RULE_TEMPLATES, metricFor, type RuleTemplate } from './starterTemplates';
import { useFocusRow, useOpenFromUrl } from '../urlIntent';

interface Rule {
  id: number;
  name: string;
  metric_id: number;
  metric_name: string;
  comparator: string;
  threshold: string;
  scope: string;
  scope_team_id: number | null;
  scope_team_name: string | null;
  /** What the announcement says, one alternative per line. Empty is the
   *  fixed shape. */
  message: string;
  media_url: string | null;
  media_kind: string | null;
  media_start_seconds: number | null;
  allow_personal_media: boolean;
  enabled: boolean;
  /** Points per matching piece of work. See `app/points.py`. */
  points: number;
}

interface Metric {
  id: number;
  name: string;
  unit: string;
  aggregation?: string;
  decimal_places?: number;
  unit_label?: string | null;
}

interface Team {
  id: number;
  name: string;
}

/**
 * Rules that celebrate a piece of work rather than a goal.
 *
 * A goal is a target over a period. "Closed a deal over $5,000" is neither,
 * and it is most of what a sales floor actually celebrates — this is how that
 * becomes automatic instead of waiting for a manager to notice.
 *
 * Admin only, and its own page rather than a panel on Achievements: a rule
 * fires on **every screen in the building every time it matches**, so setting
 * the bar too low does not fail loudly, it just turns the wall into noise.
 */
export default function AchievementRules() {
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [editing, setEditing] = useState<Rule | null>(null);
  const [creating, setCreating] = useState(false);
  const [template, setTemplate] = useState<RuleTemplate | null>(null);
  const [error, setError] = useState<string | null>(null);
  useOpenFromUrl('new', () => setCreating(true));
  useFocusRow(rules !== null);

  const load = useCallback(async () => {
    try {
      const [r, m, t] = await Promise.all([
        api<Rule[]>('/api/achievement-rules'),
        api<Metric[]>('/api/metrics'),
        api<Team[]>('/api/teams'),
      ]);
      setRules(r);
      setMetrics(recordable(m));
      setTeams(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load rules.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(rule: Rule) {
    // Names disable as the reversible option, because that is the one somebody
    // reaching for this button usually wants.
    if (
      !await ask(
        `Delete "${rule.name}"?

Its past announcements go with it, from the bells and the Recognition feed. To stop it but keep what it announced, disable it instead.

Points it has already paid stay.`,
      )
    )
      return;
    try {
      await api(`/api/achievement-rules/${rule.id}`, { method: 'DELETE' });
      toast('Rule deleted');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete that.');
    }
  }

  async function toggle(rule: Rule) {
    try {
      await api(`/api/achievement-rules/${rule.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ ...toWrite(rule), enabled: !rule.enabled }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    }
  }

  return (
    <>
      <PageHeader
        title="Celebrations"
        description="What gets celebrated automatically. A rule turns a single piece of work into an announcement on the wall as soon as the number arrives, without waiting for a goal."
        actions={
          <button
            onClick={() => setCreating(true)}
            className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
          >
            New rule
          </button>
        }
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {/* Said once, where the rules are made. A rule that fires ten times a day
          is not a celebration, it is wallpaper. */}
      <p className="mb-6 max-w-2xl text-sm text-content-muted">
        A rule fires on every screen every time it matches, so set the bar where
        it means something. Rules never apply to work done before they were
        created — nothing you add here will announce last month.{' '}
        <Link to="/announcements" className="text-brand hover:underline">
          See what has fired
        </Link>
        .
      </p>

      {rules === null ? (
        <Loading />
      ) : rules.length === 0 ? (
        <EmptyState
          title="No rules yet"
          description="A rule turns a single piece of work into a celebration — a deal over a certain size, a response under a certain time. Start from one of these, set from your own numbers:"
          action={
            <TemplateButtons
              metrics={metrics}
              onPick={(t) => {
                setTemplate(t);
                setCreating(true);
              }}
            />
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-edge bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-caption uppercase tracking-wide text-content-subtle">
                <th className="px-4 py-3 font-medium">Rule</th>
                <th className="px-4 py-3 font-medium">Fires when</th>
                <th className="px-4 py-3 font-medium">Applies to</th>
                <th className="px-4 py-3 font-medium">Plays</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr
                  key={rule.id}
                  id={`row-${rule.id}`}
                  className={`border-b border-edge last:border-0 ${
                    rule.enabled ? '' : 'opacity-50'
                  }`}
                >
                  <td className="px-4 py-3 text-content">
                    <span className="flex items-center gap-2">
                      {rule.name}
                      {!rule.enabled && (
                        <span className="shrink-0 rounded-full bg-surface-raised px-2 py-0.5 text-xs text-content-muted">
                          paused
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-content-muted">
                    {rule.metric_name}{' '}
                    {rule.comparator === 'gte' ? 'at least' : 'at most'}{' '}
                    {/* In the metric's own unit — "$350", not "350" (Q2-2). */}
                    <MetricValue
                      value={rule.threshold}
                      format={{
                        unit: metrics.find((m) => m.id === rule.metric_id)?.unit ?? 'number',
                        decimal_places:
                          Number(rule.threshold) % 1 === 0
                            ? 0
                            : (metrics.find((m) => m.id === rule.metric_id)?.decimal_places ?? 2),
                        unit_label: metrics.find((m) => m.id === rule.metric_id)?.unit_label ?? null,
                      }}
                    />
                  </td>
                  <td className="px-4 py-3 text-content-muted">
                    {rule.scope === 'team'
                      ? (rule.scope_team_name ?? 'a team')
                      : 'Everyone'}
                  </td>
                  <td className="px-4 py-3 text-content-subtle">
                    {rule.allow_personal_media
                      ? rule.media_kind
                        ? `their own, else ${rule.media_kind}`
                        : 'Walk-up only — others hear nothing'
                      : (rule.media_kind ?? 'nothing')}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      {/* Pause and play rather than a power symbol: the same
                          icon in both states tells you nothing, and these two
                          say which way the click goes. A disabled rule is
                          paused — it will announce again when you resume it. */}
                      <IconButton
                        label={rule.enabled ? 'Disable' : 'Enable'}
                        icon={
                          rule.enabled ? (
                            <PauseIcon className="size-4" />
                          ) : (
                            <PlayIcon className="size-4" />
                          )
                        }
                        onClick={() => void toggle(rule)}
                      />
                      <IconButton
                        label="Edit"
                        icon={<PencilIcon className="size-4" />}
                        onClick={() => setEditing(rule)}
                      />
                      <IconButton
                        label="Delete"
                        icon={<TrashIcon className="size-4" />}
                        danger
                        onClick={() => void remove(rule)}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* What plays when a rule or a win has nothing of its own (6.17) —
          under the rules, which are what the page is for (8.3). */}
      <div className="mt-8">
        <DefaultSounds />
      </div>

      {(creating || editing) && (
        <RuleForm
          rule={editing}
          template={editing ? null : template}
          metrics={metrics}
          teams={teams}
          onClose={() => {
            setCreating(false);
            setEditing(null);
            setTemplate(null);
          }}
          onSaved={async () => {
            toast(editing ? 'Rule saved' : 'Rule created');
            setError(null);
            setCreating(false);
            setEditing(null);
            setTemplate(null);
            await load();
          }}
          onError={setError}
        />
      )}
    </>
  );
}

/** The write shape, so a PATCH that only means to flip `enabled` still sends a
 *  complete rule — the API replaces rather than merges. */
function toWrite(rule: Rule) {
  return {
    name: rule.name,
    metric_id: rule.metric_id,
    comparator: rule.comparator,
    threshold: rule.threshold,
    scope: rule.scope,
    scope_team_id: rule.scope_team_id,
    message: rule.message,
    media_url: rule.media_url,
    media_start_seconds: rule.media_start_seconds,
    allow_personal_media: rule.allow_personal_media,
    enabled: rule.enabled,
    points: rule.points,
  };
}

function RuleForm({
  rule,
  template,
  metrics,
  teams,
  onClose,
  onSaved,
  onError,
}: {
  rule: Rule | null;
  /** What a new rule starts from (6.4). Ignored when editing. */
  template?: RuleTemplate | null;
  metrics: Metric[];
  teams: Team[];
  onClose: () => void;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState(rule?.name ?? '');
  const [metricId, setMetricId] = useState(String(rule?.metric_id ?? ''));
  const [comparator, setComparator] = useState(rule?.comparator ?? 'gte');
  const [threshold, setThreshold] = useState(forInput(rule?.threshold));
  const [scope, setScope] = useState(rule?.scope ?? 'everyone');
  const [teamId, setTeamId] = useState(String(rule?.scope_team_id ?? ''));
  const [message, setMessage] = useState(rule?.message ?? '');
  const [mediaUrl, setMediaUrl] = useState(rule?.media_url ?? '');
  const [allowPersonal, setAllowPersonal] = useState(
    rule?.allow_personal_media ?? true,
  );
  const [points, setPoints] = useState(String(rule?.points ?? 10));
  const [busy, setBusy] = useState(false);
  const [tried, setTried] = useState<RulePreview | null>(null);
  const [trying, setTrying] = useState(false);
  const [tryError, setTryError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<Celebration | null>(null);

  const body = () =>
    JSON.stringify({
      name,
      metric_id: Number(metricId),
      comparator,
      threshold,
      scope,
      scope_team_id: scope === 'team' ? Number(teamId) : null,
      message,
      media_url: mediaUrl.trim() || null,
      allow_personal_media: allowPersonal,
      enabled: rule?.enabled ?? true,
      points: Number(points) || 0,
    });

  // A result for a rule that has since been changed is a result for a
  // different rule, so it goes as soon as anything it depends on does.
  useEffect(() => {
    setTried(null);
    setTryError(null);
  }, [name, metricId, comparator, threshold, scope, teamId, message, mediaUrl, allowPersonal]);

  /**
   * **Tried before it is saved** (5j): how often it would have fired last
   * week, and the celebration itself. The hint under Threshold says a rule
   * that fires ten times a day is wallpaper; this is how somebody finds out
   * whether theirs is, before the floor does.
   */
  async function tryIt(play: boolean) {
    setTrying(true);
    setTryError(null);
    try {
      const found = await api<RulePreview>('/api/achievement-rules/preview', {
        method: 'POST',
        body: body(),
      });
      setTried(found);
      if (play) setPlaying(startingNow(found.celebration));
    } catch (e) {
      setTryError(e instanceof Error ? e.message : 'Could not try that rule.');
    } finally {
      setTrying(false);
    }
  }

  /**
   * **A starter, filled in from this organization's own numbers** (6.4).
   * The name, message and points are the template's; the metric is the first
   * of the right kind; and the bar is whatever would have fired about as often
   * as the template means, over the last four weeks — then Check shows exactly
   * what it would do.
   */
  const [starting, setStarting] = useState(false);
  const [startNote, setStartNote] = useState<string | null>(null);
  async function startFrom(t: RuleTemplate) {
    setName(t.name);
    setMessage(t.message);
    setPoints(String(t.points));
    setStartNote(null);
    setStarting(true);
    try {
      // By unit: the server picks the busiest metric of that kind, which is
      // the one the floor is watching — not merely the first alphabetically.
      const found = await api<{
        metric_id: number | null;
        threshold: string | null;
        would_fire: number;
        weeks: number;
      }>(`/api/achievement-rules/suggest?unit=${t.unit}&per_week=${t.perWeek}`);
      const metric =
        metrics.find((m) => m.id === found.metric_id) ?? metricFor(t, metrics);
      if (!metric) {
        setStartNote(
          t.unit === 'currency'
            ? 'No money metric yet — choose what it measures.'
            : 'No count metric yet — choose what it measures.',
        );
        return;
      }
      setMetricId(String(metric.id));
      if (found.threshold === null || found.metric_id !== metric.id) {
        setStartNote(`No ${metric.name} in the last four weeks to set the bar from — set it yourself.`);
      } else {
        setThreshold(forInput(found.threshold));
        setStartNote(
          `Set from your own ${metric.name}: it would have fired ${found.would_fire} ${found.would_fire === 1 ? 'time' : 'times'} in the last ${found.weeks} weeks.`,
        );
      }
    } catch {
      setStartNote('Could not suggest a bar — set it yourself.');
    } finally {
      setStarting(false);
    }
  }
  const started = useRef(false);
  useEffect(() => {
    if (!rule && template && !started.current && metrics.length) {
      started.current = true;
      void startFrom(template);
    }
    // Once, when the metrics it needs have arrived.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template, metrics]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api(rule ? `/api/achievement-rules/${rule.id}` : '/api/achievement-rules', {
        method: rule ? 'PATCH' : 'POST',
        body: body(),
      });
      await onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={rule ? 'Edit rule' : 'New rule'}
      description="Fires as soon as a matching piece of work arrives: straight away for a webhook or a correction, and at the next read for a scheduled source."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        {!rule && (
          <div>
            <p className="mb-2 text-xs text-content-subtle">Start from</p>
            <TemplateButtons metrics={metrics} onPick={(t) => void startFrom(t)} />
            {(starting || startNote) && (
              <p className="mt-2 text-xs text-content-muted" role="status">
                {starting ? 'Working out a bar from your numbers…' : startNote}
              </p>
            )}
          </div>
        )}
        <Field
          label="Name"
          value={name}
          onChange={setName}
          maxLength={120}
          hint="What the screen says. 'Big deal closed' beats 'revenue >= 5000'."
        />

        <Select label="Measure" value={metricId} onChange={setMetricId}>
          <option value="">Choose a metric…</option>
          {metrics.map((metric) => (
            <option key={metric.id} value={metric.id}>
              {metric.name}
            </option>
          ))}
        </Select>

        <Select label="Fires when the value is" value={comparator} onChange={setComparator}>
          <option value="gte">at least</option>
          <option value="lte">at most</option>
        </Select>

        <Field
          label="Threshold"
          value={threshold}
          onChange={setThreshold}
          numeric={{ decimals: 2 }}
          hint="Set it where it means something. A rule that fires ten times a day is wallpaper."
        />

        <Field
          label="Points"
          value={points}
          onChange={setPoints}
          numeric={{ decimals: 0 }}
          hint="Paid every time this fires, so it is worth less than a goal. Zero celebrates it without putting it in the economy."
        />

        <Select label="Applies to" value={scope} onChange={setScope}>
          <option value="everyone">Everyone</option>
          <option value="team">One team</option>
        </Select>

        {scope === 'team' && (
          <Select label="Team" value={teamId} onChange={setTeamId}>
            <option value="">Choose a team…</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </Select>
        )}

        <MessageField
          value={message}
          onChange={setMessage}
          fallback="Peter Parker — $6,200"
        />

        {/* **A sound, or a link** (6.17): one column says what plays, so the
            two are one choice — picking a sound clears a link and typing a
            link clears the sound. */}
        <SoundPicker
          label="Sound"
          value={mediaUrl.startsWith('asset:') ? mediaUrl : ''}
          onChange={setMediaUrl}
          hint={
            allowPersonal
              ? 'Played for anyone who has not chosen their own walk-up music.'
              : 'Played for everyone, whatever they have chosen for themselves.'
          }
        />

        <MediaField
          label="Or show a video or picture (optional)"
          value={mediaUrl.startsWith('asset:') ? '' : mediaUrl}
          onChange={setMediaUrl}
          kinds={['video', 'image']}
          link="Or paste a YouTube link or GIF"
          hint={
            allowPersonal
              ? "A YouTube link or a GIF, instead of a sound. Leave both empty and only people with their own walk-up get anything."
              : 'A YouTube link or a GIF, instead of a sound. Leave both empty for no sound at all — the announcement still appears on screen.'
          }
        />

        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={allowPersonal}
            onChange={(e) => setAllowPersonal(e.target.checked)}
            className="mt-0.5 size-4 shrink-0 accent-brand"
          />
          <span className="min-w-0">
            <span className="block text-sm text-content">
              Let people use their own walk-up music
            </span>
            <span className="block text-xs text-content-subtle">
              {/* Said as an effect rather than a rule, because "precedence" is
                  not what somebody setting this up is thinking about. */}
              {allowPersonal
                ? 'Anyone who has set their own hears it; everybody else gets the clip above.'
                : 'Everybody hears the clip above, whatever they have chosen for themselves.'}
            </span>
          </span>
        </label>

        <div className="rounded-md border border-edge p-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void tryIt(false)}
              disabled={trying || !name || !metricId || !threshold}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              {trying ? 'Checking…' : 'Check the last 4 weeks'}
            </button>
            <button
              type="button"
              onClick={() => void tryIt(true)}
              disabled={trying || !name || !metricId || !threshold}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              ▶ Play celebration
            </button>
            <PreviewOnTv
              disabled={!name || !metricId || !threshold}
              send={(displayId) =>
                api(`/api/achievement-rules/preview/tv/${displayId}`, {
                  method: 'POST',
                  body: body(),
                })
              }
            />
          </div>
          {tryError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {tryError}
            </p>
          )}
          {tried && (
            <TriedLine tried={tried} metric={metrics.find((m) => String(m.id) === metricId)?.name} />
          )}
          {!tried && !tryError && (
            <p className="mt-2 text-xs text-content-subtle">
              Nothing is saved or announced: it is tried against the last four weeks,
              and plays on this screen, or on one TV you choose.
            </p>
          )}
        </div>

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={busy || !name || !metricId || !threshold}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : rule ? 'Save' : 'Create rule'}
          </button>
          <MissingHint checks={[[!name, 'Name the rule to continue.'], [!metricId, 'Choose a metric.'], [!threshold, 'Set the bar it has to reach.']]} />
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Cancel
          </button>
        </div>
      </form>
      {playing && (
        <CelebrationPreview
          celebration={playing}
          label="Rule preview"
          onClose={() => setPlaying(null)}
        />
      )}
    </Modal>
  );
}

/** What `POST /achievement-rules/preview` says a rule would have done. */
interface RulePreview {
  fired: number;
  people: number;
  days: number;
  /** Numbers of the metric in the window at all (Q2-4). */
  recorded?: number;
  celebration: CelebrationShape;
}

/** More than this many a day and the rule is wallpaper, by the form's own hint. */
const NOISY_PER_DAY = 3;

/** "Would have fired 12 times in the last 7 days, for 5 people." */
function TriedLine({ tried, metric }: { tried: RulePreview; metric?: string }) {
  const span = tried.days % 7 === 0 ? `${tried.days / 7} weeks` : `${tried.days} days`;
  // **No numbers is not a high bar** (Q2-4): with nothing arriving, every bar
  // "would not have fired", and advising a lower one blames the wrong thing.
  if (tried.recorded === 0) {
    return (
      <p className="mt-2 text-sm text-warning" role="status">
        No {metric ?? 'numbers for this metric'} arrived in the last {span}, so the check has
        nothing to try it on.
      </p>
    );
  }
  if (tried.fired === 0) {
    return (
      <p className="mt-2 text-sm text-content-muted" role="status">
        Would not have fired in the last {span}. Fine for a rare win; lower the bar if it
        should be heard more often.
      </p>
    );
  }
  const perDay = tried.fired / tried.days;
  const noisy = perDay > NOISY_PER_DAY;
  const perWeek = Math.round((tried.fired / tried.days) * 7);
  return (
    <p className={`mt-2 text-sm ${noisy ? 'text-warning' : 'text-content'}`} role="status">
      Would have fired {tried.fired} {tried.fired === 1 ? 'time' : 'times'} in the
      last {span}{perWeek >= 1 ? ` (about ${perWeek} a week)` : ''}, for {tried.people}{' '}
      {tried.people === 1 ? 'person' : 'people'}.
      {noisy &&
        ` About ${Math.round(perDay)} a day — the room will stop looking up. Raise the bar?`}
    </p>
  );
}

/** The starter rules, as buttons (6.4). */
function TemplateButtons({
  metrics,
  onPick,
}: {
  metrics: Metric[];
  onPick: (template: RuleTemplate) => void;
}) {
  return (
    <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
      {RULE_TEMPLATES.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onPick(t)}
          title={metricFor(t, metrics) ? t.blurb : `${t.blurb} — needs a ${t.unit === 'currency' ? 'money' : 'count'} metric`}
          className="rounded-full border border-edge px-3 py-1 text-sm text-content transition-colors hover:border-brand hover:bg-surface-hover"
        >
          {t.name}
        </button>
      ))}
    </div>
  );
}
