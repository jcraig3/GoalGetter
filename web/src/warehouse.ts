import { api } from './api';

/** The Snowflake connection, as the panel needs it. */
export interface WarehouseStatus {
  /** Whether this build ships the driver at all. */
  available: boolean;
  connected: boolean;

  account: string;
  username: string;
  warehouse: string;
  role: string;
  database: string;

  /** Whether a credential is stored, never what it is. */
  private_key_set: boolean;
  token_set: boolean;
  password_set: boolean;

  /** How many queries hang off this connection. */
  queries: number;
}

export interface WarehouseWrite {
  account: string;
  username: string;
  warehouse?: string;
  role?: string;
  database?: string;
  /** Omit to leave alone, empty string to clear. */
  private_key?: string;
  key_passphrase?: string;
  /** A Snowflake programmatic access token. Storing one clears the key. */
  token?: string;
  password?: string;
}

/**
 * The warehouse connection: set up once, then add queries.
 *
 * **The key is text either way.** A `.p8` is a PEM file, so an uploaded one is
 * read in the browser and posted exactly as a pasted one would be — one endpoint,
 * and the two input paths cannot drift apart.
 */
export const warehouse = {
  read: () => api<WarehouseStatus>('/api/admin/warehouse/snowflake'),

  save: (body: WarehouseWrite) =>
    api<WarehouseStatus>('/api/admin/warehouse/snowflake', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  forget: () =>
    api<void>('/api/admin/warehouse/snowflake', { method: 'DELETE' }),

  /** Can we reach it at all, before anybody writes a query? */
  test: () =>
    api<{ ok: boolean; detail: string }>('/api/admin/warehouse/snowflake/test', {
      method: 'POST',
    }),
};
