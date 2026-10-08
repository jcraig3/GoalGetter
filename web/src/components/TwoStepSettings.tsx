import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import { RecoveryCodes, SetupSteps } from './TwoStep';

interface Status {
  enabled: boolean;
  required: boolean;
  has_password: boolean;
  recovery_left: number;
}

type Mode = 'idle' | 'setup' | 'codes' | 'new-codes' | 'disable';

/**
 * Two-step sign-in, on your own account page.
 *
 * **For password sign-in.** An account that only ever signs in with SSO gets
 * its second step from the identity provider, so it is told that rather than
 * offered a switch that does nothing.
 */
export default function TwoStepSettings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [mode, setMode] = useState<Mode>('idle');
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Status>('/api/auth/mfa')
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(load, [load]);

  async function start() {
    setError(null);
    setMode('setup');
    setSetup(null);
    try {
      setSetup(await api('/api/auth/mfa/setup', { method: 'POST' }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start setup.');
    }
  }

  async function run(path: string, then: (answer: { recovery_codes?: string[] }) => void) {
    setBusy(true);
    setError(null);
    try {
      const answer = await api<{ recovery_codes?: string[] }>(path, {
        method: 'POST',
        body: JSON.stringify({ code }),
      });
      setCode('');
      then(answer ?? {});
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  }

  if (!status) return null;

  return (
    <div className="mt-6 border-t border-edge pt-6">
      <h2 className="text-sm font-medium text-content">Two-step sign-in</h2>
      {!status.has_password ? (
        <p className="mt-1 text-sm text-content-muted">
          You sign in with your work account, which handles its own second step.
        </p>
      ) : mode === 'codes' || mode === 'new-codes' ? (
        <div className="mt-3">
          <RecoveryCodes codes={codes} onDone={() => setMode('idle')} />
        </div>
      ) : mode === 'setup' ? (
        <div className="mt-3 max-w-sm">
          <SetupSteps
            setup={setup}
            busy={busy}
            error={error}
            onConfirm={(value) => {
              setCode(value);
              setBusy(true);
              setError(null);
              api<{ recovery_codes: string[] }>('/api/auth/mfa/enable', {
                method: 'POST',
                body: JSON.stringify({ code: value }),
              })
                .then((answer) => {
                  setCodes(answer.recovery_codes);
                  setMode('codes');
                  load();
                })
                .catch((e) => setError(e instanceof Error ? e.message : 'That code did not work.'))
                .finally(() => setBusy(false));
            }}
          />
          <button type="button" onClick={() => setMode('idle')} className="mt-2 text-sm text-content-muted hover:text-content">
            Cancel
          </button>
        </div>
      ) : status.enabled ? (
        <div className="mt-2 space-y-3">
          <p className="text-sm text-content">
            <span className="text-success" aria-hidden>
              ✓{' '}
            </span>
            On — signing in with your password also asks for a code from your authenticator app.{' '}
            <span className="text-content-muted">
              {status.recovery_left} recovery {status.recovery_left === 1 ? 'code' : 'codes'} left.
            </span>
          </p>
          {mode === 'disable' || mode === 'idle' ? (
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="text-xs text-content-muted">A current code, to make a change</span>
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={20}
                  placeholder="123456"
                  className="mt-1 block w-36 rounded-md border border-edge bg-bg px-3 py-2 font-mono text-sm text-content"
                />
              </label>
              <button
                type="button"
                disabled={busy || !code.trim()}
                onClick={() => void run('/api/auth/mfa/recovery-codes', (a) => { setCodes(a.recovery_codes ?? []); setMode('new-codes'); })}
                className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover disabled:opacity-50"
              >
                New recovery codes
              </button>
              <button type="button" onClick={() => void start()} className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover">
                Move to a new phone
              </button>
              {!status.required && (
                <button
                  type="button"
                  disabled={busy || !code.trim()}
                  onClick={() => void run('/api/auth/mfa/disable', () => setMode('idle'))}
                  className="rounded-md border border-danger px-3 py-2 text-sm text-danger hover:bg-danger hover:text-white disabled:opacity-50"
                >
                  Turn off
                </button>
              )}
            </div>
          ) : null}
          {status.required && (
            <p className="text-xs text-content-subtle">Your organization requires it, so it cannot be turned off.</p>
          )}
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          <p className="text-sm text-content-muted">
            Off. Turn it on and signing in with your password also asks for a six-digit code from an
            authenticator app on your phone.
          </p>
          <button
            type="button"
            onClick={() => void start()}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover"
          >
            Set up two-step sign-in
          </button>
        </div>
      )}
    </div>
  );
}
