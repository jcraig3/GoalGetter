import { api } from './api';

/** One spreadsheet this deployment reads. */
export interface Spreadsheet {
  source_id: number;
  name: string;
  tab: string;
  enabled: boolean;
  last_status: string | null;
  spreadsheet_id: string;
}

/** Everything the Google Sheets panel draws itself from. */
export interface SheetsStatus {
  registered: boolean;
  connected: boolean;
  connected_as: string;
  /**
   * Whether the credential is a service account rather than a person.
   *
   * Changes what the screen says next: a service account reads nothing until the
   * spreadsheet has been *shared* with its address, and nobody guesses that.
   */
  service_account: boolean;
  spreadsheets: Spreadsheet[];
}

/** One spreadsheet somebody could choose. */
export interface SheetHit {
  spreadsheet_id: string;
  name: string;
  location: string;
  modified: string;
  web_url: string;
}

/**
 * Reading Google spreadsheets: one account for the deployment, then a picker.
 *
 * The Sheets half of `excel.ts`, deliberately the same shape. Every call is a
 * read — both Google scopes are `readonly` by name. The two non-GETs below store
 * or drop GoalGetter's own credential; neither touches anything in Google.
 */
export const sheets = {
  status: () => api<SheetsStatus>('/api/admin/sheets/status'),

  /** Where to send the browser to choose whose spreadsheets these are. */
  connect: () =>
    api<{ url: string }>('/api/admin/sheets/account', { method: 'POST' }),

  /** Store a service-account key. Returns the address to share sheets with. */
  useServiceAccount: (key: string) =>
    api<{ share_with: string }>('/api/admin/sheets/service-account', {
      method: 'POST',
      body: JSON.stringify({ key }),
    }),

  /** Drops our stored credential. The spreadsheets and their mappings stay. */
  forget: () => api<void>('/api/admin/sheets/account', { method: 'DELETE' }),

  /** Empty term means recently modified; anything else searches by name. */
  files: (q: string) =>
    api<SheetHit[]>(`/api/admin/sheets/files?q=${encodeURIComponent(q)}`),

  /** A pasted address, as a chosen spreadsheet. Reaches what Drive will not list. */
  resolve: (url: string) =>
    api<SheetHit>(`/api/admin/sheets/resolve?url=${encodeURIComponent(url)}`),

  tabs: (spreadsheetId: string) =>
    api<{ name: string }[]>(
      `/api/admin/sheets/tabs?spreadsheet_id=${encodeURIComponent(spreadsheetId)}`,
    ),
};
