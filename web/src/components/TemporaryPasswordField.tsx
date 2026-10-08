import Field from './Field';
import { PASSWORD_HINT, passwordProblem, suggestPassword } from '../passwordRule';

/**
 * A password an admin sets for somebody, to be replaced at first sign-in (11.2).
 *
 * Shown in plain text, not dots: the admin has to read it out or paste it to
 * somebody, and nobody else is looking at their screen for the few seconds it
 * exists. "Suggest one" offers four words and a number, which is easy to say
 * aloud and well past the rule.
 */
export default function TemporaryPasswordField({
  value,
  onChange,
  autoFocus = false,
}: {
  value: string;
  onChange: (value: string) => void;
  autoFocus?: boolean;
}) {
  const problem = passwordProblem(value);
  return (
    <div>
      <Field
        label="Temporary password"
        value={value}
        onChange={onChange}
        autoComplete="off"
        autoFocus={autoFocus}
        invalid={problem !== null}
        hint={problem ?? `${PASSWORD_HINT} They choose their own when they sign in.`}
      />
      <button
        type="button"
        onClick={() => onChange(suggestPassword())}
        className="mt-1 text-sm text-brand hover:underline"
      >
        Suggest one
      </button>
    </div>
  );
}
