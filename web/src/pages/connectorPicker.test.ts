import { describe, expect, it } from 'vitest';

import {
  GROUPS,
  STRUCTURE_AT,
  grouped,
  groupOf,
  matches,
  needsStructure,
  type Pickable,
} from './connectorPicker';

function connector(key: string, display_name: string, extra: Partial<Pickable> = {}): Pickable {
  return { key, display_name, oauth: null, ...extra };
}

/**
 * The fourteen this build actually ships, so the tests describe the real page.
 *
 * **Deliberately not in alphabetical order.** An earlier version listed them
 * sorted, which meant "sorts alphabetically inside a group" passed with the sort
 * removed — the fixture was doing the work the code was supposed to.
 */
const ALL: Pickable[] = [
  connector('salesforce', 'Salesforce'),
  connector('webhook', 'Webhook'),
  connector('microsoft_excel', 'Excel', {
    oauth: { provider: 'microsoft', provider_name: 'Microsoft' },
  }),
  connector('hubspot', 'HubSpot'),
  connector('zendesk', 'Zendesk'),
  connector('api', 'Any JSON API'),
  connector('gong', 'Gong'),
  connector('pipedrive', 'Pipedrive'),
  connector('snowflake', 'Snowflake'),
  connector('google_sheets', 'Google Sheets', {
    oauth: { provider: 'google', provider_name: 'Google' },
  }),
  connector('aircall', 'Aircall'),
  connector('freshdesk', 'Freshdesk'),
  connector('close', 'Close'),
  connector('sql', 'SQL database'),
];

describe('groupOf', () => {
  it('places the spreadsheets together', () => {
    expect(groupOf(connector('google_sheets', 'Google Sheets'))).toBe('Spreadsheets');
    expect(groupOf(connector('microsoft_excel', 'Excel'))).toBe('Spreadsheets');
  });

  it('keeps the CRMs together and apart from the helpdesks', () => {
    for (const key of ['hubspot', 'salesforce', 'pipedrive', 'close']) {
      expect(groupOf(connector(key, key)), key).toBe('CRM');
    }
    for (const key of ['freshdesk', 'zendesk']) {
      expect(groupOf(connector(key, key)), key).toBe('Helpdesk');
    }
  });

  it('separates the call platforms, which measure something else', () => {
    // Gong and Aircall are about the conversation rather than the deal — the
    // leading indicator rather than the trailing one.
    for (const key of ['gong', 'aircall']) {
      expect(groupOf(connector(key, key)), key).toBe('Calls and conversations');
    }
  });

  it('files Snowflake as the database it is', () => {
    // It is its own connector as well as a dialect of the generic one, and a
    // warehouse under "Custom connections" would read as us not knowing what it was.
    expect(groupOf(connector('snowflake', 'Snowflake'))).toBe('Databases');
    expect(groupOf(connector('sql', 'SQL database'))).toBe('Databases');
  });

  it('reserves the last group for the two general-purpose tools', () => {
    // Not a leftovers bin: every named product is classified, and these two are
    // the escape hatch somebody with an unsupported system ends up reading.
    const elsewhere = ALL.filter((c) => groupOf(c) === 'Custom connections');

    expect(elsewhere.map((c) => c.key).sort()).toEqual(['api', 'webhook']);
  });

  it('gives an unplaced connector somewhere to go', () => {
    // A new connector should appear on the page before somebody remembers to
    // classify it — invisible is a worse failure than in the wrong group.
    expect(GROUPS).toContain(groupOf(connector('zoho', 'Zoho')));
  });
});

