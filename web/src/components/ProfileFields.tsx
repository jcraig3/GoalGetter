import { useState } from 'react';

import { api } from '../api';
import Select from './Select';

/**
 * The parts of a profile that belong to the person rather than the roster.
 *
 * **Its own control because it saves on its own.** Role, team and name are set
 * by whoever runs the roster and are read-only wherever this appears. These
 * follow the same rule as a photograph — yours, or anybody's if you run the
 * place — and have no form around them to submit.
 *
 * **A start date is not here**, and the split is the point: a birthday is
 * theirs, and when somebody joined is a company fact. That one sits with team
 * and role, where a manager sets it.
 */
export interface Profile {
  nickname: string;
  birthday_month: number | null;
  birthday_day: number | null;
}

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/** Days offered for a month, so 31 February cannot be chosen at all. */
function daysIn(month: number | null): number {
  if (month === null) return 31;
  // A leap year, so 29 February is offerable — somebody born on one has a
  // birthday every year and the calendar is what is inconvenient.
  return new Date(2028, month, 0).getDate();
}

export default function ProfileFields({
  userId,
  profile,
  onSaved,
}: {
  userId: number;
  profile: Profile;
  onSaved?: () => void;
}) {
  const [nickname, setNickname] = useState(profile.nickname);
  const [month, setMonth] = useState<number | null>(profile.birthday_month);
  const [day, setDay] = useState<number | null>(profile.birthday_day);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changed =
    nickname.trim() !== profile.nickname ||
    month !== profile.birthday_month ||
    day !== profile.birthday_day;

  // Half a birthday is a date nothing can mark, so it cannot be saved — said
  // by disabling the button rather than by a message after the fact.
  const halfADate = (month === null) !== (day === null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/users/${userId}/profile`, {
        method: 'PATCH',
        body: JSON.stringify({
          nickname: nickname.trim(),
          birthday_month: month,
          birthday_day: day,
        }),
      });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor="nickname" className="block text-sm text-content-muted">
          Nickname
        </label>
        <input
          id="nickname"
          type="text"
          value={nickname}
          maxLength={40}
          placeholder="Optional"
          onChange={(e) => {
            setNickname(e.target.value);
            setSaved(false);
          }}
          className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none focus:border-brand"
        />
        <p className="mt-1 text-xs text-content-subtle">
          {/* Said, because setting one and seeing nothing change is the obvious
              way to conclude it does not work. */}
          Used on the TVs when your organization has chosen to show
          nicknames.
        </p>
      </div>

      <div>
        <span className="block text-sm text-content-muted">Birthday</span>
        <div className="mt-1 grid grid-cols-2 gap-2">
          <Select
            label="Month"
            value={month === null ? '' : String(month)}
            onChange={(v) => {
              const next = v === '' ? null : Number(v);
              setMonth(next);
              // A day that does not exist in the new month would silently
              // become a date nothing marks.
              if (next !== null && day !== null && day > daysIn(next)) {
                setDay(daysIn(next));
              }
              if (next === null) setDay(null);
              setSaved(false);
            }}
            options={[
              { value: '', label: 'Not set' },
              ...MONTHS.map((name, index) => ({
                value: String(index + 1),
                label: name,
              })),
            ]}
          />
          <Select
            label="Day"
            value={day === null ? '' : String(day)}
            onChange={(v) => {
              setDay(v === '' ? null : Number(v));
              setSaved(false);
            }}
            options={[
              { value: '', label: 'Not set' },
              ...Array.from({ length: daysIn(month) }, (_, i) => ({
                value: String(i + 1),
                label: String(i + 1),
              })),
            ]}
          />
        </div>
        <p className="mt-1 text-xs text-content-subtle">
          {/* Stated plainly, because a birthday field that quietly wanted a year
              would be the one thing on this page people hesitate over. */}
          The day and month only — no year is stored. A birthday falling on a
          weekend is marked on the Friday before.
        </p>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy || !changed || halfADate}
          className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
        >
          {busy ? 'Saving…' : saved ? 'Saved' : 'Save'}
        </button>
        {halfADate && (
          <span className="text-xs text-content-muted">
            A birthday needs both a month and a day.
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
