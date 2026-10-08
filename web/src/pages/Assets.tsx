import { dayMonth } from '../time';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import EmptyState from '../components/EmptyState';
import Loading from '../components/Loading';
import PageHeader from '../components/PageHeader';
import { Tab } from '../components/Tabs';
import { ask } from '../confirm';
import { toast } from '../toast';
import BulkPhotos from '../components/BulkPhotos';
import BuiltIn, { BUILT_IN_MARKS } from '../components/BuiltInAssets';

export interface Asset {
  digest: string;
  kind: 'image' | 'video' | 'audio';
  content_type: string;
  byte_size: number;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  name: string | null;
  created_at: string;
  used_in: { label: string; link: string }[];
  /** A person's photograph (Phase 27): whose, and where it came from. */
  photo_of?: string | null;
  photo_source?: 'uploaded' | 'synced' | null;
}

type Shelf = 'all' | Asset['kind'] | 'photos' | 'builtin' | 'unused';

const SHELVES: { key: Shelf; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'image', label: 'Images' },
  { key: 'video', label: 'Video' },
  { key: 'audio', label: 'Sound' },
  { key: 'photos', label: 'Profile pics' },
  // What ships with GoalGetter: starter sounds, backgrounds, badge art.
  { key: 'builtin', label: 'Built-in' },
  // Nothing uses it (8.4): four of seven were, on the dev data, left to be
  // found one card at a time.
  { key: 'unused', label: 'Unused' },
];

/** Whether a file is on this shelf. */
export function onShelf(asset: Asset, shelf: Shelf): boolean {
  // People's photos are their own shelf; they are looked after on their pages.
  if (shelf === 'photos') return Boolean(asset.photo_of);
  if (asset.photo_of || shelf === 'builtin') return false;
  if (shelf === 'all') return true;
  if (shelf === 'unused') return asset.used_in.length === 0;
  return asset.kind === shelf;
}

const KIND_WORD: Record<Asset['kind'], string> = { image: 'Image', video: 'Video', audio: 'Sound' };

/** What the file input offers. The server decides what a file really is. */
const ACCEPT = 'image/png,image/jpeg,image/webp,video/mp4,audio/*';

/**
 * Organization → Assets (6.3): every picture, video and sound this
 * organization holds, in one place.
 *
 * They were each uploaded from where they were for — a logo on Appearance, a
 * background on a board, a walk-up song on somebody's page — and could only be
 * seen there. Here they can be browsed, previewed, named, added to, and
 * removed once nothing uses them. Each says where it is used, and one that is
 * in use cannot be removed: a channel's background vanishing would leave a
 * television drawing an empty rectangle in front of the floor.
 *
 * People's photographs have their own shelf, labelled with whose they are;
 * they are changed on their own pages.
 */
