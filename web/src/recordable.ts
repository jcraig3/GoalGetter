/**
 * Metrics somebody can record data against — every metric except a derived
 * one, which is worked out from two others and has no data of its own.
 *
 * For pickers that write facts: manual entry, corrections, source mappings and
 * achievement rules. The API refuses a derived metric in each of those anyway;
 * this keeps it out of the list so nobody picks it and meets the refusal.
 */
export function recordable<T>(metrics: T[]): T[] {
  return metrics.filter((m) => (m as { aggregation?: string }).aggregation !== 'ratio');
}
