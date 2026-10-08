import { useRef, useState } from 'react';

import { isKnown, matching, peopleFor, type Option } from './optionMatch';

/**
 * A text box that offers what the source actually contains.
 *
 * **Typeable, not a `<select>`, and that is the whole design.** A rule matching on
 * a department is a string comparison against what a provider reported, so a
 * dropdown of real values removes the failure this replaced: `Sales` typed against
 * a tenant that says `Sales Team` saves cleanly, matches nobody, and looks like a
 * broken feature. But locking it to a list would break two ordinary cases — before
 * the first sync there is no list at all, and a rule written for a department that
 * is about to exist is a legitimate thing to want.
 *
 * So the list is *advice*: pick from it and the count tells you how many people you
 * just described; type past it and it says, quietly, that nothing carries this
 * value. The admin stays in charge and stops being able to do it by accident.
 *
 * A real `<input>` with a filtered list under it rather than a headless combobox
 * library: the keyboard behaviour that matters here is arrows, enter and escape,
 * and the rest of this codebase does not carry a dependency for that.
 */
export default function Combobox({
  label,
  value,
  onChange,
  options,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** What the source holds, commonest first. Empty means nothing is known yet. */
  options: Option[];
  placeholder?: string;
}) {
  const id = label.toLowerCase().replace(/\s+/g, '-');
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(0);
  // Blur fires before a click on the list registers, so closing on blur alone
  // eats the selection. Closing on blur *unless* the pointer is over the list is
  // the smallest fix that keeps the box closing when you tab away.
  const overList = useRef(false);

  const offered = matching(options, value);
  const known = isKnown(options, value);
  const people = peopleFor(options, value);

  function choose(chosen: string) {
    onChange(chosen);
    setOpen(false);
    setHighlighted(0);
  }

  return (
    <div className="relative">
      <label htmlFor={id} className="text-sm text-content-muted">
        {label}
      </label>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setHighlighted(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          if (!overList.current) setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setOpen(false);
            return;
          }
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setOpen(true);
            setHighlighted((at) => {
              const next = e.key === 'ArrowDown' ? at + 1 : at - 1;
              if (offered.length === 0) return 0;
              return (next + offered.length) % offered.length;
            });
            return;
          }
          if (e.key === 'Enter' && open && offered[highlighted]) {
            // Only when the list is open and pointing at something — otherwise
            // this swallows the Enter that submits the form.
            e.preventDefault();
            choose(offered[highlighted].value);
          }
        }}
        className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content"
      />

      {/* What was typed, judged. Three states, and they are genuinely different:
          nothing typed means "any" and needs no comment; a known value earns its
          headcount; an unknown one earns a warning rather than a refusal. */}
      {value.trim() !== '' && (
        <p className={`mt-1 text-xs ${known ? 'text-content-subtle' : 'text-warning'}`}>
          {known
            ? `${people ?? 0} ${people === 1 ? 'person has' : 'people have'} this`
            : 'Nobody read from your directory has this — a rule on it will match nobody.'}
        </p>
      )}

      {open && offered.length > 0 && (
        <ul
          role="listbox"
          onMouseEnter={() => {
            overList.current = true;
          }}
          onMouseLeave={() => {
            overList.current = false;
          }}
          className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-edge bg-surface shadow-lg"
        >
          {offered.map((option, index) => (
            <li key={option.value}>
              <button
                type="button"
                role="option"
                aria-selected={index === highlighted}
                onMouseDown={() => choose(option.value)}
                onMouseMove={() => setHighlighted(index)}
                className={`flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left text-sm ${
                  index === highlighted ? 'bg-surface-hover text-content' : 'text-content'
                }`}
              >
                <span className="min-w-0 break-words">{option.value}</span>
                <span className="shrink-0 text-xs text-content-subtle">
                  {option.people}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
