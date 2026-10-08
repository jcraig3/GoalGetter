import { useState } from 'react';

/**
 * A labelled text input.
 *
 * Constraints are declared on the field rather than checked in each form's
 * submit handler, so a field cannot hold a value its own rules reject — and a
 * new form gets the same behaviour without remembering to write it.
 */

export interface NumericRule {
  /** 0 means integers only. Defaults to 2. */
  decimals?: number;
  allowNegative?: boolean;
  min?: number;
  max?: number;
}

interface FieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /**
   * `datetime-local` is for a competition's start and end. It reads and writes
   * wall-clock strings with no zone in them, so the caller is responsible for
   * converting to and from UTC — see `toLocalInput`/`fromLocalInput` in
   * pages/competitionClock.ts.
   */
  type?: 'text' | 'email' | 'password' | 'date' | 'datetime-local';
  /**
   * Accept numbers only. Mutually exclusive with `type`.
   *
   * Deliberately NOT `<input type="number">`. That control accepts `1e5` and
   * `--`, reports an empty string for anything it considers invalid — so the
   * form cannot tell "blank" from "nonsense" — and changes its value when a
   * scroll wheel passes over it. Filtering a text input keeps every keystroke
   * inspectable and the value always exactly what is on screen.
   */
  numeric?: NumericRule;
  /** Characters allowed, as a regex. Rejected keystrokes never land. */
  allow?: RegExp;
  autoComplete?: string;
  /**
   * Greyed example text, shown only while the field is empty.
   *
   * For a shape somebody has to match — `db.internal`, a port, a query — where
   * seeing one is faster than reading a description of one. Not a substitute for
   * `hint`: a placeholder vanishes the moment anybody types, so anything that
   * still matters once the field has content belongs in the hint.
   */
  placeholder?: string;
  hint?: string;
  invalid?: boolean;
  autoFocus?: boolean;
  maxLength?: number;
  /** Defaults to true. Every field built so far has been mandatory, so the
   *  safe default is the one that refuses an empty submit; genuinely optional
   *  fields opt out. */
  //:
  //: **A field labelled "(optional)" needs this explicitly.** The default
  //: refuses an empty submit, so a hint saying "leave empty" is a promise the
  //: browser then breaks with "please fill out this field". That shipped in
  //: five places before anybody tried it.
  required?: boolean;
}

/** The strings a partially-typed number is allowed to pass through. */
export function numericPattern({ decimals = 2, allowNegative = false }: NumericRule): RegExp {
  const sign = allowNegative ? '-?' : '';
  // The fractional part is optional and may be empty mid-typing, so "12." is
  // accepted on the way to "12.5". Rejecting it would make the decimal point
  // impossible to type at all.
  const fraction = decimals > 0 ? `(\\.\\d{0,${decimals}})?` : '';
  return new RegExp(`^${sign}\\d*${fraction}$`);
}

/** Why the value is out of range, or null. Shape is already filtered. */
export function rangeError(value: string, rule: NumericRule): string | null {
  // Mid-typing states are not errors yet — flagging "-" the moment someone
  // starts a negative number would make the field feel broken.
  if (value === '' || value === '-' || value.endsWith('.')) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 'Enter a number.';
  if (rule.min !== undefined && parsed < rule.min) return `Must be at least ${rule.min}.`;
  if (rule.max !== undefined && parsed > rule.max) return `Must be at most ${rule.max}.`;
  return null;
}

/**
 * What a numeric field accepts, as a sentence: "Whole number, 0 or more."
 *
 * Said when a keystroke is refused. The field used to swallow `-` or `a`
 * without a word, so it looked broken rather than strict (QA-6).
 */
export function allowedNumbers(rule: NumericRule): string {
  const kind = rule.decimals === 0 ? 'Whole number' : 'A number';
  const low = rule.min ?? (rule.allowNegative ? undefined : 0);
  if (low !== undefined && rule.max !== undefined) return `${kind}, ${low}–${rule.max}.`;
  if (low !== undefined) return `${kind}, ${low} or more.`;
  if (rule.max !== undefined) return `${kind}, ${rule.max} or less.`;
  return `${kind}.`;
}

