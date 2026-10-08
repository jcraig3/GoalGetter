import { useId, useMemo, useRef, useState } from 'react';

import Avatar from './Avatar';
import { matchPeople, matchTeams, OFFERED, secondLine, type PickPerson } from './peoplePick';

type Props = {
  label: string;
  /** Everybody who may be chosen — the default roster, so hidden people are
   *  already out. */
  people: PickPerson[];
  hint?: string;
  /** Never offered: yourself where that makes no sense, say. */
  exclude?: number[];
  placeholder?: string;
} & (
  | { multiple?: false; value: number | null; onChange: (id: number | null) => void }
  | { multiple: true; value: number[]; onChange: (ids: number[]) => void }
);

type Offer =
  | { kind: 'person'; person: PickPerson }
  | { kind: 'team'; name: string; ids: number[] }
  | { kind: 'all'; ids: number[] };

/**
 * Choose a person — or several — out of hundreds, by typing.
 *
 * **Why it exists.** Goal, recognition, badge and correction forms were native
 * dropdowns of 461 names, and competition entrants were 461 checkboxes — the
 * review's largest usability problem (#1). Typing three letters beats
 * scrolling for anybody, and on a phone it is the only thing that works.
 *
 * **A real input with a list under it**, like `Combobox`: arrows, Enter and
 * Escape, and no dependency. Each name has its team and address underneath,
 * so two people with one name are two different rows. Choosing several shows
 * them as chips above the box, and offers the shortcuts that matter at this
 * size — a whole team, or everybody the search found.
 */
