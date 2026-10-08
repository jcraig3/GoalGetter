import QRCode from 'qrcode';
import { useEffect, useState, type FormEvent } from 'react';

import { api, ApiError } from '../api';
import type { User } from '../auth';

/** What a correct password answers with when a second step is owed. */
export interface MfaStep {
  mfa: 'code' | 'setup';
  challenge: string;
}

export function isMfaStep(value: unknown): value is MfaStep {
  return typeof value === 'object' && value !== null && 'mfa' in value && 'challenge' in value;
}

interface Setup {
  secret: string;
  uri: string;
}

/**
 * The QR code an authenticator app scans, drawn in the browser.
 *
 * **Never sent anywhere to be drawn.** The secret is in the picture, so the
 * picture is made here from a bundled library rather than by a QR service.
 */
export function QrCode({ value, label }: { value: string; label: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    QRCode.toDataURL(value, { margin: 1, width: 200 })
      .then((url) => live && setSrc(url))
      .catch(() => live && setSrc(null));
    return () => {
      live = false;
    };
  }, [value]);
  return src ? (
    <img src={src} alt={label} width={200} height={200} className="rounded-md bg-white p-2" />
  ) : (
    <div className="grid size-[200px] place-items-center rounded-md border border-edge text-xs text-content-subtle">
      Drawing…
    </div>
  );
}

/** Groups of four, so it can be typed by hand from a phone's screen. */
function spaced(secret: string) {
  return secret.replace(/(.{4})/g, '$1 ').trim();
}

/** Recovery codes, shown once, with a way to keep them. */
export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const text = codes.join('\n');
  return (
    <div className="space-y-3">
      <p className="text-sm text-content">
        <strong>Save these recovery codes.</strong> Each one signs you in once if you lose your
        phone. They will not be shown again.
      </p>
      <ul className="grid grid-cols-2 gap-1 rounded-md border border-edge bg-bg p-3 font-mono text-sm text-content">
        {codes.map((code) => (
          <li key={code}>{code}</li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => void navigator.clipboard?.writeText(text)}
          className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
        >
          Copy
        </button>
        <a
          href={`data:text/plain;charset=utf-8,${encodeURIComponent(`GoalGetter recovery codes\n\n${text}\n`)}`}
          download="goalgetter-recovery-codes.txt"
          className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
        >
          Download
        </a>
        <button
          type="button"
          onClick={onDone}
          className="ml-auto rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover"
        >
          I have saved them
        </button>
      </div>
    </div>
  );
}

function CodeField({ value, onChange, allowRecovery }: { value: string; onChange: (v: string) => void; allowRecovery?: boolean }) {
  return (
    <label className="block">
      <span className="text-sm text-content-muted">
        {allowRecovery ? 'Code from your authenticator app, or a recovery code' : 'Code from your authenticator app'}
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode={allowRecovery ? 'text' : 'numeric'}
        autoComplete="one-time-code"
        autoFocus
        maxLength={allowRecovery ? 20 : 6}
        placeholder={allowRecovery ? '123456' : '123456'}
        className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-center font-mono text-lg tracking-widest text-content"
      />
    </label>
  );
}

/** Scan, confirm with a code. Used by sign-in and by the account page. */
export function SetupSteps({
  setup,
  busy,
  error,
  onConfirm,
}: {
  setup: Setup | null;
  busy: boolean;
  error: string | null;
  onConfirm: (code: string) => void;
}) {
  const [code, setCode] = useState('');
  return (
    <form
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onConfirm(code);
      }}
      className="space-y-4"
    >
      <ol className="list-decimal space-y-1 pl-5 text-sm text-content-muted">
        <li>Open an authenticator app — Microsoft Authenticator, Google Authenticator, 1Password.</li>
        <li>Scan this code, or type the key under it.</li>
        <li>Enter the six-digit code the app shows.</li>
      </ol>
      {setup ? (
        <div className="flex flex-col items-center gap-2">
          <QrCode value={setup.uri} label="QR code for your authenticator app" />
          <code className="select-all rounded bg-bg px-2 py-1 text-xs text-content">{spaced(setup.secret)}</code>
        </div>
      ) : (
        <p className="text-sm text-content-muted">Preparing…</p>
      )}
      <CodeField value={code} onChange={setCode} />
      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || !setup || code.replace(/\D/g, '').length !== 6}
        className="w-full rounded-md bg-brand px-4 py-2 font-medium text-white hover:bg-brand-hover disabled:opacity-50"
      >
        {busy ? 'Checking…' : 'Turn on two-step sign-in'}
      </button>
    </form>
  );
}

/**
 * The second step of a password sign-in: a code, or — when the organization
 * requires it and this account has none — setting an authenticator up.
 */
export function TwoStepSignIn({
  step,
  onSignedIn,
  onRestart,
}: {
  step: MfaStep;
  onSignedIn: (user: User) => void;
  onRestart: () => void;
}) {
  const [code, setCode] = useState('');
  const [setup, setSetup] = useState<Setup | null>(null);
  const [codes, setCodes] = useState<{ codes: string[]; user: User } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (step.mfa !== 'setup') return;
    api<Setup>('/api/auth/login/mfa/setup', { method: 'POST', body: JSON.stringify({ challenge: step.challenge }) })
      .then(setSetup)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not start setup.'));
  }, [step]);

  async function submitCode(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(
        await api<User>('/api/auth/login/mfa', {
          method: 'POST',
          body: JSON.stringify({ challenge: step.challenge, code }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That code did not work.');
      if (e instanceof ApiError && e.status === 401 && /again/.test(e.message)) onRestart();
    } finally {
      setBusy(false);
    }
  }

  async function confirm(value: string) {
    setBusy(true);
    setError(null);
    try {
      const done = await api<{ user: User; recovery_codes: string[] }>('/api/auth/login/mfa/enable', {
        method: 'POST',
        body: JSON.stringify({ challenge: step.challenge, code: value }),
      });
      setCodes({ codes: done.recovery_codes, user: done.user });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That code did not work.');
    } finally {
      setBusy(false);
    }
  }

  if (codes) return <RecoveryCodes codes={codes.codes} onDone={() => onSignedIn(codes.user)} />;

  if (step.mfa === 'setup') {
    return (
      <div className="space-y-4">
        <p className="text-sm text-content">
          Your organization requires two-step sign-in. Set up an authenticator app to continue.
        </p>
        <SetupSteps setup={setup} busy={busy} error={error} onConfirm={(value) => void confirm(value)} />
      </div>
    );
  }

  return (
    <form onSubmit={submitCode} className="space-y-4">
      <p className="text-sm text-content-muted">Enter the code from your authenticator app.</p>
      <CodeField value={code} onChange={setCode} allowRecovery />
      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || !code.trim()}
        className="w-full rounded-md bg-brand px-4 py-2 font-medium text-white hover:bg-brand-hover disabled:opacity-50"
      >
        {busy ? 'Checking…' : 'Continue'}
      </button>
      <button type="button" onClick={onRestart} className="block w-full text-center text-sm text-content-muted underline hover:text-content">
        Start again
      </button>
    </form>
  );
}
