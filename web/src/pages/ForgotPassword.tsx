import { useEffect, useState, type FormEvent } from 'react';
import { Link, useLocation } from 'react-router-dom';

import { api } from '../api';
import Field from '../components/Field';
import { useDocumentTitle } from '../documentTitle';
import type { Providers } from './loginOptions';

/**
 * "Forgot password?" from the sign-in page (Phase 14).
 *
 * Emails a link when the server can send mail; otherwise says who can send one.
 * The answer after sending is the same whether or not the address has an
 * account — the page never says which, and the link never comes back here.
 */
export default function ForgotPassword() {
  useDocumentTitle('Forgot password');
  const location = useLocation();
  const [email, setEmail] = useState(
    (location.state as { email?: string } | null)?.email ?? '',
  );
  const [canSend, setCanSend] = useState<boolean | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Providers>('/api/auth/providers')
      .then((p) => setCanSend(Boolean(p.self_reset)))
      .catch(() => setCanSend(false));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const reply = await api<{ detail: string }>('/api/auth/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ email }),
      });
      setAnswer(reply.detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send that. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-bg p-6">
      <div className="w-full max-w-sm rounded-lg border border-edge bg-surface p-8">
        <h1 className="text-2xl font-semibold text-content">Forgot your password?</h1>

        {canSend === null ? null : answer ? (
          <p role="status" className="mt-4 text-content-muted">
            {answer} Check your inbox, and your junk folder.
          </p>
        ) : canSend ? (
          <form onSubmit={submit} className="mt-2">
            <p className="text-content-muted">
              Enter the email you sign in with, and we will send you a link to choose a new one.
            </p>
            <div className="mt-6">
              <Field
                label="Email"
                type="email"
                value={email}
                onChange={setEmail}
                autoComplete="username"
                autoFocus
              />
            </div>
            {error && (
              <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy || !email}
              className="mt-6 w-full rounded-md bg-brand px-4 py-2 font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Sending…' : 'Send me a link'}
            </button>
          </form>
        ) : (
          // No mail server: nothing can be emailed, and handing a link back on
          // this page would let anybody take any account.
          <p className="mt-4 text-content-muted">
            Ask an administrator to send you a reset link. They can, from your page under Users →
            Password.
          </p>
        )}

        <p className="mt-6 text-sm text-content-muted">
          Signed in with Microsoft before? You do not need a password — use the Microsoft button
          on the sign-in page.
        </p>
        <Link to="/login" className="mt-4 inline-block text-sm text-brand hover:underline">
          Back to sign in
        </Link>
      </div>
    </main>
  );
}
