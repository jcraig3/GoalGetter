import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api';
import { useAuth, type User } from '../auth';
import Field from '../components/Field';
import { PASSWORD_HINT, passwordProblem } from '../passwordRule';

export default function AcceptInvite() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const { user, refresh } = useAuth();
  const navigate = useNavigate();

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api<User>('/api/auth/accept-invite', {
        method: 'POST',
        body: JSON.stringify({ token, password }),
      });
      // Accepting signs you in, so pull the session into context before moving.
      await refresh();
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not accept the invitation.');
      setBusy(false);
    }
  }

  const problem = passwordProblem(password);
  const mismatch = confirm.length > 0 && confirm !== password;

  return (
    <main className="grid min-h-screen place-items-center bg-bg p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-lg border border-edge bg-surface p-8"
      >
        <h1 className="text-2xl font-semibold text-content">Set your password</h1>
        <p className="mt-2 text-content-muted">
          Choose a password to finish setting up your account.
        </p>

        {!token ? (
          <p role="alert" className="mt-6 rounded-md border border-danger px-3 py-2 text-sm text-danger">
            This link is missing its invitation code. Ask an administrator for a
            new one.
          </p>
        ) : (
          <>
            <div className="mt-6 space-y-4">
              <Field
                label="Password"
                type="password"
                value={password}
                onChange={setPassword}
                autoComplete="new-password"
                autoFocus
                hint={problem ?? PASSWORD_HINT}
                invalid={problem !== null}
              />
              <Field
                label="Confirm password"
                type="password"
                value={confirm}
                onChange={setConfirm}
                autoComplete="new-password"
                hint={mismatch ? 'Passwords do not match.' : undefined}
                invalid={mismatch}
              />
            </div>

            {error && (
              <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy || problem !== null || mismatch || !password || !confirm}
              className="mt-6 w-full rounded-md bg-brand px-4 py-2 font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Setting up…' : 'Set password and sign in'}
            </button>
          </>
        )}
      </form>
    </main>
  );
}
