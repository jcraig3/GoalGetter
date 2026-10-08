import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { ask } from '../confirm';
import { handoffMessage, type Delivery } from '../handoffWords';
import { passwordProblem } from '../passwordRule';
import TemporaryPasswordField from './TemporaryPasswordField';

interface Person {
  id: number;
  full_name: string;
  email: string;
  invite_pending: boolean;
  /** In the directory with SSO required: a password would be refused (11.1). */
  must_use_sso?: boolean;
  /** Why: `signed_in` with Microsoft before, or in the `directory` (P4-6). */
  sso_reason?: 'signed_in' | 'directory' | null;
  /** Whether a reset link would have anything to reset (P4-5). */
  has_password?: boolean;
  /** Has a password an admin set and not yet replaced it (11.2). */
  must_change_password?: boolean;
}

/**
 * Somebody's password, on their page: a reset link, or a temporary password.
 *
 * **Nothing offered that cannot work** (11.3): for somebody in the directory
 * while SSO is required, a password would be refused at sign-in, so this says
 * how they sign in instead of offering a link that only looks like help.
 *
 * Two ways to set somebody up (11.2): a one-time link they open themselves, or
 * a password you hand them — for somebody standing next to you, or a deployment
 * with no mail server. Theirs to replace the moment they sign in.
 */
export default function PersonPassword({
  person,
  isMe,
  onHandoff,
  onError,
  onChanged,
}: {
  person: Person;
  isMe: boolean;
  onHandoff: (handoff: { message: string; link: string }) => void;
  onError: (message: string | null) => void;
  onChanged: () => void;
}) {
  const [setting, setSetting] = useState(false);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  async function issueLink() {
    if (
      !(await ask(
        `Issue a password reset link for ${person.full_name}?\n\nTheir current password keeps working until they use it.`,
      ))
    ) {
      return;
    }
    try {
      const r = await api<{ reset_link: string } & Delivery>(`/api/users/${person.id}/reset-password`, {
        method: 'POST',
      });
      onHandoff({
        message: handoffMessage('reset', { name: person.full_name, email: person.email }, r),
        link: r.reset_link,
      });
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not issue a link.');
    }
  }

  async function setTemporary(event: FormEvent) {
    event.preventDefault();
    // Said before, because it is the part nobody expects: they are signed out.
    if (
      !person.invite_pending &&
      !(await ask(
        `Set this password for ${person.full_name}?\n\nThey are signed out everywhere, and choose their own the next time they sign in.`,
        { confirmLabel: 'Set password' },
      ))
    ) {
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await api(`/api/users/${person.id}/temporary-password`, {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      onHandoff({
        message: `Temporary password for ${person.full_name}. Hand it over — they choose their own when they sign in.`,
        link: password,
      });
      setSetting(false);
      setPassword('');
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not set the password.');
    } finally {
      setBusy(false);
    }
  }

  if (person.must_use_sso) {
    return (
      <Section>
        <p className="mt-1 text-sm text-content-muted">
          {/* Said with the reason (P4-6): signing in with Microsoft once binds
              somebody too, and nothing said so. */}
          {person.sso_reason === 'signed_in'
            ? 'They have signed in with Microsoft before, and single sign-on is required, so they keep signing in that way. A password would not let them in.'
            : 'They sign in with their company account. Single sign-on is required for people in your directory, so a password would not let them in.'}
        </p>
      </Section>
    );
  }

  // **Your own is changed on your Account page** (P4-5), where it asks for the
  // current one. Reset links and temporary passwords are for somebody else.
  if (isMe) {
    return (
      <Section>
        <p className="mt-1 text-sm text-content-muted">
          Change your own password on your{' '}
          <Link to="/account" className="text-brand hover:underline">
            Account page
          </Link>
          .
        </p>
      </Section>
    );
  }

  // Nothing to reset (P4-5): no password, and no invitation waiting either —
  // they have only ever signed in with Microsoft.
  const noPassword = person.has_password === false && !person.invite_pending;

  return (
    <Section>
      <p className="mt-1 text-sm text-content-muted">
        {person.must_change_password
          ? 'Set by an admin — they choose their own the next time they sign in.'
          : person.invite_pending
            ? 'None yet. Resend the invitation, or set a temporary password to hand over.'
            : noPassword
              ? 'They have no password — they sign in with Microsoft. A temporary password gives them one as well.'
              : 'A one-time link, valid for two hours — their current password keeps working until they use it. Or set a temporary password to hand over.'}
      </p>

      {setting ? (
        <form onSubmit={setTemporary} className="mt-3 max-w-sm space-y-3">
          <TemporaryPasswordField value={password} onChange={setPassword} autoFocus />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={busy || !password || passwordProblem(password) !== null}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Set password'}
            </button>
            <button
              type="button"
              onClick={() => {
                setSetting(false);
                setPassword('');
              }}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {/* Nothing to reset before they have one: resending the invitation
              is the action that matches what happened. */}
          {!person.invite_pending && !noPassword && (
            <button type="button" onClick={() => void issueLink()} className={SECONDARY}>
              Issue a reset link
            </button>
          )}
          <button type="button" onClick={() => setSetting(true)} className={SECONDARY}>
            Set a temporary password
          </button>
        </div>
      )}
    </Section>
  );
}

const SECONDARY =
  'rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover';

function Section({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-6 border-t border-edge pt-6">
      <p className="text-sm text-content">Password</p>
      {children}
    </div>
  );
}
