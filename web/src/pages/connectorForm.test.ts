import { describe, expect, it } from 'vitest';

import {
  formFields,
  humanise,
  missing,
  parsePairs,
  serialisePairs,
  toPayload,
  typesOf,
} from './connectorForm';

/** The SQL connector's real schema, trimmed — the shape this has to read. */
const SQL_CONFIG = {
  properties: {
    dialect: {
      default: 'postgresql',
      enum: ['postgresql'],
      title: 'Database type',
      type: 'string',
    },
    host: { default: '', examples: ['db.internal'], title: 'Host', type: 'string' },
    port: {
      anyOf: [{ type: 'integer' }, { type: 'null' }],
      default: null,
      description: 'Leave empty for the default.',
      title: 'Port',
    },
    database: { default: '', title: 'Database name', type: 'string' },
    query: {
      default: '',
      description: 'Must use :since so each sync only reads what changed.',
      examples: ['SELECT 1 WHERE updated_at >= :since'],
      multiline: true,
      title: 'Query',
      type: 'string',
    },
    options: {
      default: {},
      description: 'One per line, as name=value.',
      title: 'Driver options',
      type: 'object',
    },
  },
};

describe('typesOf', () => {
  it('reads a plain type', () => {
    expect(typesOf({ type: 'string' })).toEqual(['string']);
  });

  it('reads an optional integer, which has no top-level type at all', () => {
    // `int | None` becomes anyOf with no `type` beside it. Reading `type` alone
    // reports every optional field as untyped, and untyped renders as text —
    // which is how a port ends up accepting "eighty".
    expect(typesOf({ anyOf: [{ type: 'integer' }, { type: 'null' }] })).toEqual([
      'integer',
      'null',
    ]);
  });

  it('assumes string when the schema says nothing', () => {
    expect(typesOf({})).toEqual(['string']);
  });
});

describe('humanise', () => {
  it('makes a label out of a field name', () => {
    expect(humanise('signing_secret')).toBe('Signing secret');
  });

  it('leaves an already-readable name alone', () => {
    expect(humanise('Host')).toBe('Host');
  });

  it('does not capitalise every word, which reads like a headline', () => {
    expect(humanise('api_base_url')).toBe('Api base url');
  });

  it('survives a name with nothing in it to split', () => {
    expect(humanise('')).toBe('');
  });
});

describe('formFields', () => {
  it('reads the SQL connector schema into a form', () => {
    const fields = formFields(SQL_CONFIG);

    expect(fields.map((f) => [f.name, f.kind])).toEqual([
      ['dialect', 'text'],
      ['host', 'text'],
      ['port', 'number'],
      ['database', 'text'],
      ['query', 'multiline'],
      ['options', 'pairs'],
    ]);
  });

  it('keeps declaration order, not alphabetical order', () => {
    // Host before database before query is how somebody thinks about connecting
    // to a database. The alphabet would open the form on "database".
    expect(formFields(SQL_CONFIG)[0]?.name).toBe('dialect');
  });

  it('carries the label, hint and placeholder the connector wrote', () => {
    const fields = formFields(SQL_CONFIG);
    const dialect = fields.find((f) => f.name === 'dialect');
    const port = fields.find((f) => f.name === 'port');
    const host = fields.find((f) => f.name === 'host');

    // `dialect` on purpose: its title is "Database type", so a form that fell back
    // to the field name would say "Dialect" and look perfectly plausible. `port`
    // and `host` cannot tell the two apart, because their titles are exactly what
    // humanising the name produces anyway.
    expect(dialect?.label).toBe('Database type');
    expect(port?.hint).toBe('Leave empty for the default.');
    expect(host?.placeholder).toBe('db.internal');
  });

  it('offers a choice list when the schema restricts the value', () => {
    // Only the dialects this build can reach — offering one that fails on connect
    // is worse than not offering it.
    expect(formFields(SQL_CONFIG).find((f) => f.name === 'dialect')?.choices).toEqual([
      'postgresql',
    ]);
  });

  it('falls back to the field name when there is no title', () => {
    const fields = formFields({ properties: { api_token: { type: 'string' } } });

    expect(fields[0]?.label).toBe('Api token');
  });

  it('marks a field required only when the schema says so', () => {
    const fields = formFields({
      properties: { a: { type: 'string' }, b: { type: 'string' } },
      required: ['b'],
    });

    expect(fields.map((f) => f.required)).toEqual([false, true]);
  });

  it('starts a field at its default', () => {
    expect(formFields(SQL_CONFIG).find((f) => f.name === 'dialect')?.initial).toBe(
      'postgresql',
    );
  });

  it('shows an empty string for a default of null rather than the word null', () => {
    expect(formFields(SQL_CONFIG).find((f) => f.name === 'port')?.initial).toBe('');
  });

  it('prefers a saved value over the default', () => {
    // The same form sets a source up and edits it later. Showing defaults instead
    // of what is stored is a form that silently reverts things.
    const fields = formFields(SQL_CONFIG, { host: 'reporting.internal', port: 5433 });

    expect(fields.find((f) => f.name === 'host')?.initial).toBe('reporting.internal');
    expect(fields.find((f) => f.name === 'port')?.initial).toBe('5433');
  });

  it('renders a saved object field as editable lines', () => {
    const fields = formFields(SQL_CONFIG, { options: { sslmode: 'require' } });

    expect(fields.find((f) => f.name === 'options')?.initial).toBe('sslmode=require');
  });

  it('reads a boolean as a toggle', () => {
    const fields = formFields({
      properties: { require_signature: { type: 'boolean', default: false } },
    });

    expect(fields[0]?.kind).toBe('boolean');
    expect(fields[0]?.initial).toBe('false');
  });

  it('has nothing to show for a connector that needs no settings', () => {
    expect(formFields({})).toEqual([]);
  });
});

