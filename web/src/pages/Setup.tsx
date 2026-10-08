import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';

import { api } from '../api';
import { useDocumentTitle } from '../documentTitle';
import { useAuth } from '../auth';
import Field from '../components/Field';
import { PASSWORD_HINT, passwordProblem } from '../passwordRule';

export default function Setup() {
  const { setupRequired, refresh } = useAuth();
  const navigate = useNavigate();
  useDocumentTitle('Set up');

  const [organizationName, setOrganizationName] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Already set up — this page must not be reachable again.
  if (!setupRequired) return <Navigate to="/login" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      await api('/api/setup', {
        method: 'POST',
        body: JSON.stringify({
          organization_name: organizationName,
          full_name: fullName,
          email,
          password,
        }),
      });
      // Setup creates the account but does not sign anyone in — you prove you
      // know the password by logging in with it.
      await refresh();
      // Said, with the email filled in, rather than a blank sign-in page (P7-14).
      navigate('/login', {
        replace: true,
        state: { notice: 'Your organization is ready. Sign in with the account you just made.', email },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed.');
      setSubmitting(false);
    }
  }

  const problem = passwordProblem(password);

  return (
    <main className="grid min-h-screen place-items-center bg-bg p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg border border-edge bg-surface p-8"
      >
        <h1 className="text-2xl font-semibold text-content">
          Welcome to GoalGetter
        </h1>
        <p className="mt-2 text-content-muted">
          Create your organization and administrator account.
        </p>

        <div className="mt-6 space-y-4">
          <Field
            label="Organization name"
            value={organizationName}
            onChange={setOrganizationName}
            autoComplete="organization"
            autoFocus
          />
          <Field
            label="Your name"
            value={fullName}
            onChange={setFullName}
            autoComplete="name"
          />
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            autoComplete="username"
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            hint={problem ?? PASSWORD_HINT}
            invalid={problem !== null}
          />
        </div>

        {error && (
          <p
            role="alert"
            className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting || problem !== null}
          className="mt-6 w-full rounded-md bg-brand px-4 py-2 font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {submitting ? 'Creating…' : 'Create organization'}
        </button>
      </form>
    </main>
  );
}
