import { useEffect, useRef, useState } from 'react';

import Select from './Select';

/** One spreadsheet somebody could choose, whichever provider it came from. */
export interface SheetChoice {
  /** Opaque, and the provider's own. Microsoft needs two ids; it packs both. */
  id: string;
  name: string;
  location: string;
  modified: string;
}

/** A spreadsheet already connected, so the picker can say so before the click. */
export interface TakenSheet {
  id: string;
  tab: string;
}

/**
 * What one provider can do, so the picker itself knows about neither.
 *
 * **Written as an adapter rather than two components.** Excel and Sheets differ in
 * three requests and two nouns and in nothing else that matters here — the
 * debounce, the paste fallback, the collapse-when-chosen, the free-tab default and
 * the already-connected labelling are the same problem twice. A second copy would
 * have been 350 lines that drift apart the first time either is fixed.
 */
export interface SheetProvider {
  /** Empty term means "recent"; anything else searches. */
  browse: (q: string) => Promise<SheetChoice[]>;
  /** A pasted address, as a chosen file. The way to reach what browsing cannot. */
  resolve: (url: string) => Promise<SheetChoice>;
  tabs: (id: string) => Promise<string[]>;
  /** What is already connected, excluding the source being edited. */
  taken: () => Promise<TakenSheet[]>;

  /** "workbook" / "spreadsheet". Used in prose, so lowercase. */
  fileNoun: string;
  /** "worksheet" / "tab". */
  tabNoun: string;
  /** Where the sharing link is copied from, for the paste hint. */
  pasteHint: string;
  placeholder: string;
  /** Said in the empty state, where somebody whose file is not listed lands. */
  missingHint: string;
}

/**
 * Choosing a spreadsheet by looking at it, instead of by describing it.
 *
 * **This replaces two text boxes that were both traps.** One asked for an address
 * — which meant leaving the page, finding the file, copying a link, and coming
 * back with something wrong in several invisible ways. The other asked for the tab
 * name, typed from memory, where a typo produced "that tab is empty": true, and
 * useless, because it was not empty, it did not exist.
 *
 * Both answers were already available over the API the cells are read with. The
 * old form asked a person to be the lookup.
 *
 * **Recent first, search on demand, paste as a peer.** A drive listing would be
 * folders to click through; somebody connecting a spreadsheet almost always wants
 * one they touched this week. And pasting is not a fallback hidden under an
 * *Advanced* heading — for a file in a SharePoint site or a shared drive it is the
 * only route, and that is where plenty of teams keep theirs.
 */
