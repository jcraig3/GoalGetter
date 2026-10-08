/**
 * Timezones in words (review §7): "Pacific Time — Los Angeles (UTC−7)", not
 * "America/Los_Angeles" in a list of ~600 sorted by continent.
 *
 * The names come from the browser's own tz data, as the list does, so nothing
 * here goes stale. The common zones come first; the rest are sorted by their
 * label, so typing "Pac" in the closed list jumps to Pacific Time.
 */

/** Where most organizations using this are; first, so they need no scrolling. */
export const COMMON_ZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'Europe/London',
  'UTC',
];

function part(tz: string, at: Date, style: Intl.DateTimeFormatOptions['timeZoneName']): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: style }).formatToParts(at);
    return parts.find((p) => p.type === 'timeZoneName')?.value ?? '';
  } catch {
    return '';
  }
}

/** "Los Angeles", "Argentina / Buenos Aires". */
function place(tz: string): string {
  const [, ...rest] = tz.split('/');
  return (rest.length > 0 ? rest : [tz]).join(' / ').replace(/_/g, ' ');
}

/** "Pacific Time — Los Angeles (UTC−7)". */
export function zoneLabel(tz: string, at: Date = new Date()): string {
  if (tz === 'UTC') return 'UTC — Coordinated Universal Time';
  const offset = part(tz, at, 'shortOffset').replace('GMT', 'UTC').replace('-', '−') || 'UTC';
  const name = part(tz, at, 'longGeneric');
  // Where the browser has no name of its own it says the offset again.
  const said = name && !name.startsWith('GMT') ? `${name} — ${place(tz)}` : place(tz);
  return `${said} (${offset})`;
}

export interface ZoneChoice {
  value: string;
  label: string;
}

/** The common zones, then everything else by label. */
export function zoneChoices(zones: string[], at: Date = new Date()): { common: ZoneChoice[]; rest: ZoneChoice[] } {
  const known = new Set(zones);
  const common = COMMON_ZONES.filter((tz) => tz === 'UTC' || known.has(tz)).map((tz) => ({
    value: tz,
    label: zoneLabel(tz, at),
  }));
  const rest = zones
    .filter((tz) => !COMMON_ZONES.includes(tz))
    .map((tz) => ({ value: tz, label: zoneLabel(tz, at) }))
    .sort((a, b) => a.label.localeCompare(b.label));
  return { common, rest };
}
