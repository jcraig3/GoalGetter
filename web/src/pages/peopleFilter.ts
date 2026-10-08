/**
 * Narrowing the People list: a search box and three dropdowns.
 *
 * **Client-side over the whole list, with no pagination**, which is the same
 * choice the product this was modelled on made and for the same reason: an
 * organization is hundreds of people, not millions, and one fetch means the
 * filters are instant and the counts are honest. A server-side filter would make
 * "12 of 574" a second round trip and "select all shown" a lie.
 *
 * Pure, and separate from the page, because the interesting parts are which
 * fields a search should look at and what an empty filter means — neither of
 * which is worth establishing by clicking.
 */

export interface Filterable {
  full_name: string;
  email: string;
  job_title: string;
  department: string;
  office_location: string;
  team_name: string | null;
  org_role?: string;
}

export interface Filters {
  search: string;
  job_title: string;
  department: string;
  office_location: string;
  /** A team's name, `NO_TEAM` for people on none, or "" for any. */
  team: string;
  role: string;
}

/** The team filter's value for people on no team. */
export const NO_TEAM = '__none__';

export const NO_FILTERS: Filters = {
  search: '',
  job_title: '',
  department: '',
  office_location: '',
  team: '',
  role: '',
};

/**
 * Fold a value the way a match should ignore.
 *
 * Case and surrounding space only. Two departments differing by inner spacing
 * are two departments, and folding them together would offer a filter that
 * silently included people nobody asked for.
 */
export function fold(value: string): string {
  return value.trim().toLowerCase();
}

/**
 * Whether one person matches the search text.
 *
 * **Name and email, not every field.** Somebody typing "sam" means a person;
 * searching titles and departments too would surface everybody in Sales for a
 * search of "sal", which is a list they did not ask for and cannot tell apart
 * from the one they did.
 */
export function matchesSearch(person: Filterable, search: string): boolean {
  const needle = fold(search);
  if (!needle) return true;
  return (
    fold(person.full_name).includes(needle) || fold(person.email).includes(needle)
  );
}

/**
 * The people left after every filter is applied.
 *
 * Empty means any, for each of them independently — so the three dropdowns
 * narrow together rather than one resetting the others.
 */
export function apply<T extends Filterable>(people: T[], filters: Filters): T[] {
  return people.filter((person) => {
    if (!matchesSearch(person, filters.search)) return false;
    if (filters.job_title && fold(person.job_title) !== fold(filters.job_title)) {
      return false;
    }
    if (filters.department && fold(person.department) !== fold(filters.department)) {
      return false;
    }
    if (
      filters.office_location &&
      fold(person.office_location) !== fold(filters.office_location)
    ) {
      return false;
    }
    if (filters.team === NO_TEAM ? person.team_name : filters.team && person.team_name !== filters.team) {
      return false;
    }
    if (filters.role && person.org_role !== filters.role) return false;
    return true;
  });
}

/**
 * The values a dropdown should offer for one field, with how many people have each.
 *
 * **Read off the people actually in the list**, so every option matches somebody
 * — a dropdown listing a department nobody is in is a filter that can only
 * produce an empty screen. Blanks are dropped for the same reason: "" already
 * means *any* at the top of the list, and offering it again as a value would be
 * offering two different meanings for one entry.
 *
 * The count comes along because these feed `Combobox`, which shows it — and
 * "Sales · 24" answers *how much will this narrow it* before the click rather
 * than after.
 */
export function optionsFor(
  people: Filterable[],
  field: keyof Filterable,
): { value: string; people: number }[] {
  const seen = new Map<string, { value: string; people: number }>();
  for (const person of people) {
    const value = String(person[field] ?? '').trim();
    if (!value) continue;
    // Keyed on the folded form so `Sales` and `sales` are one option, and the
    // first spelling seen is the one shown.
    const key = fold(value);
    const found = seen.get(key);
    if (found) found.people += 1;
    else seen.set(key, { value, people: 1 });
  }
  return [...seen.values()].sort((a, b) => a.value.localeCompare(b.value));
}

/** Whether anything is narrowing the list, for the "clear" control. */
export function isNarrowed(filters: Filters): boolean {
  return Boolean(
    filters.search.trim() ||
      filters.job_title ||
      filters.department ||
      filters.office_location ||
      filters.team ||
      filters.role,
  );
}
