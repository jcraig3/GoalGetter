import Field from './Field';
import Select from './Select';
import Toggle from './Toggle';
import { type FormField } from '../pages/connectorForm';

/**
 * A form a connector described rather than one somebody wrote for it.
 *
 * Every label, hint, placeholder and choice comes from the connector's own
 * Pydantic model, through its JSON Schema. So adding a connector adds its setup
 * form too — which is the difference between the seventh connector costing a day
 * and costing a week, and it means the person who knows what `sslmode` is for is
 * the person who writes the sentence about it.
 *
 * `connectorForm.formFields` does the reading; this only paints.
 */
export default function SchemaForm({
  fields,
  values,
  onChange,
  secret = false,
  disabled = false,
}: {
  fields: FormField[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  /**
   * Render text as password fields.
   *
   * For a credential schema. Not decided per field: everything in a connector's
   * `credential_schema` is a secret by definition, and a form that guessed from
   * the field name would show somebody's database password in the clear because
   * it was called `token`.
   */
  secret?: boolean;
  disabled?: boolean;
}) {
  if (fields.length === 0) return null;

  const plain = fields.filter((f) => !f.advanced);
  const tucked = fields.filter((f) => f.advanced);

  return (
    <>
      <One fields={plain} render={render} disabled={disabled} />
      {tucked.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-content-muted transition-colors hover:text-content">
            Advanced settings ({tucked.length})
          </summary>
          <div className="mt-4 border-l-2 border-edge pl-4">
            <One fields={tucked} render={render} disabled={disabled} />
          </div>
        </details>
      )}
    </>
  );

  function render(field: FormField) {
        const value = values[field.name] ?? '';

        if (field.kind === 'boolean') {
          return (
            <Toggle
              key={field.name}
              label={field.label}
              hint={field.hint}
              checked={value === 'true'}
              onChange={(on) => onChange(field.name, on ? 'true' : 'false')}
            />
          );
        }

        if (field.choices && field.choices.length > 0) {
          return (
            <Select
              key={field.name}
              label={field.label}
              hint={field.hint}
              value={value}
              onChange={(next) => onChange(field.name, next)}
              // The label the schema gave, falling back to the stored value.
              // Without this a mode renders as `full` and `incremental` rather
              // than as the sentences somebody is actually choosing between.
              options={field.choices.map((choice) => ({
                value: choice,
                label: field.choiceLabels?.[choice] ?? choice,
              }))}
            />
          );
        }

        if (field.kind === 'multiline' || field.kind === 'pairs') {
          return (
            <div key={field.name}>
              <label
                htmlFor={`schema-${field.name}`}
                className="block text-sm text-content-muted"
              >
                {field.label}
              </label>
              <textarea
                id={`schema-${field.name}`}
                value={value}
                rows={field.kind === 'multiline' ? 6 : 3}
                placeholder={field.placeholder}
                onChange={(event) => onChange(field.name, event.target.value)}
                // Monospace because the content is a query or `name=value` lines,
                // and proportional type makes both harder to scan for a typo.
                className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 font-mono text-sm text-content outline-none focus:border-brand"
              />
              {field.hint && (
                <p className="mt-1 text-xs text-content-muted">{field.hint}</p>
              )}
            </div>
          );
        }

        return (
          <Field
            key={field.name}
            label={field.label}
            value={value}
            onChange={(next) => onChange(field.name, next)}
            hint={field.hint}
            placeholder={field.placeholder}
            required={field.required}
            // `numeric` rather than `type="number"` — see the note in Field on why
            // that control is not used anywhere in this app.
            {...(field.kind === 'number'
              ? { numeric: { decimals: 0, min: 0 } as const }
              : {})}
            {...(secret && field.kind === 'text'
              ? { type: 'password' as const, autoComplete: 'new-password' }
              : {})}
          />
    );
  }
}

/** One list of fields. Split out so the disclosure and the main form share it. */
function One({
  fields,
  render,
  disabled,
}: {
  fields: FormField[];
  render: (field: FormField) => React.ReactElement;
  disabled?: boolean;
}) {
  if (fields.length === 0) return null;
  return (
    <fieldset disabled={disabled} className="space-y-4 disabled:opacity-60">
      {fields.map(render)}
    </fieldset>
  );
}
