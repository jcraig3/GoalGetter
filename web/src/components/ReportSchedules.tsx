import { dayAndTime } from '../time';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import Field from './Field';
import Select from './Select';
import { ask } from '../confirm';
import Loading from './Loading';
import { toast } from '../toast';
import MissingHint from './MissingHint';

interface Recipient {
  id: number;
  name: string;
  email: string;
}

export interface Schedule {
  id: number;
  name: string;
  cadence: 'weekdays' | 'weekly' | 'monthly';
  weekday: number | null;
  hour: number;
  recipients: Recipient[];
  enabled: boolean;
  last_sent_at: string | null;
  last_error: string | null;
}

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function hourLabel(hour: number): string {
  const suffix = hour < 12 ? 'am' : 'pm';
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve}${suffix}`;
}

/** "Every Monday at 8am", "Every weekday at 7am", "The 1st of each month at 9am". */
export function whenLabel(s: Pick<Schedule, 'cadence' | 'weekday' | 'hour'>): string {
  const at = hourLabel(s.hour);
  if (s.cadence === 'weekdays') return `Every weekday at ${at}`;
  if (s.cadence === 'monthly') return `The 1st of each month at ${at}`;
  return `Every ${WEEKDAYS[s.weekday ?? 0]} at ${at}`;
}

/**
 * The coaching digest, emailed on a schedule.
 *
 * **Each recipient gets their own.** It is worked out in the recipient's own
 * scope, the way this page is, so a manager added to an admin's schedule is
 * sent their team. Email only — a list of who is behind is a conversation, not
 * something to post in a channel.
 */
export default function ReportSchedules() {
  const [schedules, setSchedules] = useState<Schedule[] | null>(null);
  const [recipients, setRecipients] = useState<Recipient[]>([]);
  const [editing, setEditing] = useState<Schedule | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<number, string>>({});

  const load = useCallback(() => {
    api<Schedule[]>('/api/reporting/schedules')
      .then(setSchedules)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  // Whether email is set up, said rather than assumed (8.3).
  const [mail, setMail] = useState<{ ready: boolean; sending_from: string | null } | null>(null);
  useEffect(() => {
    api<{ ready: boolean; sending_from: string | null }>('/api/reporting/mail')
      .then(setMail)
      .catch(() => setMail(null));
  }, []);

  useEffect(() => {
    load();
    api<Recipient[]>('/api/reporting/recipients')
      .then(setRecipients)
      .catch(() => setRecipients([]));
  }, [load]);

  async function test(schedule: Schedule) {
    setTested((t) => ({ ...t, [schedule.id]: 'Sending…' }));
    try {
      const result = await api<{ ok: boolean; error: string | null }>(
        `/api/reporting/schedules/${schedule.id}/send`,
        { method: 'POST' },
      );
      setTested((t) => ({
        ...t,
        [schedule.id]: result.ok ? 'Sent to you — check your inbox.' : result.error ?? 'It did not send.',
      }));
    } catch (e) {
      setTested((t) => ({ ...t, [schedule.id]: e instanceof Error ? e.message : 'It did not send.' }));
    }
  }

  async function remove(schedule: Schedule) {
    if (!await ask(`Stop emailing “${schedule.name}”?`)) return;
    try {
      await api(`/api/reporting/schedules/${schedule.id}`, { method: 'DELETE' });
      toast('Schedule stopped');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove it.');
    }
  }

  if (!schedules) {
    return error ? (
      <p role="alert" className="text-sm text-danger">{error}</p>
    ) : (
      <Loading />
    );
  }

  return (
    <section className="space-y-4 rounded-lg border border-edge bg-surface p-6">
      <div>
        <h2 className="text-h3 text-content">Email the coaching digest</h2>
        <p className="mt-1 text-sm text-content-muted">
          The overview on this page — who is on pace, who is behind, and what catching up would
          take — sent on a schedule. Each person receives their own: a manager sees their team.
        </p>
        {mail?.ready ? (
          <p className="mt-2 text-sm text-success">
            Email is set up{mail.sending_from ? ` — sending from ${mail.sending_from}` : ''}.
          </p>
        ) : (
          <p className="mt-2 text-sm text-warning">
            It needs email set up under Integrations before anything is sent.
          </p>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {schedules.length > 0 && (
        <ul className="divide-y divide-edge rounded-md border border-edge">
          {schedules.map((s) => (
            <li key={s.id} className="px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <span className={s.enabled ? 'text-content' : 'text-content-muted'}>
                  {s.name}
                  {!s.enabled && <span className="ml-2 text-xs">off</span>}
                </span>
                <span className="flex gap-3 text-sm">
                  <button type="button" onClick={() => void test(s)} className="text-brand hover:underline">
                    Send me a test
                  </button>
                  <button type="button" onClick={() => setEditing(s)} className="text-content-muted hover:text-content">
                    Edit
                  </button>
                  <button type="button" onClick={() => void remove(s)} className="text-content-muted hover:text-danger">
                    Remove
                  </button>
                </span>
              </div>
              <p className="mt-0.5 text-xs text-content-muted">
                {whenLabel(s)} · to {s.recipients.map((r) => r.name).join(', ') || 'nobody'}
              </p>
              {s.last_error ? (
                <p className="mt-2 rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-content">
                  {s.last_error}
                </p>
              ) : (
                s.last_sent_at && (
                  <p className="mt-1 text-xs text-content-subtle">
                    Last sent {dayAndTime(s.last_sent_at)}
                  </p>
                )
              )}
              {tested[s.id] && (
                <p className="mt-1 text-xs text-content" aria-live="polite">{tested[s.id]}</p>
              )}
              {editing !== 'new' && editing?.id === s.id && (
                <ScheduleForm
                  schedule={s}
                  recipients={recipients}
                  onClose={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    load();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {editing === 'new' ? (
        <ScheduleForm
          recipients={recipients}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content hover:border-brand"
        >
          Schedule an email
        </button>
      )}
    </section>
  );
}

function ScheduleForm({
  schedule,
  recipients,
  onClose,
  onSaved,
}: {
  schedule?: Schedule;
  recipients: Recipient[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(schedule?.name ?? 'Coaching digest');
  const [cadence, setCadence] = useState<Schedule['cadence']>(schedule?.cadence ?? 'weekly');
  const [weekday, setWeekday] = useState(String(schedule?.weekday ?? 0));
  const [hour, setHour] = useState(String(schedule?.hour ?? 8));
  const [chosen, setChosen] = useState<number[]>(
    schedule?.recipients.map((r) => r.id) ?? (recipients.length === 1 ? [recipients[0]!.id] : []),
  );
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api(schedule ? `/api/reporting/schedules/${schedule.id}` : '/api/reporting/schedules', {
        method: schedule ? 'PATCH' : 'POST',
        body: JSON.stringify({
          name,
          cadence,
          weekday: Number(weekday),
          hour: Number(hour),
          recipient_ids: chosen,
          enabled,
        }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 space-y-4 rounded-md border border-edge bg-surface-hover p-4">
      <Field label="Name" value={name} onChange={setName} maxLength={80} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Select
          label="How often"
          value={cadence}
          onChange={(v) => setCadence(v as Schedule['cadence'])}
          options={[
            { value: 'weekdays', label: 'Every weekday' },
            { value: 'weekly', label: 'Once a week' },
            { value: 'monthly', label: 'The 1st of each month' },
          ]}
        />
        {cadence === 'weekly' && (
          <Select
            label="On"
            value={weekday}
            onChange={setWeekday}
            options={WEEKDAYS.map((day, i) => ({ value: String(i), label: day }))}
          />
        )}
        <Select
          label="At"
          value={hour}
          onChange={setHour}
          options={Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: hourLabel(h) }))}
          hint="In your organization’s time zone."
        />
      </div>

      <fieldset>
        <legend className="text-sm text-content-muted">Send to</legend>
        <div className="mt-2 grid gap-1 sm:grid-cols-2">
          {recipients.map((r) => (
            <label key={r.id} className="flex items-center gap-2 text-sm text-content">
              <input
                type="checkbox"
                checked={chosen.includes(r.id)}
                onChange={(e) =>
                  setChosen(e.target.checked ? [...chosen, r.id] : chosen.filter((id) => id !== r.id))
                }
              />
              {r.name}
              <span className="truncate text-xs text-content-subtle">{r.email}</span>
            </label>
          ))}
        </div>
        <p className="mt-1 text-xs text-content-subtle">
          Admins and managers only — it is a list of people to talk to.
        </p>
      </fieldset>

      {schedule && (
        <label className="flex items-center gap-2 text-sm text-content">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Sending
        </label>
      )}

      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">{error}</p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || !name.trim() || chosen.length === 0}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <MissingHint checks={[[!name.trim(), 'Name it to continue.'], [chosen.length === 0, 'Choose who receives it.']]} />
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-content-muted hover:text-content">
          Cancel
        </button>
      </div>
      <p className="text-xs text-content-subtle">
        The first one goes out at the next time it is due. Once it is saved, “Send me a test”
        beside it sends you one now.
      </p>
    </div>
  );
}
