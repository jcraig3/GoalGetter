import { useState, type FormEvent } from 'react';

import { api } from '../api';
import Field from '../components/Field';
import { PASSWORD_HINT, passwordProblem } from '../passwordRule';

/**
 * Change your own password, proving the current one.
 *
 * Collapsed by default: it belongs on the account panel, but an always-open
 * password form is a permanent invitation to a task almost nobody is here to
 * do — and three empty password fields on the home page read as clutter.
 */
export default function ChangePassword() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const mismatch = confirm.length > 0 && next !== confirm;
  const problem = passwordProblem(next);

  function reset() {
    setCurrent('');
    setNext('');
    setConfirm('');
    setError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api('/api/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      reset();
      setOpen(false);
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change the password.');
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <div className="mt-4 flex items-center gap-3 border-t border-edge pt-4">
        <button
          onClick={() => {
            setDone(false);
            setOpen(true);
          }}
          className="rounded-md border border-edge px-3 py-1.5 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
        >
          Change password
        </button>
        {done && <span className="text-sm text-success">Password updated.</span>}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="mt-4 space-y-4 border-t border-edge pt-4">
      <Field
        label="Current password"
        type="password"
        value={current}
        onChange={setCurrent}
        autoComplete="current-password"
        autoFocus
      />
      <Field
        label="New password"
        type="password"
        value={next}
        onChange={setNext}
        autoComplete="new-password"
        invalid={problem !== null}
        hint={problem ?? PASSWORD_HINT}
      />
      <Field
        label="Confirm new password"
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

      {/* Said before they submit, not after — being signed out of another
          device is a surprise worth warning about. */}
      <p className="text-xs text-content-muted">
        This signs you out on every other device. You stay signed in here.
      </p>

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy || !current || problem !== null || mismatch || !next || !confirm}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? 'Saving…' : 'Change password'}
        </button>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
