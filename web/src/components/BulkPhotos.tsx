import { useEffect, useRef, useState, type DragEvent } from 'react';

import { api } from '../api';
import PeoplePicker from './PeoplePicker';
import type { PickPerson } from './peoplePick';
import {
  filesFromDrop,
  isJunk,
  kindOf,
  markReplaced,
  type PhotoRow,
} from './staffPhotos';
import { toast } from '../toast';

interface Outcome {
  filename: string;
  status: PhotoRow['status'];
  detail: string;
  user_id: number | null;
  user_name: string | null;
}

const TONES: Record<string, string> = {
  waiting: 'text-content-subtle',
  matched: 'text-success',
  unmatched: 'text-warning',
  ambiguous: 'text-warning',
  rejected: 'text-danger',
};

const WORDS: Record<string, string> = {
  waiting: 'Waiting',
  matched: 'Set',
  unmatched: 'Not matched',
  ambiguous: 'More than one fits',
  rejected: 'Not used',
};

let nextKey = 0;

/**
 * Staff photos, in bulk or one at a time (moved here from Settings).
 *
 * **One drop zone for everything.** Drag in — or click and choose — a `.zip`,
 * a folder, or any number of single photos. Each is matched to its person by
 * its name: their username (`pparker.jpg`), or their whole email address.
 * Separators and capitals do not matter, and two people who could both be the
 * name are never guessed between.
 *
 * **Single photos go one at a time**, so the page counts them off as they go
 * and no one request has to carry four hundred. A zip goes as itself.
 *
 * **Every file gets a line back**, problems first. One nobody matched can be
 * given to the right person there and then, without renaming it and starting
 * again; two photos for one person say which one won.
 */