/**
 * A stored decimal as the shortest thing worth typing.
 *
 * `NUMERIC(18,4)` comes back from the API as `"25.0000"`, and putting that
 * straight into a form gives somebody four decimal places to delete before they
 * can edit their own number.
 *
 * Done on the string rather than via `String(Number(value))`, which is the
 * shorter version and was already in use in two other forms. Doubles lose
 * precision above 2^53, so that round trip can quietly alter a large currency
 * total — the exact thing MetricValue.tsx warns about. Trimming characters
 * cannot.
 *
 * Anything that is not a plain decimal is returned untouched: this is a
 * presentation step, not a validator, and mangling an unexpected value would
 * hide the problem rather than show it.
 */
export function forInput(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '';
  const text = String(value).trim();
  if (!/^-?\d*\.\d+$/.test(text)) return text;

  // Guarded on the regex above requiring a decimal point, which is what keeps
  // this away from "1000" — stripping trailing zeros from an integer would turn
  // a target of ten thousand into one.
  const trimmed = text.replace(/0+$/, '').replace(/\.$/, '');
  // Any flavour of zero becomes a plain "0". Without this, "-0.0000" trims to
  // "-0", which is a real string a real column can produce and nobody wants to
  // see in a form.
  return /^-?0*$/.test(trimmed) ? '0' : trimmed;
}

/**
 * The value a keystroke should leave in the field.
 *
 * Exported and pure so the rules can be tested directly. Reimplementing this
 * in a test would mean the test keeps passing after the component stops
 * calling it.
 */
export function filterInput(
  current: string,
  next: string,
  rules: { numeric?: NumericRule; allow?: RegExp },
): string {
  // Clearing a field is always allowed, or a rule could trap a value the user
  // has no way to remove.
  if (next === '') return '';
  if (rules.numeric && !numericPattern(rules.numeric).test(next)) return current;
  if (rules.allow && !rules.allow.test(next)) return current;
  return next;
}

export default function Field({
  label,
  value,
  onChange,
  type = 'text',
  numeric,
  allow,
  autoComplete,
  placeholder,
  hint,
  invalid,
  autoFocus,
  maxLength,
  required = true,
}: FieldProps) {
  const id = label.toLowerCase().replace(/\s+/g, '-');

  // The last keystroke this field refused, and why — cleared by the next one
  // it accepts.
  const [refused, setRefused] = useState<string | null>(null);

  const outOfRange = numeric ? rangeError(value, numeric) : null;
  const showInvalid = invalid || !!outOfRange || !!refused;
  const message = refused ?? outOfRange ?? hint;

  function handle(next: string) {
    const accepted = filterInput(value, next, { numeric, allow });
    if (accepted === value && next !== value) {
      // Refused, and said so rather than silently dropped.
      setRefused(numeric ? allowedNumbers(numeric) : 'That character is not allowed here.');
      return;
    }
    setRefused(null);
    // Only notify on a real change, so a rejected keystroke does not re-render
    // the form for nothing.
    if (accepted !== value) onChange(accepted);
  }

  return (
    <div>
      {/* htmlFor/id pairing means clicking the label focuses the input, and
          screen readers announce the two together. */}
      <label htmlFor={id} className="block text-sm text-content-muted">
        {label}
      </label>
      <input
        id={id}
        type={numeric ? 'text' : type}
        // The right on-screen keyboard on a phone, without the desktop
        // drawbacks of type="number".
        inputMode={numeric ? (numeric.decimals === 0 ? 'numeric' : 'decimal') : undefined}
        value={value}
        required={required}
        maxLength={maxLength}
        autoFocus={autoFocus}
        autoComplete={autoComplete}
        placeholder={placeholder}
        aria-describedby={message ? `${id}-hint` : undefined}
        aria-invalid={showInvalid || undefined}
        onChange={(e) => handle(e.target.value)}
        className={`mt-1 w-full rounded-md border bg-bg px-3 py-2 text-content outline-none focus:border-brand ${
          showInvalid ? 'border-danger' : 'border-edge'
        }`}
      />
      {message && (
        <p
          id={`${id}-hint`}
          className={`mt-1 text-xs ${showInvalid ? 'text-danger' : 'text-content-muted'}`}
        >
          {message}
        </p>
      )}
    </div>
  );
}
