import CopyValue from './CopyValue';

/**
 * Turning sound on for TVs nobody clicks (Phase 24).
 *
 * **Browsers don't let a site give itself sound**: a tab needs a click
 * first, unless its browser has been told the site may. Nobody clicks a TV and
 * nothing prompts on one (asked for), so each TV's browser is told once — in
 * its settings, or by policy for Chrome, which has no setting for it. Each
 * screen reports when its sound was held back; this lists those TVs and goes
 * away by itself once each has played something with sound.
 */
export default function TvSoundHelp({ tvs }: { tvs: { name: string; url: string }[] }) {
  if (tvs.length === 0) return null;
  const origins = [...new Set(tvs.map((tv) => originOf(tv.url)).filter(Boolean))] as string[];
  const names = tvs.map((tv) => tv.name).join(', ');
  return (
    <section className="mt-4 rounded-lg border border-warning/40 bg-surface p-4 text-sm" aria-label="Sound on TVs">
      <p className="font-medium text-content">Sound is off on {names}</p>
      <p className="mt-1 text-content-muted">
        Browsers don’t let a site start sound by itself. Allow it once in each of these TVs’ browsers, and sound plays
        from the moment the channel opens:
      </p>
      <div className="mt-2 space-y-1 text-xs">
        {origins.map((origin) => (
          <CopyValue key={origin} text={origin} />
        ))}
      </div>
      <ul className="mt-3 space-y-3 text-content">
        <li>
          <span className="font-medium">Edge</span>
          <span className="block text-xs text-content-subtle">
            Settings → Cookies and site permissions → Media autoplay → Allow, then add the address above under Allow.
          </span>
        </li>
        <li>
          <span className="font-medium">Firefox</span>
          <span className="block text-xs text-content-subtle">
            On the channel, the icon left of the address → Autoplay → Allow Audio and Video.
          </span>
        </li>
        <li>
          <span className="font-medium">Chrome</span>
          <span className="text-content-muted">, which has no setting for it: on the TV, PowerShell as administrator, then restart Chrome.</span>
          {origins.map((origin) => (
            <div key={origin} className="mt-1 text-xs">
              <CopyValue text={policyCommand('Google\\Chrome', origin)} />
            </div>
          ))}
          <span className="mt-1 block text-xs text-content-subtle">
            Or start Chrome with <code>--autoplay-policy=no-user-gesture-required</code>.
          </span>
        </li>
      </ul>
    </section>
  );
}

function originOf(url: string): string | null {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

/** Adds the address to the browser's autoplay allowlist, after whatever IT
 *  already put there rather than over it. */
export function policyCommand(browser: string, origin: string): string {
  return (
    `$k='HKLM:\\SOFTWARE\\Policies\\${browser}\\AutoplayAllowlist'; New-Item -Force $k | Out-Null; ` +
    `New-ItemProperty $k -Name ((Get-Item $k).ValueCount + 1) -Value '${origin}' | Out-Null`
  );
}