export default function BulkPhotos() {
  const input = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<PhotoRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function update(key: string, change: Partial<PhotoRow>) {
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...change } : r)));
  }

  async function take(files: File[]) {
    const usable = files.filter((f) => !isJunk(f.name));
    if (usable.length === 0) return;
    setError(null);
    setBusy(true);

    const zips = usable.filter((f) => kindOf(f) === 'zip');
    const singles = usable.filter((f) => kindOf(f) === 'image');
    const others = usable.filter((f) => kindOf(f) === 'other');

    const queued: PhotoRow[] = [
      ...singles.map((file) => ({
        key: String(nextKey++),
        filename: file.webkitRelativePath || file.name,
        status: 'waiting' as const,
        detail: '',
        file,
      })),
      ...others.map((file) => ({
        key: String(nextKey++),
        filename: file.name,
        status: 'rejected' as const,
        detail: 'Not a picture (.jpg, .png, .webp) or a .zip.',
      })),
    ];
    setRows(queued);
    setProgress({ done: 0, total: singles.length + zips.length });

    let done = 0;
    let set = 0;
    for (const zip of zips) {
      try {
        const report = await api<{ outcomes: Outcome[] }>('/api/users/photos/bulk', {
          method: 'POST',
          body: zip,
        });
        set += report.outcomes.filter((o) => o.status === 'matched').length;
        setRows((current) => [
          ...current,
          ...report.outcomes.map((o) => ({ ...o, key: String(nextKey++), filename: `${zip.name} › ${o.filename}` })),
        ]);
      } catch (e) {
        setRows((current) => [
          ...current,
          {
            key: String(nextKey++),
            filename: zip.name,
            status: 'rejected',
            detail: e instanceof Error ? e.message : 'That archive could not be read.',
          },
        ]);
      }
      setProgress({ done: ++done, total: singles.length + zips.length });
    }

    // One at a time, in order, so "the later one wins" means the one listed later.
    for (const row of queued.filter((r) => r.file)) {
      try {
        const found = await api<Outcome>('/api/users/photos/one', {
          method: 'POST',
          body: row.file,
          headers: { 'X-File-Name': encodeURIComponent(row.file!.name) },
        });
        if (found.status === 'matched') set += 1;
        update(row.key, {
          status: found.status,
          detail: found.detail,
          user_id: found.user_id,
          user_name: found.user_name,
        });
      } catch (e) {
        update(row.key, {
          status: 'rejected',
          detail: e instanceof Error ? e.message : 'That photo could not be sent.',
        });
      }
      setProgress({ done: ++done, total: singles.length + zips.length });
    }

    setRows((current) => markReplaced(current));
    setBusy(false);
    setProgress(null);
    if (set) toast(set === 1 ? '1 photo set' : `${set} photos set`);
  }

  async function giveTo(row: PhotoRow, userId: number, name: string) {
    if (!row.file) return;
    try {
      await api(`/api/users/${userId}/photo`, { method: 'POST', body: row.file });
      update(row.key, { status: 'matched', detail: 'Set by hand.', user_id: userId, user_name: name });
      setRows((current) => markReplaced(current));
      toast(`Photo set for ${name}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set that photo.');
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    void filesFromDrop(event.dataTransfer).then(take);
  }

  // Problems first: they are the reason somebody reads this list.
  const ordered = [...rows].sort((a, b) => rank(a) - rank(b));
  const matched = rows.filter((r) => r.status === 'matched').length;
  const unresolved = rows.filter((r) => r.status !== 'matched' && r.status !== 'waiting').length;

  return (
    <section className="max-w-3xl rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">Staff photos</h2>
      <p className="mt-1 text-sm text-content-muted">
        <strong className="text-content">A separate upload from Add files.</strong>{' '}
        These become people&rsquo;s profile pictures and the faces on boards —
        they do not go into the library below. One person&rsquo;s photo can also
        be changed on their own page.
      </p>

      <div
        role="button"
        tabIndex={0}
        aria-label="Upload staff photos: drop them here, or press to choose"
        aria-disabled={busy}
        onClick={() => !busy && input.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !busy) {
            e.preventDefault();
            input.current?.click();
          }
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'copy';
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
        }}
        onDrop={onDrop}
        className={`mt-4 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors outline-none focus-visible:border-brand ${
          dragging
            ? 'border-brand bg-brand-subtle'
            : 'border-edge hover:border-content-subtle hover:bg-surface-hover'
        } ${busy ? 'pointer-events-none opacity-60' : ''}`}
      >
        <svg viewBox="0 0 24 24" className="size-10 text-content-subtle" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 16.5V18a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1.5M12 15V4M7.5 8.5 12 4l4.5 4.5" />
        </svg>
        <p className="mt-3 text-content">
          {dragging ? 'Drop to upload' : 'Drag photos, a folder or a .zip here'}
        </p>
        <p className="mt-1 text-sm text-content-muted">
          or <span className="text-brand underline">click to choose files</span>
        </p>
        <p className="mt-3 max-w-md text-xs text-content-subtle">
          Name each photo after the person&rsquo;s username — <code>pparker.jpg</code> —
          or their email address. JPG, PNG or WebP up to 10 MB each; a zip up to
          100 MB, with subfolders if you like.
        </p>
      </div>
      <input
        ref={input}
        type="file"
        multiple
        accept=".zip,application/zip,image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
        className="sr-only"
        aria-label="Choose staff photos or a zip"
        tabIndex={-1}
        onChange={(e) => {
          const chosen = [...(e.target.files ?? [])];
          e.target.value = '';
          void take(chosen);
        }}
      />

      {progress && (
        <div className="mt-4" role="status">
          <div className="flex justify-between text-xs text-content-muted">
            <span>Uploading…</span>
            <span className="tabular-nums">
              {progress.done} of {progress.total}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-hover">
            <div
              className="h-full bg-brand transition-[width]"
              style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {rows.length > 0 && !busy && (
        <p className="mt-5 text-sm text-content">
          <strong>{matched}</strong> {matched === 1 ? 'photo set' : 'photos set'}
          {unresolved > 0 && (
            <>
              , <strong className="text-warning">{unresolved}</strong> to sort out
            </>
          )}
          .
        </p>
      )}

      {ordered.length > 0 && (
        <ul className="mt-3 max-h-96 divide-y divide-edge overflow-y-auto rounded-md border border-edge">
          {ordered.map((row) => (
            <ResultRow key={row.key} row={row} onGive={(id, name) => void giveTo(row, id, name)} />
          ))}
        </ul>
      )}
    </section>
  );
}

function rank(row: PhotoRow): number {
  if (row.status === 'unmatched' || row.status === 'ambiguous') return 0;
  if (row.status === 'rejected') return 1;
  if (row.status === 'waiting') return 2;
  return 3;
}

/** One file's line, with a way to give an unmatched single photo to somebody. */
function ResultRow({
  row,
  onGive,
}: {
  row: PhotoRow;
  onGive: (userId: number, name: string) => void;
}) {
  const fixable = Boolean(row.file) && (row.status === 'unmatched' || row.status === 'ambiguous');
  const [people, setPeople] = useState<PickPerson[] | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [chosen, setChosen] = useState<number | null>(null);

  useEffect(() => {
    if (!choosing || people) return;
    api<PickPerson[]>('/api/users')
      .then(setPeople)
      .catch(() => setPeople([]));
  }, [choosing, people]);

  return (
    <li className="px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <code className="min-w-40 flex-1 truncate text-xs text-content">{row.filename}</code>
        <span className={`shrink-0 text-xs ${TONES[row.status] ?? 'text-content-muted'}`}>
          {WORDS[row.status]}
          {row.status === 'matched' && row.user_name ? ` — ${row.user_name}` : ''}
        </span>
        {fixable && !choosing && (
          <button
            type="button"
            onClick={() => setChoosing(true)}
            className="shrink-0 text-xs text-brand underline"
          >
            Choose person
          </button>
        )}
      </div>
      {row.detail && row.status !== 'waiting' && (
        <p className="mt-0.5 text-xs text-content-subtle">{row.detail}</p>
      )}
      {fixable && choosing && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <div className="min-w-60 flex-1">
            {people === null ? (
              <p className="text-xs text-content-subtle">Loading people…</p>
            ) : (
              <PeoplePicker
                label={`Whose photo is ${row.filename}?`}
                people={people}
                value={chosen}
                onChange={setChosen}
              />
            )}
          </div>
          <button
            type="button"
            disabled={chosen === null}
            onClick={() => {
              const person = people?.find((p) => p.id === chosen);
              if (person) onGive(person.id, person.full_name);
            }}
            className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            Set photo
          </button>
          <button
            type="button"
            onClick={() => setChoosing(false)}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted hover:bg-surface-hover"
          >
            Cancel
          </button>
        </div>
      )}
    </li>
  );
}
