/**
 * Matching what somebody typed against what the directory actually holds.
 *
 * Pure, and separate from the component, for the same reason `directorySync.ts` is
 * separate from `DirectoryPanel.tsx`: the interesting part is which options a
 * half-typed string should offer and whether it counts as one of them, and neither
 * is something to establish by clicking.
 */

export interface Option {
  value: string;
  /** How many people carry it. Zero is worth showing — see `Combobox`. */
  people: number;
}

/** How many options to offer at once. */
export const SHOWING = 8;

/**
 * Fold a value the way a match should ignore.
 *
 * Case and surrounding space only. **Not punctuation or inner spacing**, because
 * `Sales` and `Sales Team` are genuinely different departments and folding them
 * together would offer somebody a value that matches nobody — which is the whole
 * problem this dropdown exists to remove.
 */
export function fold(value: string): string {
  return value.trim().toLowerCase();
}

/**
 * The options worth offering for what has been typed so far.
 *
 * **Prefix matches first, then anything containing it.** Somebody typing "sa"
 * means Sales far more often than they mean "Inside Sales", and a list that puts
 * the substring hit first makes the obvious choice the one you have to scroll for.
 * Order within each group is left as given — the endpoint already sorts by how
 * many people carry the value.
 */
export function matching(options: Option[], typed: string): Option[] {
  const needle = fold(typed);
  if (!needle) return options.slice(0, SHOWING);

  const starts: Option[] = [];
  const contains: Option[] = [];
  for (const option of options) {
    const candidate = fold(option.value);
    if (candidate.startsWith(needle)) starts.push(option);
    else if (candidate.includes(needle)) contains.push(option);
  }
  return [...starts, ...contains].slice(0, SHOWING);
}

/**
 * Whether what was typed is one of the directory's own values.
 *
 * Drives the warning, and the warning is the point of all of this: a rule is a
 * string comparison against what the provider sent, so a value nothing carries is
 * a rule that saves cleanly and then matches nobody, with nothing on screen saying
 * so until somebody wonders why no accounts appeared.
 */
export function isKnown(options: Option[], typed: string): boolean {
  const needle = fold(typed);
  return needle === '' || options.some((option) => fold(option.value) === needle);
}

/**
 * How many people a typed value would match, or null when it matches nothing
 * the directory reported.
 *
 * Null and zero mean different things and the form says so differently: null is
 * "no such value here", zero is "this value exists and nobody has it" — which
 * happens to a department after the last person in it leaves.
 */
export function peopleFor(options: Option[], typed: string): number | null {
  const needle = fold(typed);
  const found = options.find((option) => fold(option.value) === needle);
  return found ? found.people : null;
}
