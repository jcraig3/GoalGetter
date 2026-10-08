import { useEffect, useState } from 'react';

import { api } from './api';
import type { Appearance } from './appearance';

/**
 * The organization — its look, and its timezone — fetched once and shared.
 *
 * **Two readers with different reasons.** The app chrome needs the company's
 * logo and colours, because that is what makes this deployment look like the
 * company's own tool rather than a product they rent. Every per-item
 * appearance control needs the same object for a different reason: it is the
 * answer to "what would this be if I left it alone?".
 *
 * One request serves both. The Appearance and Settings pages are the only
 * things that change it, and each forgets the cache when it saves — so a cache
 * for the life of the page is exact rather than merely cheap.
 */
interface Organization {
  appearance_resolved: Appearance;
  /** IANA name. Every period boundary and every time a contest is set in. */
  timezone: string;
}

let pending: Promise<Organization> | null = null;

//: Components currently showing it, so a save reaches them without a reload.
const listeners = new Set<(next: Organization) => void>();

/**
 * The organization, from the one shared request.
 *
 * **Everything that needs it asks here.** Sign-in used to fetch it for the
 * brand while this module fetched it again for the header, so every page load
 * asked twice (QA-28).
 */
export function loadOrganization(): Promise<Organization> {
  pending ??= api<Organization>('/api/organization').catch((err) => {
    // A failed fetch must not become a permanent one. Clearing the cache means
    // the next reader tries again rather than inheriting a rejection from a
    // request that failed while the server was restarting.
    pending = null;
    throw err;
  });
  return pending;
}

/**
 * Forget the cached answer and tell everyone showing it.
 *
 * Called after a save, and on signing in, since the next person may belong to
 * another organization. **Re-fetching rather than accepting the new value from
 * the caller** because the server resolves defaults the client does not — a
 * cleared field comes back as the built-in rather than as absent, and a header
 * showing "absent" would draw nothing.
 */
export function forgetOrgAppearance(): void {
  pending = null;
  if (listeners.size === 0) return;
  loadOrganization()
    .then((next) => listeners.forEach((notify) => notify(next)))
    .catch(() => undefined);
}

function useOrganization(): Organization | null {
  const [org, setOrg] = useState<Organization | null>(null);

  useEffect(() => {
    let live = true;
    const notify = (next: Organization) => {
      if (live) setOrg(next);
    };
    listeners.add(notify);

    loadOrganization()
      .then(notify)
      .catch(() => undefined);

    return () => {
      live = false;
      listeners.delete(notify);
    };
  }, []);

  return org;
}

/**
 * The organization's resolved appearance, or `null` until it arrives.
 *
 * `null` is not an error state: callers fall back to the built-in defaults, so
 * a page stays usable even if the request never lands.
 */
export function useOrgAppearance(): Appearance | null {
  return useOrganization()?.appearance_resolved ?? null;
}

/**
 * The organization's timezone, or `null` until it arrives.
 *
 * Callers fall back to the browser's zone meanwhile, and hold instants rather
 * than wall-clock strings, so the answer arriving changes how a time is shown
 * and never which time it is.
 */
export function useOrgTimezone(): string | null {
  return useOrganization()?.timezone ?? null;
}
