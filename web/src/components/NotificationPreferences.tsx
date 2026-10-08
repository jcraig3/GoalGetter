import { useEffect, useState } from 'react';

import { api } from '../api';

interface Preference {
  event_key: string;
  label: string;
  description: string;
  enabled: boolean;
}

/**
 * Which events reach your bell.
 *
 * On the account page because it is about you and nobody else — the same
 * reasoning that moved your role, team and sign-out here rather than leaving
 * them on a dashboard everyone shares.
 *
 * **Switching something off hides it from your bell; it does not stop it
 * happening.** An achievement you have muted still reaches the Achievements
 * page and the wall screens, because that is the organization's record rather
 * than your inbox. Turning one back on shows what you missed.
 */
export default function NotificationPreferences() {
  const [preferences, setPreferences] = useState<Preference[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<Preference[]>('/api/notifications/preferences')
      .then(setPreferences)
      .catch(() => setError('Could not load your notification settings.'));
  }, []);

  async function toggle(key: string) {
    if (!preferences) return;

    // Applied locally first: a toggle that waits for a round trip before
    // moving feels broken, and the server's reply replaces this anyway.
    const next = preferences.map((p) =>
      p.event_key === key ? { ...p, enabled: !p.enabled } : p,
    );
    setPreferences(next);
    setSaving(true);
    setError(null);

    try {
      setPreferences(
        await api<Preference[]>('/api/notifications/preferences', {
          method: 'PUT',
          body: JSON.stringify({
            enabled: next.filter((p) => p.enabled).map((p) => p.event_key),
          }),
        }),
      );
    } catch {
      // Put it back. A switch that stays where you left it while the server
      // disagrees is worse than one that visibly springs back.
      setPreferences(preferences);
      setError('Could not save that. Your settings are unchanged.');
    } finally {
      setSaving(false);
    }
  }

  if (!preferences && !error) return null;

  return (
    <div className="mt-6 border-t border-edge pt-6">
      <h2 className="text-sm font-medium text-content">Notifications</h2>
      <p className="mt-1 text-xs text-content-muted">
        What reaches the bell in the top bar. Switching something off hides it
        from you — it does not stop it appearing on the Recognition feed or on
        the TVs.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}

      <ul className="mt-4 space-y-3">
        {preferences?.map((preference) => (
          <li key={preference.event_key} className="flex items-start gap-3">
            <input
              type="checkbox"
              id={`pref-${preference.event_key}`}
              checked={preference.enabled}
              disabled={saving}
              onChange={() => void toggle(preference.event_key)}
              className="mt-0.5 size-4 shrink-0 accent-brand"
            />
            <label htmlFor={`pref-${preference.event_key}`} className="min-w-0">
              <span className="block text-sm text-content">{preference.label}</span>
              <span className="block text-xs text-content-subtle">
                {preference.description}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
