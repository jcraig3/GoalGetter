/** Words for goals, shared by the list and the detail page. */

/** "Repeats monthly" — the tag said in full, everywhere (8.2). */
export function repeatTag(goal: { recurring: boolean; period_type: string }): {
  label: string;
  title: string;
} {
  const every: Record<string, string> = {
    day: 'daily',
    week: 'weekly',
    month: 'monthly',
    quarter: 'quarterly',
    year: 'yearly',
  };
  return goal.recurring
    ? {
        label: `Repeats ${every[goal.period_type] ?? 'every period'}`,
        title: 'A new copy of this goal is made at the start of each period.',
      }
    : {
        label: 'Made automatically',
        title: 'A copy of a repeating goal, made for this period. Edit the goal it came from to change the next ones.',
      };
}
