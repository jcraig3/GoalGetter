/**
 * What the directory sync screen says, with no React in sight.
 *
 * Four decisions, each of which is easy to get subtly and invisibly wrong:
 * how a run is summarised, whether the tab nags, how a rule reads back in
 * English, and which clashes are worth mentioning. They live here so they can be
 * tested rather than eyeballed.
 */

import type { DirectoryRule, DirectoryRun, DirectoryStatus } from '../directory';

export interface Named {
  id: number;
  name: string;
}

/**
 * What to say about the last pass.
 *
 * **A failure says the provider's words and nothing about counts.** A run that
 * could not read the directory has counts of zero, and reporting "0 people" beside
 * an error reads as *the directory is empty* — which is the single most alarming
 * wrong conclusion available here.
 */
export function summarise(run: DirectoryRun | null): string {
  if (!run) return 'Never run.';
  // **A sync in progress is a state this had no word for.** The request that
  // starts one runs the whole read server-side, so navigating away does not stop
  // it — and coming back to a screen that said "never run" made a working sync
  // look like a button that had done nothing.
  if (run.status === 'running') return 'A sync is running…';
  if (run.status === 'failed') return run.error || 'The last sync failed.';

  const parts = [`${run.people_seen} ${run.people_seen === 1 ? 'person' : 'people'}`];
  if (run.created) parts.push(`${run.created} new`);
  if (run.applied) parts.push(`${run.applied} added`);
  if (run.archived) parts.push(`${run.archived} left`);
  if (run.needs_review) parts.push(`${run.needs_review} changed`);
  return parts.join(' · ');
}

/**
 * Whether the last pass is worth flagging as not-quite-right.
 *
 * `partial` means people were read *and* something was held back — usually one
 * person with no email address. Not a failure, and not silence either: a run that
 * quietly does nine-tenths of its job is how somebody spends a week wondering where
 * one person went.
 */
/**
 * How often the sync runs, in words.
 *
 * Said on the Users tab because the switch is not there any more — it lives with
 * the connection it belongs to — so this screen has to state the schedule it is
 * subject to rather than letting somebody assume one.
 *
 * Named intervals for the ones the panel offers and a plain count for anything
 * else, since the column accepts any number of hours and a value set by hand
 * should still read as something.
 */
export function everyHours(hours: number): string {
  if (hours === 1) return 'every hour';
  if (hours === 24) return 'daily';
  if (hours === 168) return 'weekly';
  if (hours % 24 === 0) return `every ${hours / 24} days`;
  return `every ${hours} hours`;
}

export function needsAttention(run: DirectoryRun | null): boolean {
  return run !== null && (run.status === 'failed' || run.status === 'partial');
}

/**
 * The number on the tab, or nothing.
 *
 * Zero is not a badge. A badge showing `0` is a permanent visual alarm that means
 * "everything is fine", which trains somebody to stop seeing badges at all.
 */
export function badge(status: DirectoryStatus | null): number | null {
  if (!status || status.pending <= 0) return null;
  return status.pending;
}

/**
 * What the screen is actually asking of somebody right now.
 *
 * Three states with three different next actions, and conflating any two of them
 * produces a screen that either nags about something impossible or stays silent
 * about something urgent.
 */
export type Stage = 'unavailable' | 'unconnected' | 'off' | 'on';

export function stage(status: DirectoryStatus | null): Stage {
  if (!status || status.available.length === 0) return 'unavailable';
  if (!status.connected) return 'unconnected';
  return status.enabled ? 'on' : 'off';
}

const ROLE_NAMES: Record<string, string> = {
  admin: 'an admin',
  manager: 'a manager',
  agent: 'an agent',
};

/**
 * A rule, read back as a sentence.
 *
 * **Because a row of four mostly-empty boxes does not say what it does.** The
 * conditions are an *and*, and "Any" repeated across three columns is exactly the
 * shape that gets misread as an *or* — so the sentence names only what is set.
 */
export function describe(rule: DirectoryRule, teams: Named[]): string {
  const conditions = [
    rule.department && `in ${rule.department}`,
    rule.job_title && `whose title is ${rule.job_title}`,
    rule.office && `at ${rule.office}`,
    rule.group && `in the ${rule.group} group`,
  ].filter(Boolean);

  // No conditions is the catch-all, and it deserves saying plainly rather than as
  // an empty subject: it is the rule most likely to surprise somebody later.
  const who = conditions.length ? `Anyone ${conditions.join(', ')}` : 'Everyone else';

  const team = teams.find((t) => t.id === rule.team_id);
  const becomes = ROLE_NAMES[rule.role] ?? `a ${rule.role}`;

  return team
    ? `${who} becomes ${becomes} on ${team.name}.`
    : `${who} becomes ${becomes}, with no team.`;
}

/**
 * Which rules are shadowed by an earlier one, phrased for the person who wrote them.
 *
 * Returned per *position* rather than as pairs, because the warning belongs on the
 * row that does nothing — that is the row somebody has to change, and a message at
 * the top of the table saying "rules 2 and 5" makes them count.
 */
export function shadowed(clashes: number[][]): Map<number, number> {
  const found = new Map<number, number>();
  for (const pair of clashes) {
    const first = pair[0];
    const later = pair[1];
    if (first === undefined || later === undefined) continue;
    // The first one wins, so only the later is shadowed. Recording both would
    // put a warning on a rule that works perfectly.
    if (!found.has(later)) found.set(later, first);
  }
  return found;
}

/**
 * What the rules would do with somebody, in a phrase.
 *
 * Shown next to them *before* anybody presses approve, because "where will these
 * two hundred people land" is the question an admin actually has — and finding out
 * afterwards means undoing it by hand.
 */
export function placement(
  person: { would_be_role: string; would_be_team_id: number | null },
  teams: Named[],
): string {
  const team = teams.find((t) => t.id === person.would_be_team_id);
  const role = ROLE_NAMES[person.would_be_role] ?? `a ${person.would_be_role}`;
  return team ? `${role} on ${team.name}` : `${role}, unassigned`;
}
