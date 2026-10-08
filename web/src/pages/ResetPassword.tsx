import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api';
import Field from '../components/Field';
import { useDocumentTitle } from '../documentTitle';
import { MIN_PASSWORD_LENGTH, passwordProblem } from '../passwordRule';

/**
 * Sets a new password from an admin-issued reset link.
 *
 * Outside the app shell, like login: the person using this cannot sign in, so
 * there is no navigation to show them.
 */
export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  useDocumentTitle('Reset password');
  const token = params.get('token') ?? '';

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Asked as the page opens, so a dead link says so before anybody types a
  // new password twice into it (QA-29). Null while asking.
  const [dead, setDead] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    api('/api/auth/reset-password/check', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }).catch((e) =>
      setDead(e instanceof Error ? e.message : 'This reset link is no longer valid.'),
    );
  }, [token]);

  // Checked as they type rather than only on submit, so the mismatch is
  // visible before they have committed to it.
  const mismatch = confirm.length > 0 && password !== confirm;
  const problem = passwordProblem(password);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api('/api/auth/reset-password', {
        method: 'POST',
        body: JSON.stringify({ token, password }),
      });
      // Deliberately not signed in — a reset answers a possible compromise, so
      // signing in with the new password is what proves you chose it.
      navigate('/login', { state: { notice: 'Password updated. Sign in with it.' } });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set the password.');
    } finally {
      setBusy(false);
    }
  }

  if (!token || dead) {
    return (
      <Centred>
        <h1 className="text-h2 text-content">Reset password</h1>
        <p className="mt-2 text-sm text-content-muted">
          {dead ?? 'This link is missing its token.'}
        </p>
        {/* Two links, visibly two (P5-12): they read "Get a new linkBack to
            sign in" side by side with nothing between them. */}
        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Link to="/forgot-password" className="text-brand hover:underline">
            Get a new link
          </Link>
          <Link to="/login" className="text-brand hover:underline">
            Back to sign in
          </Link>
        </div>
      </Centred>
    );
  }

  return (
    <Centred>
      <h1 className="text-h2 text-content">Choose a new password</h1>
      <p className="mt-2 text-sm text-content-muted">
        At least {MIN_PASSWORD_LENGTH} characters. A passphrase of a few words is both
        stronger and easier to remember than a short one with symbols in it.
      </p>

      <form onSubmit={submit} className="mt-6 space-y-4">
        <Field
          label="New password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          autoFocus
          invalid={problem !== null}
          hint={problem ?? undefined}
        />
        <Field
          label="Confirm password"
          type="password"
          value={confirm}
          onChange={setConfirm}
          autoComplete="new-password"
          invalid={mismatch}
          hint={mismatch ? 'These do not match.' : undefined}
        />

        {error && (
          <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || problem !== null || mismatch || !password || !confirm}
          className="w-full rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Set password'}
        </button>
      </form>

      <p className="mt-6 text-xs text-content-muted">
        Setting a new password signs you out everywhere else.
      </p>
    </Centred>
  );
}

function Centred({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center bg-bg px-4">
      <div className="w-full max-w-sm rounded-lg border border-edge bg-surface p-8">
        {children}
      </div>
    </div>
  );
}
