import type { Source } from '../dataSources';

/** One connector's sources, listed together. */
export interface SourceGroup {
  connector: string;
  connector_name: string;
  sources: Source[];
}

/**
 * Sources gathered by connector, so one integration reads as one thing.
 *
 * **The list used to be flat, and that was the whole problem.** Connect four
 * spreadsheets and you got four loose cards all called Microsoft Excel, each
 * looking like a separate integration — when in truth there is one Microsoft
 * connection, one signed-in account, and four sheets inside it. The model was
 * already right; the page disagreed with it.
 *
 * **They stay separate rows, and that is not a compromise.** A sheet is a real
 * source: `metric_fact.data_source_id` says which sheet a number came from,
 * `_withdraw_missing` is scoped per source so one sheet cannot delete another's
 * facts, `deal_id` can repeat across two workbooks without colliding, and
 * `failure_count` backs off one bad tab without touching the rest. Collapsing
 * them into one row would hide "Q3 Pipeline has been failing for three days"
 * behind a click — which is exactly what somebody opens this page to find.
 *
 * Order is first-appearance, so the list does not reshuffle when a source is
 * added: whichever connector you connected first stays at the top.
 */
export function groupSources(sources: Source[]): SourceGroup[] {
  const groups: SourceGroup[] = [];
  const at = new Map<string, SourceGroup>();

  for (const source of sources) {
    let group = at.get(source.connector);
    if (!group) {
      group = {
        connector: source.connector,
        // The server's own name for it, falling back to the key so a connector
        // this build no longer ships still renders as something.
        connector_name: source.connector_name || source.connector,
        sources: [],
      };
      at.set(source.connector, group);
      groups.push(group);
    }
    group.sources.push(source);
  }

  return groups;
}

/**
 * The worksheet a spreadsheet source reads, for the line under its name.
 *
 * **What distinguishes siblings.** Four sources from one workbook differ only by
 * tab, so a list showing four names and no tabs is a list of four identical rows.
 * Empty for anything that is not a spreadsheet, and empty for a sheet configured
 * before the picker existed — in both cases the caller shows nothing rather than
 * an empty pair of quotes.
 */
export function worksheetOf(source: Source): string {
  const raw = source.config?.worksheet;
  return typeof raw === 'string' ? raw.trim() : '';
}

/**
 * Whether adding another of these is a thing somebody can do from the list.
 *
 * True for a connector where "one more" is the normal case — another spreadsheet,
 * another warehouse query. A webhook is the counter-example: its second endpoint
 * is a different shape of decision, made where endpoints are made.
 *
 * Named as a question about the *connector*, not a hardcoded key list at the call
 * site, so the rule is stated once and reads as a rule.
 */
export function acceptsMore(connector: string): boolean {
  return connector === 'microsoft_excel' || connector === 'google_sheets';
}

/** What the button offers to add, in that connector's own noun. */
export function addLabel(connector: string): string {
  if (connector === 'microsoft_excel' || connector === 'google_sheets') {
    return 'Add a spreadsheet';
  }
  return 'Add another';
}
