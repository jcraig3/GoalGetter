import { api } from './api';

/** One spreadsheet this deployment reads. */
export interface Workbook {
  source_id: number;
  name: string;
  worksheet: string;
  enabled: boolean;
  last_status: string | null;
  /** Which file and tab, so a picker can grey out what is already connected. */
  drive_id: string;
  item_id: string;
}

/** Everything the Excel panel draws itself from. */
export interface ExcelStatus {
  /** Whether Microsoft 365 is registered at all. */
  registered: boolean;
  connected: boolean;
  /** Whose files these are. Empty when nobody is signed in. */
  connected_as: string;
  workbooks: Workbook[];
}

/** One workbook somebody could choose. */
export interface FileHit {
  drive_id: string;
  item_id: string;
  name: string;
  location: string;
  modified: string;
  web_url: string;
}

/**
 * Reading spreadsheets: one account for the deployment, then a file picker.
 *
 * **Every call here is a read.** The account's token carries `Files.Read.All` and
 * nothing else — a scope that cannot create, modify or delete a file. The one
 * non-GET below removes GoalGetter's own stored token; it touches nothing in
 * Microsoft.
 */
export const excel = {
  status: () => api<ExcelStatus>('/api/admin/excel/status'),

  /** Where to send the browser to choose whose files these are. */
  connect: () =>
    api<{ url: string }>('/api/admin/excel/account', { method: 'POST' }),

  /** Drops our stored token. The workbooks and their column mappings stay. */
  forget: () =>
    api<void>('/api/admin/excel/account', { method: 'DELETE' }),

  /** Empty term means recent; anything else searches everything they can reach. */
  files: (q: string) =>
    api<FileHit[]>(`/api/admin/excel/files?q=${encodeURIComponent(q)}`),

  /** A pasted sharing link, as a chosen workbook. Reaches SharePoint sites. */
  resolve: (url: string) =>
    api<FileHit>(`/api/admin/excel/resolve?url=${encodeURIComponent(url)}`),

  worksheets: (driveId: string, itemId: string) =>
    api<{ name: string }[]>(
      `/api/admin/excel/worksheets?drive_id=${encodeURIComponent(driveId)}` +
        `&item_id=${encodeURIComponent(itemId)}`,
    ),
};
