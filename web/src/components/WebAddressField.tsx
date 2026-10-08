import Field from './Field';

/** Whether an address only opens on the computer that uses it. */
export function isLocalAddress(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return (
      host === 'localhost' ||
      host === '[::1]' ||
      host.startsWith('127.') ||
      host.endsWith('.localhost')
    );
  } catch {
    return false;
  }
}

/**
 * Where people reach this deployment, set in Settings (11.7).
 *
 * **Offered, not guessed into the form.** The browser knows the address it is
 * on, so the page offers it in one press — but never writes it in by itself:
 * an admin setting up over `localhost` would otherwise save an address nobody
 * else can open, the moment they changed the currency.
 */
export default function WebAddressField({
  value,
  saved,
  fallback,
  onChange,
  detected = window.location.origin,
}: {
  value: string | null;
  /** What is saved now, to say when a change moves the sign-in addresses. */
  saved: string | null;
  /** `APP_URL` from the server: what applies while this is empty. */
  fallback: string;
  onChange: (value: string | null) => void;
  /** The address this browser is on. */
  detected?: string;
}) {
  const current = value ?? '';
  // An older server sends no default; nothing to warn about then.
  const effective = current || fallback || '';
  return (
    <div>
      <Field
        label="Web address"
        value={current}
        onChange={(v) => onChange(v.trim() ? v : null)}
        placeholder={fallback}
        required={false}
        hint={current ? 'Used in links, emails and Microsoft sign-in' : `Empty uses ${fallback}`}
      />
      {detected && detected !== effective && (
        <button
          type="button"
          onClick={() => onChange(detected)}
          className="mt-1 text-sm text-brand hover:underline"
        >
          Use {detected}
        </button>
      )}
      {isLocalAddress(effective) && (
        <p className="mt-1 text-xs text-warning">
          Only opens on this computer.
          {/* The browser knows only the address it is on, so from localhost
              there is nothing better to offer; say how to get one offered. */}
          {isLocalAddress(detected) && ' Open GoalGetter by its network address to have that offered here.'}
        </p>
      )}
      {/* **Before saving, not after a sign-in fails.** Microsoft accepts an
          http:// redirect only for localhost; anything else must be https://,
          and no change in Azure can register it. Found by setting a LAN
          address and watching single sign-on fail with AADSTS50011. */}
      {effective.startsWith('http://') && !isLocalAddress(effective) && (
        <p className="mt-1 text-xs text-warning">
          Microsoft sign-in needs https:// here (http:// works only for localhost).
        </p>
      )}
      {(value ?? null) !== (saved ?? null) && (
        <p className="mt-1 text-xs text-content-muted">
          After saving, add the new sign-in addresses in Azure (Integrations lists them).
        </p>
      )}
    </div>
  );
}
