/**
 * Sorting and searching the connector list, with no React in sight.
 *
 * Fourteen connectors is well past the point where a flat grid stops being a list
 * and starts being a wall. Grouping and a search box are the standard answer, and both are
 * decisions — which group, and what counts as a match — so they live here where
 * they can be tested rather than inside a component where they cannot.
 */

/**
 * The little a connector has to say about itself to be pickable.
 *
 * Narrower than the API's `ConnectorOption`, which carries config schemas and
 * credential schemas as well — deliberately, so this module cannot start
 * depending on things a card does not show. `oauth` is here because the search
 * reads the provider's name from it: somebody types *microsoft* looking for Excel.
 */
export interface Pickable {
  key: string;
  display_name: string;
  oauth: { provider: string; provider_name: string } | null;
}

/**
 * The groups, in the order they are shown.
 *
 * Ordered by how likely somebody is to want one, not alphabetically. Spreadsheets
 * first because that is where numbers live in a company that has not built a
 * pipeline; the escape hatches last because you only reach for them once nothing
 * above fits.
 *
 * **"Custom connections" holds exactly two things, and always will: the webhook and
 * the generic API connector.** The name is doing work: it says what the group *is*
 * — the pair of general-purpose tools you build your own integration with — rather
 * than what it is not. "Anything else" was the earlier name and read as a leftovers
 * bin, which invited putting a product there when nobody had classified it. Every
 * named product belongs in a category that says what it is.
 */
export const GROUPS = [
  'Spreadsheets',
  'CRM',
  'Helpdesk',
  'Calls and conversations',
  'Databases',
  'Custom connections',
] as const;

export type Group = (typeof GROUPS)[number];

/** Which group each connector belongs to. Everything unlisted falls through. */
const PLACED: Record<string, Group> = {
  google_sheets: 'Spreadsheets',
  microsoft_excel: 'Spreadsheets',

  hubspot: 'CRM',
  salesforce: 'CRM',
  pipedrive: 'CRM',
  close: 'CRM',

  freshdesk: 'Helpdesk',
  zendesk: 'Helpdesk',

  // Not CRMs. They measure the conversation rather than the deal, which is a
  // different question a sales leader asks — and the leading indicator rather than
  // the trailing one.
  gong: 'Calls and conversations',
  aircall: 'Calls and conversations',

  sql: 'Databases',
  snowflake: 'Databases',
};

export function groupOf(connector: Pickable): Group {
  // Falling through to "Custom connections" is for a connector nobody has classified
  // *yet* — it should appear on the page before somebody remembers to add a line
  // above, because in the wrong group is a far smaller failure than invisible.
  // Every connector this build ships is placed on purpose.
  return PLACED[connector.key] ?? 'Custom connections';
}

/**
 * What somebody might type to find a connector.
 *
 * More than the display name, because people search for the thing they have rather
 * than the name we gave it: *excel* should find Excel, but so should *xlsx* and
 * *microsoft*; *postgres* should find the SQL connector, which is not called that.
 */
const ALSO_KNOWN_AS: Record<string, string[]> = {
  // `snowflake` stays in this list even though it has a connector of its own.
  // It is a dialect of the generic one too, and that is the route for a build
  // whose image was stripped of the driver — so searching for it has to surface
  // both, not the one we happened to think of first.
  sql: ['postgres', 'postgresql', 'mysql', 'mariadb', 'snowflake', 'redshift',
        'sql server', 'mssql', 'database', 'warehouse', 'query'],
  snowflake: ['warehouse', 'database', 'sql', 'data cloud'],
  microsoft_excel: ['xlsx', 'microsoft', 'office', '365', 'onedrive', 'sharepoint',
                    'spreadsheet'],
  google_sheets: ['gsheet', 'gsheets', 'google', 'spreadsheet', 'drive'],
  webhook: ['zapier', 'push', 'http', 'post', 'events', 'realtime', 'make'],
  api: ['rest', 'json', 'http', 'endpoint', 'custom', 'anything'],
  hubspot: ['crm', 'deals'],
  salesforce: ['crm', 'sfdc', 'opportunity', 'soql'],
  pipedrive: ['crm', 'deals'],
  freshdesk: ['tickets', 'support', 'helpdesk', 'freshworks'],
  zendesk: ['tickets', 'support', 'helpdesk'],
  close: ['crm', 'closeio', 'leads', 'opportunities'],
  gong: ['calls', 'conversation intelligence', 'revenue intelligence', 'recordings'],
  aircall: ['calls', 'phone', 'dialer', 'voip'],
};

/**
 * Whether a connector matches what was typed.
 *
 * Substring rather than word-prefix, because the useful queries here are partial:
 * somebody types *sheet* looking for Google Sheets, or *fresh* for Freshdesk.
 * Case and surrounding space are ignored — a pasted product name usually arrives
 * with both.
 */
export function matches(connector: Pickable, query: string): boolean {
  const wanted = query.trim().toLowerCase();
  if (!wanted) return true;

  const haystack = [
    connector.display_name,
    connector.key,
    connector.oauth?.provider_name ?? '',
    ...(ALSO_KNOWN_AS[connector.key] ?? []),
  ]
    .join(' ')
    .toLowerCase();

  return haystack.includes(wanted);
}

/**
 * The shortest list worth putting structure around.
 *
 * A search box and six headings over three connectors is chrome around nothing —
 * the whole list is already one glance. Past roughly half a dozen it stops being a
 * glance and starts being reading, which is where both start earning their space.
 *
 * One threshold for both, because they answer the same problem, and a build with a
 * search box but no headings would be a strange half-measure.
 */
export const STRUCTURE_AT = 6;

export function needsStructure(count: number): boolean {
  return count >= STRUCTURE_AT;
}

export interface Grouped {
  group: Group;
  connectors: Pickable[];
}

/**
 * The connectors that match, in groups, with empty groups left out.
 *
 * Empty groups are dropped rather than shown empty: a search for *sheet* that
 * printed five bare headings above one result would be almost entirely chrome.
 */
export function grouped(connectors: Pickable[], query = ''): Grouped[] {
  const hits = connectors.filter((connector) => matches(connector, query));

  return GROUPS.map((group) => ({
    group,
    connectors: hits
      .filter((connector) => groupOf(connector) === group)
      // Inside a group, alphabetical: there is no meaningful priority between two
      // CRMs, and a stable order is worth more than an arbitrary one.
      .sort((a, b) => a.display_name.localeCompare(b.display_name)),
  })).filter((entry) => entry.connectors.length > 0);
}