describe('advanced fields', () => {
  it('is off unless the connector says otherwise', () => {
    expect(formFields(SQL_CONFIG).every((f) => !f.advanced)).toBe(true);
  });

  it('is read from the schema', () => {
    const fields = formFields({
      properties: {
        host: { type: 'string' },
        options: { type: 'object', advanced: true },
      },
    });

    expect(fields.map((f) => [f.name, f.advanced])).toEqual([
      ['host', false],
      ['options', true],
    ]);
  });

  it('does not make a field optional, or required', () => {
    // Tucked away is not the same as unimportant. A required advanced field still
    // has to be filled in, and the form still has to say so.
    const fields = formFields(
      { properties: { key: { type: 'string', advanced: true } }, required: ['key'] },
    );

    expect(fields[0]?.required).toBe(true);
    expect(missing(fields, {})).toEqual(['Key']);
  });
});

describe('parsePairs', () => {
  it('reads name=value lines', () => {
    expect(parsePairs('sslmode=require\nrole=analyst')).toEqual({
      sslmode: 'require',
      role: 'analyst',
    });
  });

  it('forgives blank lines and stray spaces', () => {
    expect(parsePairs('\n  sslmode = require  \n\n')).toEqual({ sslmode: 'require' });
  });

  it('keeps an = inside the value, because passwords and DSNs contain them', () => {
    expect(parsePairs('opts=a=b')).toEqual({ opts: 'a=b' });
  });

  it('drops a line with no = rather than storing an empty key', () => {
    // Which the API would reject later, from a screen that had said nothing.
    expect(parsePairs('sslmode')).toEqual({});
  });

  it('drops a line that starts with =, for the same reason', () => {
    expect(parsePairs('=require')).toEqual({});
  });

  it('allows an empty value, which some drivers use as a flag', () => {
    expect(parsePairs('readonly=')).toEqual({ readonly: '' });
  });
});

describe('serialisePairs', () => {
  it('round-trips through parsePairs', () => {
    const text = 'sslmode=require\nrole=analyst';
    expect(serialisePairs(parsePairs(text))).toBe(text);
  });

  it('has nothing to show for nothing', () => {
    expect(serialisePairs({})).toBe('');
    expect(serialisePairs(null)).toBe('');
    expect(serialisePairs(undefined)).toBe('');
  });
});

describe('toPayload', () => {
  const fields = formFields(SQL_CONFIG);

  it('sends text as text', () => {
    const body = toPayload(fields, { host: 'db.internal' });
    expect(body.host).toBe('db.internal');
  });

  it('sends a number as a number, not a string', () => {
    expect(toPayload(fields, { port: '5432' }).port).toBe(5432);
  });

  it('sends an empty optional number as null rather than zero', () => {
    // A blank port means "use the default". Zero is a port.
    expect(toPayload(fields, { port: '' }).port).toBeNull();
  });

  it('sends object lines as an object', () => {
    expect(toPayload(fields, { options: 'sslmode=require' }).options).toEqual({
      sslmode: 'require',
    });
  });

  it('sends a boolean as a boolean', () => {
    const toggle = formFields({ properties: { on: { type: 'boolean' } } });

    expect(toPayload(toggle, { on: 'true' }).on).toBe(true);
    expect(toPayload(toggle, { on: 'false' }).on).toBe(false);
  });

  it('includes a field nobody touched, so a cleared value really clears', () => {
    expect(toPayload(fields, {}).host).toBe('');
  });
});

describe('missing', () => {
  const fields = formFields({
    properties: { host: { type: 'string', title: 'Host' }, note: { type: 'string' } },
    required: ['host'],
  });

  it('names what is missing rather than counting it', () => {
    expect(missing(fields, {})).toEqual(['Host']);
  });

  it('treats whitespace as empty', () => {
    expect(missing(fields, { host: '   ' })).toEqual(['Host']);
  });

  it('is satisfied by a real value', () => {
    expect(missing(fields, { host: 'db.internal' })).toEqual([]);
  });

  it('ignores an empty optional field', () => {
    expect(missing(fields, { host: 'db.internal', note: '' })).toEqual([]);
  });
});
