import { dayAndTime } from '../time';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import Toggle from './Toggle';
import { ask } from '../confirm';
import { toast } from '../toast';

interface Stream {
  enabled: boolean;
  format: 'json' | 'splunk';
  url_hint: string;
  header_name: string;
  header_set: boolean;
  last_sent_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
}

/**
 * The activity log, out of GoalGetter: a download, and a stream to a SIEM.
 *
 * **A stream starts from now** and sends each entry once, in order, moving on
 * only when the collector accepts. The download is how to hand over what came
 * before. The collector's address and credential are write-only, like every
 * other secret here.
 */
export default function AuditExport() {
  const [stream, setStream] = useState<Stream | null | undefined>(undefined);
  const [editing, setEditing] = useState(false);
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [tested, setTested] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Stream | null>('/api/audit/stream')
      .then(setStream)
      .catch(() => setStream(null));
  }, []);

  useEffect(load, [load]);

  const range = [since && `since=${since}`, until && `until=${until}`].filter(Boolean).join('&');

  async function test() {
    setTested('Sending…');
    try {
      const result = await api<{ ok: boolean; error: string | null }>('/api/audit/stream/test', {
        method: 'POST',
      });
      setTested(
        result.ok
          ? 'The collector accepted a test entry.'
          : (result.error ?? 'It was not accepted.'),
      );
    } catch (e) {
      setTested(e instanceof Error ? e.message : 'It was not accepted.');
    }
  }

  async function remove() {
    if (!await ask('Stop sending the activity log to this collector?')) return;
    try {
      await api('/api/audit/stream', { method: 'DELETE' });
      toast('Stream stopped');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove it.');
    }
  }

  return (
    <section className="mt-8 max-w-3xl space-y-5 rounded-lg border border-edge bg-surface p-6">
      <div>
        <h2 className="font-medium text-content">Export the activity log</h2>
        <p className="mt-1 text-sm text-content-muted">
          Every entry in a date range, oldest first. Leave the dates empty for all of it.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="block text-sm text-content-muted">
            From
            <input
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="mt-1 block rounded-md border border-edge bg-bg px-2 py-1.5 text-sm text-content"
            />
          </label>
          <label className="block text-sm text-content-muted">
            To
            <input
              type="date"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              className="mt-1 block rounded-md border border-edge bg-bg px-2 py-1.5 text-sm text-content"
            />
          </label>
          <a
            href={`/api/audit/export?format=csv${range ? `&${range}` : ''}`}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
          >
            Download CSV
          </a>
          <a
            href={`/api/audit/export?format=jsonl${range ? `&${range}` : ''}`}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
          >
            Download JSON Lines
          </a>
        </div>
      </div>

      <div className="border-t border-edge pt-5">
        <h2 className="font-medium text-content">Send to a SIEM</h2>
        <p className="mt-1 text-sm text-content-muted">
          Each new entry is sent to your security tool’s HTTPS collector as it happens — Splunk’s
          HTTP Event Collector, or anything that takes a JSON batch.
        </p>

        {error && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {error}
          </p>
        )}

        {stream === undefined ? null : stream && !editing ? (
          <div className="mt-3 space-y-2 text-sm">
            <p className="text-content">
              {stream.enabled ? 'Sending' : 'Paused'} to{' '}
              <code className="text-xs">{stream.url_hint}</code> as{' '}
              {stream.format === 'splunk' ? 'Splunk HEC' : 'a JSON batch'}.
            </p>
            {stream.last_error ? (
              <p className="rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-content">
                {stream.last_error}
              </p>
            ) : (
              stream.last_sent_at && (
                <p className="text-xs text-content-subtle">
                  Last sent {dayAndTime(stream.last_sent_at)}
                </p>
              )
            )}
            {tested && (
              <p className="text-xs text-content" aria-live="polite">
                {tested}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => void test()}
                className="text-brand hover:underline"
              >
                Send a test
              </button>
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="text-content-muted hover:text-content"
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => void remove()}
                className="text-content-muted hover:text-danger"
              >
                Remove
              </button>
            </div>
          </div>
        ) : (
          <StreamForm
            stream={stream}
            onClose={stream ? () => setEditing(false) : undefined}
            onSaved={(saved) => {
              setStream(saved);
              setEditing(false);
            }}
          />
        )}
      </div>
    </section>
  );
}

function StreamForm({
  stream,
  onClose,
  onSaved,
}: {
  stream: Stream | null;
  onClose?: () => void;
  onSaved: (saved: Stream) => void;
}) {
  const [url, setUrl] = useState('');
  const [format, setFormat] = useState<Stream['format']>(stream?.format ?? 'json');
  const [headerName, setHeaderName] = useState(stream?.header_name ?? 'Authorization');
  const [headerValue, setHeaderValue] = useState('');
  const [enabled, setEnabled] = useState(stream?.enabled ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await api<Stream>('/api/audit/stream', {
          method: 'PUT',
          body: JSON.stringify({
            enabled,
            format,
            header_name: headerName,
            ...(url.trim() ? { url: url.trim() } : {}),
            ...(headerValue ? { header_value: headerValue } : {}),
          }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  const field = 'mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content';
  return (
    <div className="mt-3 space-y-3">
      <label className="block">
        <span className="text-sm text-content-muted">
          Collector address{stream ? ' (leave empty to keep the current one)' : ''}
        </span>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://splunk.acme.example:8088/services/collector"
          className={field}
          autoComplete="off"
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm text-content-muted">Format</span>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as Stream['format'])}
            className={field}
          >
            <option value="json">JSON batch</option>
            <option value="splunk">Splunk HTTP Event Collector</option>
          </select>
        </label>
        <label className="block">
          <span className="text-sm text-content-muted">Header</span>
          <input
            value={headerName}
            onChange={(e) => setHeaderName(e.target.value)}
            maxLength={100}
            className={field}
          />
        </label>
      </div>
      <label className="block">
        <span className="text-sm text-content-muted">
          Header value{stream?.header_set ? ' (leave empty to keep the current one)' : ''}
        </span>
        <input
          type="password"
          value={headerValue}
          onChange={(e) => setHeaderValue(e.target.value)}
          placeholder={format === 'splunk' ? 'Splunk <token>' : 'Bearer <token>'}
          className={field}
          autoComplete="new-password"
        />
        <span className="mt-1 block text-xs text-content-subtle">
          Stored encrypted and never shown again.
        </span>
      </label>
      {stream && (
        <Toggle
          label="Sending"
          checked={enabled}
          onChange={setEnabled}
          hint="Off pauses it. Switching back on starts from then — download the gap."
        />
      )}
      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || (!stream && !url.trim()) || !headerName.trim()}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : stream ? 'Save' : 'Start sending'}
        </button>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-4 py-2 text-sm text-content-muted hover:text-content"
          >
            Cancel
          </button>
        )}
      </div>
      {!stream && (
        <p className="text-xs text-content-subtle">
          It starts from now. Use the download above for anything earlier.
        </p>
      )}
    </div>
  );
}