describe('matches', () => {
  it('finds a connector by its name', () => {
    expect(matches(connector('freshdesk', 'Freshdesk'), 'freshdesk')).toBe(true);
  });

  it('finds one from a partial word, because that is how people type', () => {
    expect(matches(connector('freshdesk', 'Freshdesk'), 'fresh')).toBe(true);
    expect(matches(connector('google_sheets', 'Google Sheets'), 'sheet')).toBe(true);
  });

  it('ignores case and surrounding space, which a pasted name arrives with', () => {
    expect(matches(connector('hubspot', 'HubSpot'), '  HUBSPOT ')).toBe(true);
  });

  it('finds the SQL connector by the database somebody actually has', () => {
    // Nobody looking for Postgres searches for "SQL database".
    const sql = connector('sql', 'SQL database');

    for (const query of ['postgres', 'mysql', 'redshift', 'warehouse']) {
      expect(matches(sql, query), query).toBe(true);
    }
  });

  it('answers a search for Snowflake with both routes to it', () => {
    // Its own connector, and the generic SQL one — which is the route for a build
    // whose image was stripped of the driver. Finding only one would hide the
    // answer from whoever needed the other.
    const found = grouped(ALL, 'snowflake').flatMap((entry) => entry.connectors);

    expect(found.map((c) => c.key).sort()).toEqual(['snowflake', 'sql']);
  });

  it('finds a call platform by the word calls, which neither is named', () => {
    for (const key of ['gong', 'aircall']) {
      expect(matches(connector(key, key), 'calls'), key).toBe(true);
    }
  });

  it('finds Excel by the words around it rather than the word Excel', () => {
    const excel = connector('microsoft_excel', 'Excel', {
      oauth: { provider: 'microsoft', provider_name: 'Microsoft' },
    });

    for (const query of ['xlsx', 'microsoft', 'onedrive', 'sharepoint', '365']) {
      expect(matches(excel, query), query).toBe(true);
    }
  });

  it('finds the webhook when somebody searches for Zapier', () => {
    // Which is a separate product on a competitor's list and the same connector
    // here — so searching for it has to land somewhere rather than nowhere.
    expect(matches(connector('webhook', 'Webhook'), 'zapier')).toBe(
      true,
    );
  });

  it('finds the CRMs by the word CRM, which none of them are called', () => {
    for (const key of ['hubspot', 'salesforce', 'pipedrive', 'close']) {
      expect(matches(connector(key, key), 'crm'), key).toBe(true);
    }
  });

  it('finds either helpdesk by the word tickets', () => {
    for (const key of ['freshdesk', 'zendesk']) {
      expect(matches(connector(key, key), 'tickets'), key).toBe(true);
    }
  });

  it('searches the display name, which the key does not always contain', () => {
    // A synthetic connector on purpose: every real one has a key spelling out its
    // own name, so a test using one cannot tell whether the name was consulted.
    expect(matches(connector('xyz', 'Widget'), 'widget')).toBe(true);
  });

  it('searches the provider it signs in to', () => {
    const odd = connector('xyz', 'Widget', {
      oauth: { provider: 'acme', provider_name: 'Acme Identity' },
    });

    expect(matches(odd, 'acme')).toBe(true);
  });

  it('lower-cases what it searches as well as what was typed', () => {
    // Both halves have to be folded. Every real connector's key is already
    // lowercase, so it quietly rescued a haystack that was not.
    expect(matches(connector('xyz', 'WIDGET'), 'widget')).toBe(true);
  });

  it('matches everything when nothing was typed', () => {
    expect(ALL.every((c) => matches(c, ''))).toBe(true);
    expect(ALL.every((c) => matches(c, '   '))).toBe(true);
  });

  it('matches nothing for a query nothing answers', () => {
    expect(ALL.some((c) => matches(c, 'carrier pigeon'))).toBe(false);
  });
});

describe('grouped', () => {
  it('shows every connector when nothing is typed', () => {
    const total = grouped(ALL).reduce((n, entry) => n + entry.connectors.length, 0);

    expect(total).toBe(ALL.length);
  });

  it('keeps the groups in their declared order, not alphabetically', () => {
    // Spreadsheets first because that is where numbers live in a company that has
    // not built a pipeline; the escape hatches last. Alphabetically this would
    // begin with "Custom connections", which is the one that has to be last.
    expect(grouped(ALL).map((entry) => entry.group)).toEqual([
      'Spreadsheets',
      'CRM',
      'Helpdesk',
      'Calls and conversations',
      'Databases',
      'Custom connections',
    ]);
  });

  it('sorts alphabetically inside a group', () => {
    const crm = grouped(ALL).find((entry) => entry.group === 'CRM');

    expect(crm?.connectors.map((c) => c.display_name)).toEqual([
      'Close',
      'HubSpot',
      'Pipedrive',
      'Salesforce',
    ]);
  });

  it('leaves out a group with nothing in it', () => {
    // A search for "sheet" that printed five bare headings above one result would
    // be almost entirely chrome.
    const found = grouped(ALL, 'sheet');

    expect(found.map((entry) => entry.group)).toEqual(['Spreadsheets']);
  });

  it('returns nothing at all rather than empty groups', () => {
    expect(grouped(ALL, 'carrier pigeon')).toEqual([]);
  });

  it('survives a build with no connectors', () => {
    expect(grouped([], 'anything')).toEqual([]);
  });
});

describe('needsStructure', () => {
  it('leaves a short list alone', () => {
    // Three cards need no search box. Asserted at 1 and at one below the
    // threshold, so an off-by-one in either direction shows up.
    expect(needsStructure(1)).toBe(false);
    expect(needsStructure(3)).toBe(false);
    expect(needsStructure(STRUCTURE_AT - 1)).toBe(false);
  });

  it('structures the list this build actually ships', () => {
    // The point of the threshold: fourteen connectors is a wall without it.
    expect(needsStructure(ALL.length)).toBe(true);
    expect(needsStructure(STRUCTURE_AT)).toBe(true);
  });

  it('handles a build with no connectors at all', () => {
    expect(needsStructure(0)).toBe(false);
  });
});