export default function SpreadsheetPicker({
  provider,
  fileId,
  fileName,
  fileUrl,
  tab,
  onPick,
  onTab,
}: {
  provider: SheetProvider;
  fileId: string;
  /** What the chosen file is called. Stored, because the id is unreadable. */
  fileName: string;
  /**
   * An address the source was configured with before the picker existed.
   *
   * Carried in so it is not silently lost: it used to live in a text box under
   * *Advanced*, and hiding that box would have left an existing source showing an
   * empty picker with its own address nowhere on screen.
   */
  fileUrl: string;
  tab: string;
  onPick: (choice: SheetChoice | null) => void;
  onTab: (name: string) => void;
}) {
  const [term, setTerm] = useState('');
  const [hits, setHits] = useState<SheetChoice[] | null>(null);
  const [tabs, setTabs] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState<SheetChoice | null>(null);

  // **Two ways in, one visible at a time.** See the class comment: pasting is a
  // peer of search, not a fallback.
  const legacy = Boolean(fileUrl && !fileId);
  const [pasting, setPasting] = useState(legacy);
  const [link, setLink] = useState(legacy ? fileUrl : '');

  // **What is already connected, so a duplicate is visible instead of refused.**
  // The API rejects a second source on the same sheet either way, but a 409 at
  // the end of a wizard is a wasted trip — the answer was knowable before the
  // click. Failing silently just means nothing is greyed out.
  const [taken, setTaken] = useState<TakenSheet[]>([]);
  useEffect(() => {
    provider
      .taken()
      .then(setTaken)
      .catch(() => setTaken([]));
    // The adapter is rebuilt on each render by its caller; depending on it would
    // re-fetch forever. The identity that matters is the provider's nouns, which
    // do not change for the life of this component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.fileNoun]);

  const usedTabs = (id: string) =>
    taken.filter((t) => t.id === id).map((t) => t.tab);

  // Debounced, because every keystroke is a search and providers rate-limit them.
  // 300ms is under the threshold where typing feels laggy and well above one
  // request per character.
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (pasting || fileId) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setBusy(true);
      setError(null);
      provider
        .browse(term)
        .then(setHits)
        .catch((e) => {
          setHits([]);
          setError(e instanceof Error ? e.message : 'Could not list your files.');
        })
        .finally(() => setBusy(false));
    }, 300);
    return () => window.clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [term, pasting, fileId]);

  // The tabs, refetched whenever the file changes. Failing is not fatal: the tab
  // falls back to a typed name, which is what it always was.
  useEffect(() => {
    if (!fileId) {
      setTabs(null);
      return;
    }
    provider
      .tabs(fileId)
      .then((all) => {
        setTabs(all);
        // **Commit the default rather than only displaying it**, and the first
        // *free* one rather than the first. A dropdown that rendered a value
        // while the state stayed empty saved a source with no tab — which reads
        // as "the first one, whichever that is today" and silently changes
        // meaning if somebody reorders them. Defaulting onto a tab already
        // connected would seed every new source with a duplicate.
        const free = all.filter((n) => !usedTabs(fileId).includes(n));
        if (!tab && free[0]) onTab(free[0]);
      })
      .catch(() => setTabs(null));
    // `tab` is deliberately not a dependency: this fills it in, and depending on
    // it would re-run the moment it succeeded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId, taken]);

  async function usePastedLink() {
    const url = link.trim();
    if (!url) return;
    setBusy(true);
    setError(null);
    try {
      const hit = await provider.resolve(url);
      setChosen(hit);
      onPick(hit);
      setLink('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open that link.');
    } finally {
      setBusy(false);
    }
  }

  const Noun = provider.fileNoun.charAt(0).toUpperCase() + provider.fileNoun.slice(1);
  const allTaken =
    tabs !== null && tabs.length > 0 && tabs.every((n) => usedTabs(fileId).includes(n));

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm text-content" htmlFor="sheet-search">
          {Noun}
        </label>

        {fileId ? (
          // Chosen. The list collapses to the answer, because a picker still
          // showing fifty options after you picked one reads as unfinished.
          <div className="mt-1.5 flex items-center gap-3 rounded-md border border-edge bg-surface px-3 py-2">
            <span aria-hidden className="text-success">
              ✓
            </span>
            <span className="min-w-0 flex-1 truncate text-sm text-content">
              {chosen?.name || fileName || `${Noun} attached`}
              {chosen?.location && (
                <span className="ml-2 text-xs text-content-subtle">
                  {chosen.location}
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => {
                setChosen(null);
                setPasting(false);
                onPick(null);
              }}
              className="shrink-0 text-xs text-content-muted underline transition-colors hover:text-content"
            >
              Change
            </button>
          </div>
        ) : pasting ? (
          <>
            <div className="mt-1.5 flex flex-wrap items-end gap-2">
              <input
                id="sheet-link"
                type="url"
                value={link}
                onChange={(e) => setLink(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    void usePastedLink();
                  }
                }}
                placeholder={provider.placeholder}
                className="min-w-60 flex-1 rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none placeholder:text-content-subtle focus:border-brand"
              />
              <button
                type="button"
                onClick={() => void usePastedLink()}
                disabled={busy || !link.trim()}
                className="shrink-0 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
              >
                {busy ? 'Opening…' : 'Use this'}
              </button>
            </div>
            <p className="mt-1 text-xs text-content-subtle">
              {legacy && link
                ? `This is the address this source already uses. Press Use this to turn it into a proper choice, with a ${provider.tabNoun} list.`
                : provider.pasteHint}{' '}
              <button
                type="button"
                onClick={() => {
                  setPasting(false);
                  setError(null);
                }}
                className="underline transition-colors hover:text-content"
              >
                Search instead
              </button>
            </p>
          </>
        ) : (
          <>
            <input
              id="sheet-search"
              type="search"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="Search your spreadsheets…"
              className="mt-1.5 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none placeholder:text-content-subtle focus:border-brand"
            />
            <p className="mt-1 text-xs text-content-subtle">
              {term
                ? 'Searching what the connected account can open.'
                : 'Your recent spreadsheets. Type to search all of them.'}{' '}
              <button
                type="button"
                onClick={() => {
                  setPasting(true);
                  setError(null);
                }}
                className="underline transition-colors hover:text-content"
              >
                Or paste a link
              </button>
            </p>

            <div className="mt-2 max-h-64 overflow-y-auto rounded-md border border-edge">
              {busy && hits === null && (
                <p className="px-3 py-3 text-sm text-content-muted">Looking…</p>
              )}
              {hits?.length === 0 && !busy && (
                <div className="px-3 py-3 text-sm text-content-muted">
                  <p>
                    {term ? 'Nothing matching that.' : 'No recent spreadsheets here.'}
                  </p>
                  {/* Where somebody whose file is not listed actually lands, so
                      it is where the way out belongs. */}
                  <p className="mt-1 text-xs text-content-subtle">
                    {provider.missingHint}{' '}
                    <button
                      type="button"
                      onClick={() => {
                        setPasting(true);
                        setError(null);
                      }}
                      className="underline transition-colors hover:text-content"
                    >
                      Paste its link instead
                    </button>
                  </p>
                </div>
              )}
              {hits?.map((hit) => {
                const already = usedTabs(hit.id);
                return (
                  <button
                    key={hit.id}
                    type="button"
                    onClick={() => {
                      setChosen(hit);
                      onPick(hit);
                    }}
                    className="flex w-full items-center gap-3 border-b border-edge px-3 py-2 text-left transition-colors last:border-0 hover:bg-surface-hover"
                  >
                    <span aria-hidden className="shrink-0 text-content-subtle">
                      ▤
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-content">
                        {hit.name}
                      </span>
                      <span className="block truncate text-xs text-content-subtle">
                        {hit.location}
                        {hit.modified ? ` · ${hit.modified.slice(0, 10)}` : ''}
                        {/* **Still choosable, deliberately.** A file with a tab
                            per team is the normal shape, so "one tab is taken"
                            is not "this file is taken" — the list below is where
                            individual tabs get ruled out. */}
                        {already.length > 0 &&
                          ` · ${already.length} ${provider.tabNoun}${
                            already.length === 1 ? '' : 's'
                          } already connected`}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </>
        )}

        {error && (
          <p role="alert" className="mt-2 text-sm text-danger">
            {error}
          </p>
        )}
      </div>

      {/* Only once there is a file. A tab dropdown above the file it belongs to
          would be a control with nothing to list. */}
      {fileId &&
        (tabs && tabs.length > 0 ? (
          <Select
            label={provider.tabNoun.charAt(0).toUpperCase() + provider.tabNoun.slice(1)}
            value={tab}
            onChange={onTab}
            options={tabs.map((name) => {
              const used = usedTabs(fileId).includes(name);
              return {
                // A taken tab stays listed, labelled rather than removed —
                // removing it would leave somebody wondering whether it exists.
                value: used ? '' : name,
                label: used ? `${name} — already connected` : name,
              };
            })}
            hint={
              allTaken
                ? `Every ${provider.tabNoun} in this ${provider.fileNoun} is already connected. Choose a different one, or open the existing source to change it.`
                : undefined
            }
          />
        ) : (
          // The fallback, which is what this field always used to be. Reached
          // when the provider will not list them — a file still syncing, or one
          // too large to open.
          <div>
            <label className="block text-sm text-content" htmlFor="sheet-tab">
              {provider.tabNoun.charAt(0).toUpperCase() + provider.tabNoun.slice(1)}
            </label>
            <input
              id="sheet-tab"
              value={tab}
              onChange={(e) => onTab(e.target.value)}
              placeholder="Leave empty for the first one"
              className="mt-1.5 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none placeholder:text-content-subtle focus:border-brand"
            />
            <p className="mt-1 text-xs text-content-subtle">
              They could not be listed, so type the name — or leave it empty for
              the first one.
            </p>
          </div>
        ))}
    </div>
  );
}
