import Field from './Field';

export interface StretchDraft {
  value: string;
  label: string;
}

const MAX_LEVELS = 3;
const DEFAULT_LABELS = ['Stretch', 'Stretch 2', 'Stretch 3'];

/**
 * Up to three levels past a goal's target, each harder than the last.
 *
 * **The target is still the target.** Progress, pace and "hit" are measured
 * against it; a level is a further line past it, celebrated once per period
 * when it is crossed. So this sits under the Target field and says so, rather
 * than looking like a second target.
 */
export default function StretchFields({
  levels,
  onChange,
  lowerIsBetter,
}: {
  levels: StretchDraft[];
  onChange: (levels: StretchDraft[]) => void;
  lowerIsBetter: boolean;
}) {
  function set(index: number, patch: Partial<StretchDraft>) {
    onChange(levels.map((level, i) => (i === index ? { ...level, ...patch } : level)));
  }

  return (
    <fieldset className="rounded-md border border-edge p-3">
      <legend className="px-1 text-sm text-content-muted">Stretch levels</legend>
      <p className="text-xs text-content-subtle">
        Optional. Levels past the target, each celebrated once when it is reached — each one{' '}
        {lowerIsBetter ? 'lower' : 'higher'} than the last.
      </p>
      {levels.length > 0 && (
        <div className="mt-3 space-y-2">
          {levels.map((level, index) => (
            <div key={index} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
              <Field
                label={`Level ${index + 1}`}
                value={level.value}
                onChange={(value) => set(index, { value })}
                numeric={{ decimals: 4, min: 0 }}
              />
              <Field
                label="Called"
                value={level.label}
                onChange={(label) => set(index, { label })}
                maxLength={40}
                required={false}
                placeholder={DEFAULT_LABELS[index]}
              />
              <button
                type="button"
                onClick={() => onChange(levels.filter((_, i) => i !== index))}
                aria-label={`Remove level ${index + 1}`}
                className="mb-1 rounded-md px-2 py-2 text-sm text-content-muted hover:text-danger"
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
      {levels.length < MAX_LEVELS && (
        <button
          type="button"
          onClick={() => onChange([...levels, { value: '', label: '' }])}
          className="mt-3 text-sm text-brand hover:underline"
        >
          Add a stretch level
        </button>
      )}
    </fieldset>
  );
}

/** What the API takes: levels with a number, labels only when typed. */
export function stretchPayload(levels: StretchDraft[]) {
  return levels
    .filter((level) => level.value.trim() !== '')
    .map((level) => ({ value: level.value.trim(), label: level.label.trim() || null }));
}