export default function Assets() {
  const [assets, setAssets] = useState<Asset[] | null>(null);
  const [shelf, setShelf] = useState<Shelf>('all');
  const [builtInCount, setBuiltInCount] = useState<number | null>(null);
  const [uploading, setUploading] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setAssets(await api<Asset[]>('/api/assets?photos=true'));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the assets.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function add(files: FileList | null) {
    if (!files || files.length === 0) return;
    setError(null);
    const list = [...files];
    setUploading(list.length);
    const failed: string[] = [];
    // One at a time: a ten-file drop should not be ten 20 MB bodies at once.
    for (const file of list) {
      try {
        await api('/api/assets', {
          method: 'POST',
          body: file,
          headers: { 'X-File-Name': encodeURIComponent(file.name) },
        });
      } catch (e) {
        failed.push(`${file.name}: ${e instanceof Error ? e.message : 'not added'}`);
      }
      setUploading((n) => n - 1);
    }
    if (input.current) input.current.value = '';
    const added = list.length - failed.length;
    // Both halves, when it went both ways (Q2-20): "Added to the library"
    // beside a refusal read as everything having worked.
    if (added && failed.length) toast(`Added ${added} · ${failed.length} refused — see why above`);
    else if (added) toast(added === 1 ? 'Added to the library' : `${added} files added`);
    if (failed.length) setError(failed.join(' · '));
    await load();
  }

  async function rename(asset: Asset, name: string) {
    const next = name.trim();
    if (!next || next === asset.name) return;
    try {
      await api(`/api/assets/${asset.digest}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: next }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not rename that.');
    }
  }

  async function remove(asset: Asset) {
    if (!(await ask(`Remove “${nameOf(asset)}” from the library? This cannot be undone.`))) return;
    try {
      await api(`/api/assets/${asset.digest}`, { method: 'DELETE' });
      toast('Removed from the library');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove that.');
    }
  }

  const shown = (assets ?? []).filter((a) => onShelf(a, shelf));
  const count = (key: Shelf) =>
    key === 'builtin'
      ? (builtInCount ?? BUILT_IN_MARKS)
      : (assets ?? []).filter((a) => onShelf(a, key)).length;

  async function removeUnused() {
    const unused = (assets ?? []).filter((a) => onShelf(a, 'unused'));
    if (!(await ask(`Remove all ${unused.length} unused files from the library? Nothing uses them, and this cannot be undone.`))) return;
    let removed = 0;
    for (const asset of unused) {
      try {
        await api(`/api/assets/${asset.digest}`, { method: 'DELETE' });
        removed += 1;
      } catch {
        // One refusal (it came into use a moment ago) does not stop the rest.
      }
    }
    toast(removed === unused.length ? `Removed ${removed}` : `Removed ${removed} · ${unused.length - removed} kept`);
    await load();
  }

  return (
    <>
      <PageHeader
        title="Assets"
        description="Your staff's photos, and the library of pictures, video and sound your walls, badges and celebrations use — with where each one is used."
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {/* **Staff photos are their own upload** (moved here from Settings),
          first on the page: a zip matched to people by name, which become
          their profile pictures — not files in the library below. */}
      <div id="staff-photos" className="mb-8 scroll-mt-20">
        <BulkPhotos />
      </div>

      {/* Add files sits with the library it adds to, not over the page —
          right above Staff photos it read as that section's button. */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-h3 text-content">Library</h2>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          multiple
          className="sr-only"
          aria-label="Choose files to add"
          onChange={(e) => void add(e.target.files)}
        />
        <button
          type="button"
          onClick={() => input.current?.click()}
          disabled={uploading > 0}
          className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {uploading > 0 ? `Adding ${uploading}…` : 'Add files'}
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-1">
        {SHELVES.map((s) => (
          <Tab key={s.key} active={shelf === s.key} onClick={() => setShelf(s.key)}>
            {s.label}
            {assets && <span className="ml-1.5 text-content-subtle">{count(s.key)}</span>}
          </Tab>
        ))}
      </div>

      {shelf === 'unused' && shown.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-edge px-4 py-3 text-sm">
          <span className="text-content-muted">
            Nothing on a wall, a badge, a celebration or a walk-up uses these.
          </span>
          <button
            type="button"
            onClick={() => void removeUnused()}
            className="rounded-md border border-danger/50 px-3 py-1.5 text-danger hover:bg-danger/10"
          >
            Remove all {shown.length}
          </button>
        </div>
      )}

      <p className="mb-4 text-xs text-content-subtle">
        Add files takes PNG, JPEG or WebP pictures up to 10 MB — a picture with
        transparency is kept as art, anything else is fitted to a TV — MP4 video
        up to 20 MB and a minute long, and sound up to 15 seconds. It is not for
        people&rsquo;s photos: those are uploaded under{' '}
        <a href="#staff-photos" className="underline">
          Staff photos
        </a>
        , above.
      </p>

      {shelf === 'builtin' ? (
        <BuiltIn onCount={setBuiltInCount} />
      ) : assets === null ? (
        !error && <Loading />
      ) : shown.length === 0 ? (
        <EmptyState
          title={
            shelf === 'unused'
              ? 'Everything here is in use'
              : shelf === 'photos'
                ? 'No profile pictures yet'
              : shelf === 'all'
                ? 'Nothing here yet'
                : `No ${SHELVES.find((s) => s.key === shelf)!.label.toLowerCase()} yet`
          }
          description="Add a logo, a backdrop, a loop or a sound, and use it anywhere a wall or a celebration asks for one."
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {shown.map((asset) => (
            <AssetCard
              key={asset.digest}
              asset={asset}
              onRename={(name) => void rename(asset, name)}
              onRemove={() => void remove(asset)}
            />
          ))}
        </ul>
      )}
    </>
  );
}

export function nameOf(asset: Asset): string {
  if (asset.photo_of) return asset.photo_of;
  return asset.name || `${KIND_WORD[asset.kind]} from ${dayMonth(asset.created_at)}`;
}

function sizeOf(asset: Asset): string {
  const parts: string[] = [];
  if (asset.width && asset.height) parts.push(`${asset.width}×${asset.height}`);
  if (asset.duration_ms) parts.push(`${Math.round(asset.duration_ms / 100) / 10}s`);
  const kb = asset.byte_size / 1024;
  parts.push(kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(kb))} KB`);
  return parts.join(' · ');
}

function AssetCard({
  asset,
  onRename,
  onRemove,
}: {
  asset: Asset;
  onRename: (name: string) => void;
  onRemove: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const src = `/api/images/${asset.digest}`;
  const used = asset.used_in.length > 0;
  const photo = Boolean(asset.photo_of);

  return (
    <li className="flex flex-col overflow-hidden rounded-lg border border-edge bg-surface">
      {/* A checkerboard behind pictures, so transparent art reads as art. */}
      <div className="flex aspect-video items-center justify-center overflow-hidden bg-[repeating-conic-gradient(var(--gg-surface-raised)_0%_25%,var(--gg-surface)_0%_50%)] bg-[length:20px_20px]">
        {asset.kind === 'image' && (
          <img src={src} alt="" className="h-full w-full object-contain" loading="lazy" />
        )}
        {asset.kind === 'video' && (
          <video src={src} muted loop playsInline controls preload="metadata" className="h-full w-full object-contain" />
        )}
        {asset.kind === 'audio' && (
          <audio src={src} controls preload="none" className="w-11/12" aria-label={`Play ${nameOf(asset)}`} />
        )}
      </div>

      <div className="flex flex-1 flex-col p-3">
        {photo ? (
          <p className="truncate text-sm text-content">{nameOf(asset)}</p>
        ) : editing ? (
          <input
            autoFocus
            defaultValue={asset.name ?? ''}
            maxLength={120}
            aria-label="Name"
            onBlur={(e) => {
              setEditing(false);
              onRename(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
              if (e.key === 'Escape') setEditing(false);
            }}
            className="rounded-md border border-edge bg-bg px-2 py-1 text-sm text-content outline-none focus:border-brand"
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            title="Rename"
            className="truncate text-left text-sm text-content hover:underline"
          >
            {nameOf(asset)}
          </button>
        )}
        <p className="mt-0.5 text-xs text-content-subtle">
          {photo
            ? asset.photo_source === 'synced'
              ? 'Synced from Microsoft 365'
              : 'Uploaded'
            : `${KIND_WORD[asset.kind]} · ${sizeOf(asset)}`}
        </p>

        <div className="mt-2 flex-1 text-xs">
          {photo ? (
            <p className="text-content-subtle">Profile picture — change it on their page</p>
          ) : used ? (
            <ul className="space-y-0.5">
              {asset.used_in.slice(0, 3).map((u) => (
                <li key={`${u.label}${u.link}`} className="truncate">
                  <Link to={u.link} className="text-content-muted hover:text-content hover:underline">
                    {u.label}
                  </Link>
                </li>
              ))}
              {asset.used_in.length > 3 && (
                <li className="text-content-subtle">and {asset.used_in.length - 3} more</li>
              )}
            </ul>
          ) : (
            <p className="text-content-subtle">Not used anywhere</p>
          )}
        </div>

        {!photo && (
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={onRemove}
            disabled={used}
            title={used ? 'In use — change what uses it first' : undefined}
            className="rounded-md px-2 py-1 text-xs text-content-muted transition-colors hover:bg-surface-hover hover:text-danger disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-content-muted"
          >
            Remove
          </button>
        </div>
        )}
      </div>
    </li>
  );
}
