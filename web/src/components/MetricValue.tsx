/**
 * The one place a metric value becomes text.
 *
 * Ad-hoc formatting disagrees with itself: the same number appears as "1234",
 * "1,234", and "$1,234.00" on three screens, and users reasonably conclude one
 * of them is wrong. A metric's `unit` and `decimal_places` decide how it reads,
 * here and nowhere else.
 */

export interface MetricFormat {
  unit: string;
  decimal_places: number;
  /**
   * What a count is a count of, as the plural: "deals". Shown after a count
   * the way "$" goes before money (§8). Optional; see `app/units.py`, which
   * applies the same rule on the server.
   */
  unit_label?: string | null;
}

/** "deals" → "deal", "replies" → "reply", "glasses" → "glass"; "NPS" stays.
 *  The same rule as `app/units.py`. */
export function singular(label: string): string {
  const lower = label.toLowerCase();
  if (label === label.toUpperCase() && label !== lower) return label;
  if (lower.endsWith('ies') && label.length > 3) return `${label.slice(0, -3)}y`;
  if (lower.endsWith('sses')) return label.slice(0, -2);
  if (lower.endsWith('ss') || !lower.endsWith('s')) return label;
  return label.slice(0, -1);
}

/**
 * Values arrive from the API as strings, not numbers.
 *
 * The server stores NUMERIC(18,4) precisely; JavaScript numbers are IEEE
 * doubles and lose precision above 2^53, so parsing a large currency total
 * would throw away the exactness the column was chosen for. Parsing here is
 * safe because it happens at the last step — for display only, never for
 * arithmetic that is written back.
 */
export function formatMetric(
  value: string | number,
  format: MetricFormat,
  currency = 'USD',
  /** Without the count's noun: the first half of "12 of 40 deals". */
  bare = false,
): string {
  const amount = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(amount)) return '—';

  const digits = {
    minimumFractionDigits: format.decimal_places,
    maximumFractionDigits: format.decimal_places,
  };

  switch (format.unit) {
    case 'currency': {
      // **No ".00" on a whole amount** (P3-7, decided 5 Oct): "$500", as the
      // announcements say it, not "$500.00" on the wall beside it. Cents that
      // are there are kept — "$4,215.37". Exports are the server's, exact.
      const rounded = Number(amount.toFixed(format.decimal_places));
      const whole = Number.isInteger(rounded);
      return amount.toLocaleString(undefined, {
        style: 'currency',
        currency,
        ...(whole ? { minimumFractionDigits: 0, maximumFractionDigits: 0 } : digits),
      });
    }

    case 'percent':
      // Values are stored as the percentage itself (73 means 73%), not as a
      // fraction. Using Intl's `style: 'percent'` would multiply by 100 and
      // display 7300%.
      return `${amount.toLocaleString(undefined, digits)}%`;

    case 'duration':
      return formatDuration(amount);

    default: {
      const text = amount.toLocaleString(undefined, digits);
      const label = format.unit === 'count' && !bare ? format.unit_label : null;
      if (!label) return text;
      return `${text} ${amount === 1 ? singular(label) : label}`;
    }
  }
}

/** Seconds → "45s", "12m 30s", "3h 05m". */
function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total}s`;
  if (total < 3600) return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`;
  return `${Math.floor(total / 3600)}h ${String(Math.floor((total % 3600) / 60)).padStart(2, '0')}m`;
}

export default function MetricValue({
  value,
  format,
  currency,
  className,
  bare = false,
}: {
  value: string | number;
  format: MetricFormat;
  currency?: string;
  className?: string;
  /** Leave off a count's noun, where the next number says it. */
  bare?: boolean;
}) {
  // tabular-nums so digits align in a column. Without it, ranked rows visibly
  // jitter because proportional fonts give "1" less width than "8".
  return (
    <span className={`tabular-nums ${className ?? ''}`}>
      {formatMetric(value, format, currency, bare)}
    </span>
  );
}