export default function PeoplePicker(props: Props) {
  const { label, people, hint, placeholder } = props;
  const id = useId();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  const overList = useRef(false);
  const input = useRef<HTMLInputElement>(null);

  const chosen = props.multiple ? props.value : props.value === null ? [] : [props.value];
  const byId = useMemo(() => new Map(people.map((p) => [p.id, p])), [people]);
  const exclude = useMemo(
    () => new Set([...(props.exclude ?? []), ...(props.multiple ? chosen : [])]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [props.exclude, chosen.join(',')],
  );

  const matched = matchPeople(people, query, exclude);
  const offers: Offer[] = [
    ...matched.slice(0, OFFERED).map((person) => ({ kind: 'person' as const, person })),
  ];
  if (props.multiple && query.trim()) {
    for (const team of matchTeams(people, query, exclude)) {
      if (team.ids.length > 1) offers.push({ kind: 'team', name: team.name, ids: team.ids });
    }
    if (matched.length > 1) offers.push({ kind: 'all', ids: matched.map((p) => p.id) });
  }

  function take(offer: Offer) {
    if (props.multiple) {
      const add = offer.kind === 'person' ? [offer.person.id] : offer.ids;
      props.onChange([...props.value, ...add.filter((x) => !props.value.includes(x))]);
      setQuery('');
      input.current?.focus();
      // **Closed after a pick** (8.3): it stayed open listing everybody, and
      // the next pick meant reading past the whole roster. Typing reopens it.
      setOpen(false);
    } else if (offer.kind === 'person') {
      props.onChange(offer.person.id);
      setQuery('');
      setOpen(false);
    }
    setHighlighted(0);
  }

  function drop(personId: number) {
    if (props.multiple) props.onChange(props.value.filter((x) => x !== personId));
    else props.onChange(null);
  }

  const single = !props.multiple && props.value !== null ? byId.get(props.value) : null;

  return (
    <div className="relative">
      <label htmlFor={id} className="block text-sm text-content-muted">
        {label}
      </label>

      {props.multiple && chosen.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-1.5" aria-label={`${label}: chosen`}>
          {chosen.map((personId) => {
            const person = byId.get(personId);
            return (
              <li
                key={personId}
                className="flex items-center gap-1.5 rounded-full border border-edge bg-bg py-0.5 pl-1 pr-2 text-sm text-content"
              >
                <Avatar name={person?.full_name ?? '?'} digest={person?.photo_digest} />
                {person?.full_name ?? 'Someone no longer listed'}
                <button
                  type="button"
                  onClick={() => drop(personId)}
                  aria-label={`Remove ${person?.full_name ?? 'this person'}`}
                  className="text-content-subtle hover:text-danger"
                >
                  ×
                </button>
              </li>
            );
          })}
          {chosen.length > 1 && (
            <li>
              <button
                type="button"
                onClick={() => props.multiple && props.onChange([])}
                className="px-1 text-xs text-content-muted hover:text-content"
              >
                Clear all {chosen.length}
              </button>
            </li>
          )}
        </ul>
      )}

      {single ? (
        // Chosen: shown as the person, with a way to change it, rather than as
        // a box of text that looks like it still wants typing.
        <div className="mt-1 flex items-center gap-3 rounded-md border border-edge bg-bg px-3 py-2">
          <Avatar name={single.full_name} digest={single.photo_digest} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-content">{single.full_name}</span>
            <span className="block truncate text-xs text-content-subtle">{secondLine(single)}</span>
          </span>
          <button
            type="button"
            onClick={() => {
              drop(single.id);
              setTimeout(() => input.current?.focus());
            }}
            className="shrink-0 text-xs text-brand hover:underline"
          >
            Change
          </button>
        </div>
      ) : (
        <input
          ref={input}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          autoComplete="off"
          value={query}
          placeholder={placeholder ?? 'Type a name, an email or a team'}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setHighlighted(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            if (!overList.current) setOpen(false);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              // Closes the list, and stops there — not the dialog around it.
              if (open) e.stopPropagation();
              setOpen(false);
              return;
            }
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault();
              setOpen(true);
              setHighlighted((at) => {
                if (offers.length === 0) return 0;
                const next = e.key === 'ArrowDown' ? at + 1 : at - 1;
                return (next + offers.length) % offers.length;
              });
              return;
            }
            if (e.key === 'Enter' && open && offers[highlighted]) {
              // Only while the list points at something, or this would eat the
              // Enter that submits the form.
              e.preventDefault();
              take(offers[highlighted]);
            }
            if (e.key === 'Backspace' && query === '' && props.multiple && chosen.length) {
              drop(chosen[chosen.length - 1]!);
            }
          }}
          className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none focus:border-brand"
        />
      )}

      {hint && <p className="mt-1 text-xs text-content-muted">{hint}</p>}

      {open && !single && (
        <ul
          id={`${id}-list`}
          role="listbox"
          onMouseEnter={() => {
            overList.current = true;
          }}
          onMouseLeave={() => {
            overList.current = false;
          }}
          className="absolute z-30 mt-1 max-h-80 w-full overflow-y-auto rounded-md border border-edge bg-surface shadow-lg"
        >
          {offers.length === 0 && (
            <li className="px-3 py-2 text-sm text-content-muted">
              {query.trim() ? `Nobody matches “${query.trim()}”.` : 'Nobody left to choose.'}
            </li>
          )}
          {offers.map((offer, index) => (
            <li key={offer.kind === 'person' ? offer.person.id : `${offer.kind}:${'name' in offer ? offer.name : ''}`}>
              <button
                type="button"
                role="option"
                aria-selected={index === highlighted}
                onMouseDown={(e) => {
                  e.preventDefault();
                  take(offer);
                }}
                onMouseMove={() => setHighlighted(index)}
                className={`flex w-full items-center gap-3 px-3 py-2 text-left ${
                  index === highlighted ? 'bg-surface-hover' : ''
                } ${offer.kind !== 'person' ? 'border-t border-edge' : ''}`}
              >
                {offer.kind === 'person' ? (
                  <>
                    <Avatar name={offer.person.full_name} digest={offer.person.photo_digest} />
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-content">
                        {offer.person.full_name}
                      </span>
                      <span className="block truncate text-xs text-content-subtle">
                        {secondLine(offer.person)}
                      </span>
                    </span>
                  </>
                ) : offer.kind === 'team' ? (
                  <span className="text-sm text-brand">
                    Add everyone on {offer.name} ({offer.ids.length})
                  </span>
                ) : (
                  <span className="text-sm text-brand">
                    Add all {offer.ids.length} matching “{query.trim()}”
                  </span>
                )}
              </button>
            </li>
          ))}
          {matched.length > OFFERED && (
            <li className="px-3 py-1.5 text-xs text-content-subtle">
              {matched.length - OFFERED} more — keep typing to narrow it down.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
