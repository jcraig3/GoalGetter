import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { api, ApiError } from '../api';
import { useAuth } from '../auth';
import Field from '../components/Field';
import { TwoStepSignIn, type MfaStep } from '../components/TwoStep';
import { useDocumentTitle } from '../documentTitle';
import { loginOptions, type Providers } from './loginOptions';

export default function Login() {
  const { user, setupRequired, login, signedIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [searchParams] = useSearchParams();
  // "Sign in · GoalGetter", not just the product name (P4-7).
  useDocumentTitle('Sign in');
  // Said by the page that sent us here: "Password updated. Sign in with it."
  // It was sent and never shown.
  const notice = (location.state as { notice?: string } | null)?.notice ?? null;

  // Filled in when first-run setup sends the new admin here (P7-14).
  const [email, setEmail] = useState((location.state as { email?: string } | null)?.email ?? '');
  const [password, setPassword] = useState('');
  // A failed SSO round trip redirects back here with ?error=… — that flow
  // can't return JSON, so the message arrives in the URL.
  const [error, setError] = useState<string | null>(searchParams.get('error'));
  const [submitting, setSubmitting] = useState(false);
  const [lockedFor, setLockedFor] = useState(0);
  const [providers, setProviders] = useState<Providers | null>(null);
  //: The password was right and a second step is owed.
  const [step, setStep] = useState<MfaStep | null>(null);

  // One answer for every half of the form, and their order (11.1).
  const shown = useMemo(() => loginOptions(providers), [providers]);

  useEffect(() => {
    // Which buttons to draw is a server decision, so toggling SSO takes effect
    // without rebuilding the frontend.
    api<Providers>('/api/auth/providers')
      .then(setProviders)
      .catch(() => setProviders({ local: true, sso_enabled: false, sso_button_label: '' }));
  }, []);

  // Counts the lockout down so the button re-enables on its own, rather than
  // leaving the user to guess when they may try again.
  useEffect(() => {
    if (lockedFor <= 0) return;
    const timer = setInterval(() => setLockedFor((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(timer);
  }, [lockedFor]);

  useEffect(() => {
    if (lockedFor === 0) setError((e) => (e?.startsWith('Too many') ? null : e));
  }, [lockedFor]);

  if (setupRequired) return <Navigate to="/setup" replace />;
  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const owed = await login(email, password);
      if (owed) {
        setStep(owed);
        setSubmitting(false);
        return;
      }
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from ?? '/', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setLockedFor(err.retryAfter ?? 60);
      }
      setError(err instanceof Error ? err.message : 'Sign in failed.');
      // Cleared, so pressing Sign in again is a new attempt rather than the
      // same wrong one (P4-7). The address stays: it is rarely the mistake.
      setPassword('');
      setSubmitting(false);
    }
  }

  const locked = lockedFor > 0;

  // A link, not a fetch. The OIDC flow is a full-page browser redirect to the
  // provider — an XHR could not follow it, and the provider needs to set its
  // own cookies on its own origin.
  const ssoButton = (
    <a
      href="/api/auth/sso/start"
      className={`block w-full rounded-md px-4 py-2 text-center font-medium transition-colors ${
        shown.ssoFirst
          ? 'bg-brand text-white hover:bg-brand-hover'
          : 'border border-edge text-content hover:bg-surface-hover'
      }`}
    >
      {providers?.sso_button_label}
    </a>
  );

  if (step) {
    return (
      <main className="grid min-h-screen place-items-center bg-bg p-6">
        <div className="w-full max-w-sm rounded-lg border border-edge bg-surface p-8">
          <h1 className="text-2xl font-semibold text-content">Two-step sign-in</h1>
          <div className="mt-6">
            <TwoStepSignIn
              step={step}
              onSignedIn={(me) => {
                signedIn(me);
                const from = (location.state as { from?: string } | null)?.from;
                navigate(from ?? '/', { replace: true });
              }}
              onRestart={() => {
                setStep(null);
                setPassword('');
              }}
            />
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="grid min-h-screen place-items-center bg-bg p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border border-edge bg-surface p-8"
      >
        <h1 className="text-2xl font-semibold text-content">Sign in</h1>
        <p className="mt-2 text-content-muted">Welcome back to GoalGetter.</p>
        {notice && (
          <p role="status" className="mt-4 rounded-md border border-success px-3 py-2 text-sm text-success">
            {notice}
          </p>
        )}

        {/* When SSO is required the button leads: it is how most people here
            get in (11.1). */}
        {shown.sso && shown.ssoFirst && (
          <>
            <div className="mt-6">{ssoButton}</div>
            <Divider words="or with a password" />
          </>
        )}

        {shown.form && (
          <div className={`space-y-4 ${shown.ssoFirst ? '' : 'mt-6'}`}>
            <Field
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              autoComplete="username"
              // Not over the button everybody in the directory should press.
              autoFocus={!shown.ssoFirst}
            />
            <div>
              <Field
                label="Password"
                type="password"
                value={password}
                onChange={setPassword}
                autoComplete="current-password"
              />
              {/* Always offered (Phase 14): the page behind it says whether a
                  link can be emailed, or that an admin sends one. */}
              <Link
                to="/forgot-password"
                state={{ email }}
                className="mt-1 inline-block text-sm text-brand hover:underline"
              >
                Forgot password?
              </Link>
            </div>
          </div>
        )}

        {error && (
          // role="alert" makes a screen reader announce this the moment it
          // appears, rather than leaving it silently on screen.
          <p
            role="alert"
            className={`mt-4 rounded-md border px-3 py-2 text-sm ${
              locked
                ? 'border-warning text-warning'
                : 'border-danger text-danger'
            }`}
          >
            {locked ? `Too many sign-in attempts. Try again in ${lockedFor}s.` : error}
          </p>
        )}

        {shown.form && (
          <button
            type="submit"
            disabled={submitting || locked}
            // One brand button on the page: the SSO one, when it leads.
            className={`mt-6 w-full rounded-md px-4 py-2 font-medium transition-colors disabled:opacity-50 ${
              shown.ssoFirst
                ? 'border border-edge text-content hover:bg-surface-hover'
                : 'bg-brand text-white hover:bg-brand-hover'
            }`}
          >
            {locked
              ? `Locked (${lockedFor}s)`
              : submitting
                ? 'Signing in…'
                : 'Sign in'}
          </button>
        )}

        {/* **A policy, not a hint about any one account.** Who the form is for
            sets the expectation; the refusal of a directory person's password
            is the same "Incorrect email or password" as a wrong one, so nothing
            here says who is in the directory. */}
        {shown.hint && (
          <p className="mt-4 text-center text-sm text-content-muted">
            Have a company account? Use the button above — passwords are for
            admins and people without one.
          </p>
        )}

        {shown.sso && !shown.ssoFirst && (
          <>
            {shown.divider && <Divider words="or" />}
            {ssoButton}
          </>
        )}
      </form>
    </main>
  );
}

function Divider({ words }: { words: string }) {
  return (
    <div className="my-6 flex items-center gap-3">
      <span className="h-px flex-1 bg-edge" />
      <span className="text-xs text-content-muted">{words}</span>
      <span className="h-px flex-1 bg-edge" />
    </div>
  );
}
