import { useEffect, useState } from 'react';

import { directory } from '../directory';

/**
 * Signing in the account a connection acts as, in delegated mode.
 *
 * **Only one of two modes needs this.** In application mode nothing signs in —
 * see `oauth_client.directory_auth_mode`. This exists because a Cloud Application
 * Administrator can consent to every delegated Microsoft Graph permission and to
 * none of its app roles, so the application mode needs somebody more senior to
 * press consent once and this mode needs nobody.
 *
 * A popup rather than a redirect, so the panel behind it keeps its place and the
 * result arrives by message. A blocked popup is not a dead end: the same page
 * navigates instead, and the callback lands back on Integrations.
 */
export default function AccountConnectButton({
  provider,
  label,
  onConnected,
}: {
  /** The provider key, not the display name. */
  provider: string;
  label: string;
  onConnected: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function heard(event: MessageEvent) {
      // Same-origin only: this message is the signal that a credential was
      // stored, and any page that could forge it could act on that.
      if (event.origin !== window.location.origin) return;
      if (event.data?.source !== 'goalgetter-tenant') return;
      setBusy(false);
      setError(event.data.result?.error ?? null);
      if (!event.data.result?.error) onConnected();
    }
    window.addEventListener('message', heard);
    return () => window.removeEventListener('message', heard);
  }, [onConnected]);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await directory.startAccount(provider);
      const opened = window.open(url, 'gg-tenant', 'width=520,height=660');
      if (!opened) window.location.assign(url);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : 'Could not start that.');
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => void connect()}
        disabled={busy}
        className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? 'Waiting for sign-in…' : label}
      </button>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
    </>
  );
}
