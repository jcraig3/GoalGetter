import MetricValue from '../MetricValue';
import type { Slide } from './types';

/**
 * Whether a ranked slide has nothing in it yet: no rows, or — where higher is
 * better — every row at zero, which ranks a whole floor joint first for
 * doing nothing. A zero can be a real best where lower is better.
 */
export function nobodyYet(slide: Pick<Slide, 'entries'> & Partial<Pick<Slide, 'direction'>>): boolean {
  if (slide.entries.length === 0) return true;
  return slide.direction !== 'lower_is_better' && slide.entries.every((e) => !Number(e.value));
}

/**
 * A ranked slide with nothing in it yet (10.1).
 *
 * Every layout says so in the same words — the list used to say nothing at all,
 * which on the first of every month was a blank television. A calendar board
 * also shows last period's top three, so the first morning of October
 * celebrates September rather than showing an empty room.
 */
export default function NobodyYet({
  slide,
}: {
  slide: Pick<Slide, 'unit' | 'decimal_places' | 'unit_label'> & Partial<Pick<Slide, 'previous'>>;
}) {
  const last = slide.previous;
  const format = {
    unit: slide.unit ?? 'count',
    decimal_places: slide.decimal_places,
    unit_label: slide.unit_label,
  };
  return (
    <div data-testid="nobody-yet">
      <p className="text-wall-3xl text-content-muted">Nobody has scored yet.</p>
      {last && last.entries.length > 0 && (
        <div className="mt-10">
          <p className="text-wall-xl font-semibold uppercase tracking-widest text-content">
            {last.label}’s top {last.entries.length === 1 ? 'place' : last.entries.length}
          </p>
          <ol className="mt-4 space-y-3">
            {last.entries.map((entry, i) => (
              <li key={entry.entity_id} className="wall-panel flex items-baseline gap-6 px-8 py-4">
                <span className="w-10 text-wall-3xl tabular-nums text-content-subtle">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate text-wall-3xl text-content">{entry.entity_name}</span>
                <MetricValue
                  value={entry.value}
                  format={format}
                  className="text-wall-3xl font-semibold tabular-nums text-content"
                />
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
