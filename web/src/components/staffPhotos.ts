/**
 * The parts of the staff photo upload that are not drawing: what each dropped
 * file is, reading a dropped folder, and spotting two photos for one person.
 */

export type FileKind = 'zip' | 'image' | 'other';

const IMAGE_SUFFIX = /\.(jpe?g|png|webp)$/i;

/** A zip, a picture, or neither — by type, then by name, as browsers differ. */
export function kindOf(file: { name: string; type: string }): FileKind {
  if (/zip/i.test(file.type) || /\.zip$/i.test(file.name)) return 'zip';
  if (/^image\/(jpe?g|pjpeg|png|webp)$/i.test(file.type) || IMAGE_SUFFIX.test(file.name)) {
    return 'image';
  }
  return 'other';
}

/** What a Mac or Windows leaves in a folder, which nobody means to upload. */
export function isJunk(name: string): boolean {
  const base = name.split('/').pop() ?? name;
  return base.startsWith('.') || name.includes('__MACOSX') || /^thumbs\.db$/i.test(base);
}

// The parts of the File System API a drop uses — typed here because the
// DOM library names them inconsistently across versions.
interface Entry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (ok: (f: File) => void, fail: (e: unknown) => void) => void;
  createReader?: () => { readEntries: (ok: (e: Entry[]) => void, fail: (e: unknown) => void) => void };
}

async function walk(entry: Entry, out: File[]): Promise<void> {
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((ok, fail) => entry.file!(ok, fail));
    if (!isJunk(file.name)) out.push(file);
    return;
  }
  if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    // A reader hands entries back in batches until it returns none.
    for (;;) {
      const batch = await new Promise<Entry[]>((ok, fail) => reader.readEntries(ok, fail));
      if (batch.length === 0) break;
      for (const child of batch) await walk(child, out);
    }
  }
}

/**
 * Every file in a drop, folders opened all the way down.
 *
 * **A dropped folder is read, not refused.** `dataTransfer.files` lists a
 * folder as one useless entry, so this asks each item for its file-system
 * entry and walks it. Browsers without that fall back to the plain list.
 */
export async function filesFromDrop(data: DataTransfer): Promise<File[]> {
  const items = [...(data.items ?? [])];
  const entries = items
    .map((item) => (item as unknown as { webkitGetAsEntry?: () => Entry | null }).webkitGetAsEntry?.())
    .filter((e): e is Entry => Boolean(e));
  if (entries.length === 0) return [...(data.files ?? [])].filter((f) => !isJunk(f.name));
  const out: File[] = [];
  for (const entry of entries) await walk(entry, out);
  return out;
}

/** One file's result, as the page shows it. */
export interface PhotoRow {
  key: string;
  filename: string;
  status: 'waiting' | 'matched' | 'unmatched' | 'ambiguous' | 'rejected';
  detail: string;
  user_id?: number | null;
  user_name?: string | null;
  /** Kept for a single photo, so one nobody matched can be given to somebody by hand. */
  file?: File;
}

/**
 * Two photos for one person: the later one is what they now have, and the
 * earlier is said so, rather than looking set when it was replaced.
 */
export function markReplaced(rows: PhotoRow[]): PhotoRow[] {
  const last = new Map<number, string>();
  for (const row of rows) {
    if (row.status === 'matched' && row.user_id != null) last.set(row.user_id, row.key);
  }
  return rows.map((row) => {
    if (row.status !== 'matched' || row.user_id == null) return row;
    const winner = last.get(row.user_id);
    if (winner === row.key) return row;
    const by = rows.find((r) => r.key === winner)?.filename ?? 'a later file';
    return { ...row, detail: `Replaced by ${by}, which came later.` };
  });
}
