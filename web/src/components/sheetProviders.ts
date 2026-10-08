import { excel } from '../excel';
import { sheets } from '../sheets';
import type { SheetProvider } from './SpreadsheetPicker';

/**
 * What Excel and Google Sheets each give the picker.
 *
 * **Side by side on purpose.** The two differ in three requests and two nouns and
 * in nothing else, and keeping the adapters in one file is what makes that
 * visible — a reader can see the whole difference without opening two components
 * and diffing them in their head.
 *
 * The one genuinely awkward bit is the id. Microsoft addresses a file by *two*
 * values, Google by one; the picker only ever compares ids for equality and hands
 * them back, so Excel packs both into one opaque string and unpacks it at the
 * edge. That keeps the shared component from growing a provider-shaped hole.
 */

const SEPARATOR = '|';

export function packExcelId(driveId: string, itemId: string): string {
  return driveId && itemId ? `${driveId}${SEPARATOR}${itemId}` : '';
}

export function unpackExcelId(id: string): { drive_id: string; item_id: string } {
  const at = id.indexOf(SEPARATOR);
  if (at < 0) return { drive_id: '', item_id: '' };
  return { drive_id: id.slice(0, at), item_id: id.slice(at + 1) };
}

/** Reading a workbook on OneDrive or SharePoint. */
export function excelProvider(sourceId?: number): SheetProvider {
  return {
    browse: async (q) =>
      (await excel.files(q)).map((f) => ({
        id: packExcelId(f.drive_id, f.item_id),
        name: f.name,
        location: f.location,
        modified: f.modified,
      })),
    resolve: async (url) => {
      const f = await excel.resolve(url);
      return {
        id: packExcelId(f.drive_id, f.item_id),
        name: f.name,
        location: f.location,
        modified: f.modified,
      };
    },
    tabs: async (id) => {
      const { drive_id, item_id } = unpackExcelId(id);
      return (await excel.worksheets(drive_id, item_id)).map((w) => w.name);
    },
    taken: async () =>
      (await excel.status()).workbooks
        // The source being edited is not in its own way: without this, opening a
        // finished source to change its header row would show its own tab greyed
        // out as "already connected" — by itself.
        .filter((w) => w.source_id !== sourceId)
        .map((w) => ({ id: packExcelId(w.drive_id, w.item_id), tab: w.worksheet })),

    fileNoun: 'workbook',
    tabNoun: 'worksheet',
    pasteHint: 'In Excel or SharePoint: Share → Copy link. Paste the whole address.',
    placeholder: 'https://contoso.sharepoint.com/…/Deals.xlsx',
    missingHint:
      'A workbook kept in a SharePoint site will not appear here — browsing covers this account’s own files and what was shared to it.',
  };
}

/** Reading a spreadsheet on Google Drive. */
export function sheetsProvider(sourceId?: number): SheetProvider {
  return {
    browse: async (q) =>
      (await sheets.files(q)).map((f) => ({
        id: f.spreadsheet_id,
        name: f.name,
        location: f.location,
        modified: f.modified,
      })),
    resolve: async (url) => {
      const f = await sheets.resolve(url);
      return {
        id: f.spreadsheet_id,
        name: f.name,
        location: f.location,
        modified: f.modified,
      };
    },
    tabs: async (id) => (await sheets.tabs(id)).map((t) => t.name),
    taken: async () =>
      (await sheets.status()).spreadsheets
        .filter((s) => s.source_id !== sourceId)
        .map((s) => ({ id: s.spreadsheet_id, tab: s.tab })),

    fileNoun: 'spreadsheet',
    tabNoun: 'tab',
    pasteHint:
      'Copy the address from your browser while the sheet is open, or use Share → Copy link.',
    placeholder: 'https://docs.google.com/spreadsheets/d/…/edit',
    missingHint:
      'A sheet on a shared drive may not appear here. If you are using a service account, share the sheet with its address first.',
  };
}
