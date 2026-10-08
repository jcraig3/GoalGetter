/**
 * Who matches what somebody typed into a people picker, with no React in it.
 *
 * Pulled out so the ranking can be tested: with 450 people, which eight are
 * offered first is the whole of whether the picker works.
 */
export interface PickPerson {
  id: number;
  full_name: string;
  email: string;
  team_id?: number | null;
  team_name?: string | null;
  photo_digest?: string | null;
}

/** How many to offer at once. More is a list to scroll, which is the problem. */
export const OFFERED = 8;

function fold(value: string): string {
  return value.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
}

/**
 * How well one person matches, or null if they do not. Higher is better.
 *
 * Every typed word has to match somewhere — name, email or team — so "peter
 * metropolis" finds the Peter on the Metropolis team. A match at the start of the name
 * beats one at the start of any word, which beats one anywhere.
 */
function score(person: PickPerson, words: string[]): number | null {
  const name = fold(person.full_name);
  const haystack = `${name} ${fold(person.email)} ${fold(person.team_name ?? '')}`;
  let total = 0;
  for (const word of words) {
    if (!haystack.includes(word)) return null;
    if (name.startsWith(word)) total += 3;
    else if (name.split(/\s+/).some((part) => part.startsWith(word))) total += 2;
    else total += 1;
  }
  return total;
}

/** Everybody matching `query`, best first, alphabetical among equals. */
export function matchPeople(
  people: PickPerson[],
  query: string,
  exclude: ReadonlySet<number> = new Set(),
): PickPerson[] {
  const words = fold(query).split(/\s+/).filter(Boolean);
  const candidates = people.filter((p) => !exclude.has(p.id));
  if (words.length === 0) {
    return [...candidates].sort((a, b) => a.full_name.localeCompare(b.full_name));
  }
  return candidates
    .map((person) => ({ person, s: score(person, words) }))
    .filter((m): m is { person: PickPerson; s: number } => m.s !== null)
    .sort((a, b) => b.s - a.s || a.person.full_name.localeCompare(b.person.full_name))
    .map((m) => m.person);
}

export interface TeamMatch {
  name: string;
  /** Members not already chosen. */
  ids: number[];
}

/** Teams whose name contains what was typed, with the members still to add. */
export function matchTeams(
  people: PickPerson[],
  query: string,
  exclude: ReadonlySet<number> = new Set(),
): TeamMatch[] {
  const q = fold(query);
  if (!q) return [];
  const teams = new Map<string, number[]>();
  for (const person of people) {
    if (!person.team_name || exclude.has(person.id)) continue;
    if (!fold(person.team_name).includes(q)) continue;
    const ids = teams.get(person.team_name) ?? [];
    ids.push(person.id);
    teams.set(person.team_name, ids);
  }
  return [...teams]
    .map(([name, ids]) => ({ name, ids }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** The line under a name, which is what tells two Peter Parkers apart. */
export function secondLine(person: PickPerson): string {
  return [person.team_name ?? 'No team', person.email].filter(Boolean).join(' · ');
}
