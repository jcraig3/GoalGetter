/**
 * Turning a connector's JSON Schema into a form, with no React in sight.
 *
 * A connector declares its settings as a Pydantic model; the API sends that
 * model's JSON Schema; this reads it. So a new connector arrives with its own
 * labels, hints and examples and the wizard renders them without knowing what a
 * warehouse role is — which is the whole reason the protocol carries schemas
 * rather than a hand-written field list per connector.
 *
 * Pulled out here because reading JSON Schema is fiddly in specific ways — an
 * optional integer is `anyOf: [integer, null]`, not `integer` — and fiddly logic
 * inside a component is logic nobody can test.
 */

export type FieldKind = 'text' | 'multiline' | 'number' | 'boolean' | 'pairs';

export interface FormField {
  name: string;
  label: string;
  kind: FieldKind;
  hint?: string;
  placeholder?: string;
  /** Present when the schema restricts the value to a known set. */
  choices?: string[];
  /** What to show for each choice, when the stored value is not readable. */
  choiceLabels?: Record<string, string>;
  /**
   * True when the connector marked this as something most people never touch.
   *
   * Rendered behind a disclosure rather than omitted. The generic API connector
   * genuinely needs fourteen answers and there is no honest way to guess them —
   * but showing all fourteen at once makes the three that matter impossible to
   * find, and hiding the other eleven would make the connector useless for the
   * case it exists to serve.
   */
  advanced: boolean;
  required: boolean;
  /** What the field holds before anybody touches it. */
  initial: string;
}

/** The shape of the bits of JSON Schema this reads. Deliberately loose. */
interface Property {
  type?: string;
  anyOf?: { type?: string }[];
  title?: string;
  description?: string;
  default?: unknown;
  examples?: unknown[];
  enum?: unknown[];
  /**
   * Readable names for the values in `enum`, keyed by value.
   *
   * Without it a choice renders as whatever it is stored as — `full` and
   * `incremental` rather than "Everything, every time" and "Only what changed".
   * The stored value is the API's vocabulary; this is the reader's.
   */
  enum_labels?: Record<string, string>;
  multiline?: boolean;
  advanced?: boolean;
  /**
   * Set by the schema for a value no person types — an id, or a name a picker
   * fills in. Distinct from `advanced`, which collapses a field somebody might
   * still want: this one removes it.
   */
  hidden?: boolean;
}

interface Schema {
  properties?: Record<string, Property>;
  required?: string[];
}

/**
 * The types a property allows, with `null` meaning "and it may be omitted".
 *
 * `int | None` in Python becomes `anyOf: [{integer}, {null}]` with no top-level
 * `type` at all, so reading `type` alone reports every optional field as
 * untyped — and an untyped field renders as text, which is how a port number
 * ends up accepting "eighty".
 */
export function typesOf(property: Property): string[] {
  if (property.anyOf) {
    return property.anyOf.map((entry) => entry.type ?? 'string');
  }
  return [property.type ?? 'string'];
}

/** Title case from a snake_case name, for a schema that gave no title. */
export function humanise(name: string): string {
  const words = name.split(/[^A-Za-z0-9]+/).filter(Boolean);
  if (words.length === 0) return name;
  const [first, ...rest] = words as [string, ...string[]];
  return [first.charAt(0).toUpperCase() + first.slice(1), ...rest].join(' ');
}

/**
 * One form field per property, in the order the model declared them.
 *
 * Declaration order is kept because it is the order a person chose — host before
 * database before query is how somebody thinks about connecting to a database,
 * and the alphabet would open the form on "database".
 */
export function formFields(schema: Schema, values: Record<string, unknown> = {}): FormField[] {
  // **`hidden` means gone, not tucked away.** These are ids and names a picker
  // sets; there is nothing a person could usefully type into them, and one was
  // rendering as a text box captioned with its own implementation notes.
  // `advanced` is the collapse; this is the omission.
  const properties = Object.entries(schema.properties ?? {}).filter(
    ([, property]) => property.hidden !== true,
  );
  const required = new Set(schema.required ?? []);

  return properties.map(([name, property]) => {
    const types = typesOf(property);
    const kind: FieldKind = property.multiline
      ? 'multiline'
      : types.includes('boolean')
        ? 'boolean'
        : types.includes('integer') || types.includes('number')
          ? 'number'
          : types.includes('object')
            ? 'pairs'
            : 'text';

    // The stored value wins over the schema's default: this form is used both to
    // set something up and to edit it later, and an edit form showing defaults
    // instead of what is saved is a form that silently reverts things.
    const held = values[name];
    const fallback = property.default;
    const initial =
      held !== undefined && held !== null
        ? kind === 'pairs'
          ? serialisePairs(held as Record<string, string>)
          : String(held)
        : fallback === undefined || fallback === null
          ? ''
          : kind === 'pairs'
            ? serialisePairs(fallback as Record<string, string>)
            : String(fallback);

    return {
      name,
      label: property.title ?? humanise(name),
      kind,
      hint: property.description,
      placeholder: property.examples?.[0] === undefined ? undefined : String(property.examples[0]),
      choices: property.enum?.map(String),
      choiceLabels: property.enum_labels,
      advanced: property.advanced === true,
      // Pydantic marks a field required by omitting it from `default`, and the
      // schema's own `required` list is authoritative. A field with a default is
      // never required, whatever else is true.
      required: required.has(name),
      initial,
    };
  });
}

/**
 * `name=value` lines into an object.
 *
 * A textarea rather than a repeating row editor, because the realistic content is
 * one line — `sslmode=require` — and a two-column widget for one line is more
 * chrome than the thing it holds. Blank lines and stray spaces are forgiven; a
 * line with no `=` is dropped rather than stored under an empty key, which would
 * be silently rejected by the API later.
 */
export function parsePairs(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const at = line.indexOf('=');
    if (at < 0) continue;
    const key = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim();
    // One guard, not two: a line starting with `=` has an empty key and is
    // dropped here, so also excluding `at === 0` above said the same thing twice.
    // Found by mutation testing, which could not tell the two versions apart.
    if (key) out[key] = value;
  }
  return out;
}

/** The inverse, so an edit form shows what was saved. */
export function serialisePairs(pairs: Record<string, string> | null | undefined): string {
  if (!pairs) return '';
  return Object.entries(pairs)
    .map(([key, value]) => `${key}=${value}`)
    .join('\n');
}

/**
 * The values a form is holding, as the API wants them.
 *
 * Typed on the way out rather than on the way in, so a half-typed number is
 * allowed to exist in the field while somebody is thinking. An empty optional
 * number becomes `null` rather than `0`: a port left blank means "use the
 * default", and zero is a port.
 */
export function toPayload(
  fields: FormField[],
  text: Record<string, string>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = text[field.name] ?? '';
    if (field.kind === 'number') {
      out[field.name] = raw.trim() === '' ? null : Number(raw);
    } else if (field.kind === 'boolean') {
      out[field.name] = raw === 'true';
    } else if (field.kind === 'pairs') {
      out[field.name] = parsePairs(raw);
    } else {
      out[field.name] = raw;
    }
  }
  return out;
}

/**
 * Which required fields are still empty.
 *
 * Named rather than counted, so the form can say what is missing instead of
 * refusing to submit for reasons the reader has to hunt for.
 */
export function missing(fields: FormField[], text: Record<string, string>): string[] {
  return fields
    .filter((field) => field.required && !(text[field.name] ?? '').trim())
    .map((field) => field.label);
}
