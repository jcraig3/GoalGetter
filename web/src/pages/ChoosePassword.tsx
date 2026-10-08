import { useState, type FormEvent } from 'react';

import { api } from '../api';
import { useAuth } from '../auth';
import Field from '../components/Field';
import { useDocumentTitle } from '../documentTitle';
import { PASSWORD_HINT, passwordProblem } from '../passwordRule';

/**
 * Replacing a password an admin set, before anything else (11.2).
 *
 * Shown in place of every signed-in page while one is owed, and the server
 * refuses every other request until it is done — this page decides what to
 * draw, not what is allowed. No current password asked for: they typed it a
 * moment ago to get here.
 */
export default function ChoosePassword() {
  const { user, refresh, logout } = useAuth();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);
  useDocumentTitle('Choose your password');

  const problem = passwordProblem(password);
  const mismatch = confirm.length > 0 && confirm !== password;

  async function submit(event: FormEvent) {
    event.preventDefault();
    // Checked here too, not only by the disabled button (P4-8): a forced
    // submit with a different confirmation saved the first field.
    if (!password || problem !== null || confirm !== password) {
      setError(confirm !== password ? 'These do not match.' : problem ?? 'Enter a password.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api('/api/auth/choose-password', {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      // The session now opens everything; the app takes over from here.
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set the password.');
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-bg p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-lg border border-edge bg-surface p-8"
      >
        <h1 className="text-2xl font-semibold text-content">Choose your own password</h1>
        <p className="mt-2 text-sm text-content-muted">
          {user?.full_name ? `Welcome, ${user.full_name.split(' ')[0]}. ` : ''}
          The password you signed in with was set for you. Choose one only you
          know to carry on.
        </p>

        <div className="mt-6 space-y-4">
          <Field
            label="New password"
            type={show ? 'text' : 'password'}
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            autoFocus
            invalid={problem !== null}
            hint={problem ?? PASSWORD_HINT}
          />
          <Field
            label="Confirm password"
            type={show ? 'text' : 'password'}
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
            invalid={mismatch}
            hint={mismatch ? 'These do not match.' : undefined}
          />
          <label className="flex items-center gap-2 text-sm text-content-muted">
            <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} />
            Show passwords
          </label>
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
          {busy ? 'Saving…' : 'Set password and continue'}
        </button>
        <button
          type="button"
          onClick={() => void logout()}
          className="mt-3 block w-full text-center text-sm text-content-muted underline transition-colors hover:text-content"
        >
          Sign out
        </button>
      </form>
    </main>
  );
}
