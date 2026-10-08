import { useEffect, useRef, useState } from 'react';

import { api } from '../api';

/**
 * What a celebration says, with the tags it can carry and a look at the result.
 *
 * **Three lines and a shuffle, rather than a language model.** The product this
 * borrows from rewords each announcement with AI, which needs an outbound
 * connection and a willingness to put text nobody wrote on a wall. Writing the
 * alternatives yourself does the same job for a floor that would otherwise
 * stop looking up, and the words are always words somebody chose.
 *
 * **The preview is the point of the control.** A merge tag is the one kind of
 * text where what you type is not what anybody reads, so the version with the
 * names filled in has to be on screen while you write it — otherwise the first
 * proofread happens on a television.
 */
export interface MergeTag {
  name: string;
  describes: string;
  example: string;
}

export default function MessageField({
  value,
  onChange,
  fallback,
}: {
  value: string;
  onChange: (value: string) => void;
  /** What the wall says when this is left empty. */
  fallback: string;
}) {
  const [tags, setTags] = useState<MergeTag[]>([]);
  const box = useRef<HTMLTextAreaElement>(null);
  //: Where the caret was when the box last had it.
  //:
  //: **Remembered rather than read on demand**, because pressing a tag button
  //: takes focus off the textarea first — so by the time the handler runs the
  //: browser reports a caret at zero and every tag lands at the front of the
  //: sentence. Null means the box has not been touched, and appending is what
  //: somebody expects then.
  const caret = useRef<number | null>(null);

  // Served rather than listed here, the same rule as the eligible screens: the
  // picker and the validation are then one catalogue, and the quiet version of
  // that mistake is a picker offering a tag the server refuses.
  useEffect(() => {
    api<MergeTag[]>('/api/achievement-rules/tags')
      .then(setTags)
      .catch(() => undefined);
  }, []);

  /** Insert where the caret was, or at the end if it has never been there. */
  function insert(tag: string) {
    const token = `{${tag}}`;
    const at = Math.min(caret.current ?? value.length, value.length);

    onChange(value.slice(0, at) + token + value.slice(at));
    caret.current = at + token.length;

    // Focus back and put the caret after what was inserted, so somebody can
    // keep typing the sentence they were in the middle of.
    const element = box.current;
    if (!element) return;
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(at + token.length, at + token.length);
    });
  }

  const lines = value.split('\n').filter((line) => line.trim());

  return (
    <div>
      <label htmlFor="message" className="block text-sm text-content-muted">
        What the wall says
      </label>

      <textarea
        id="message"
        ref={box}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onSelect={(e) => {
          caret.current = e.currentTarget.selectionStart;
        }}
        rows={3}
        placeholder={fallback}
        className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none focus:border-brand"
      />

      <div className="mt-2 flex flex-wrap gap-1.5">
        {tags.map((tag) => (
          <button
            key={tag.name}
            type="button"
            title={tag.describes}
            onClick={() => insert(tag.name)}
            className="rounded-md border border-edge px-2 py-1 font-mono text-xs text-content-muted transition-colors hover:border-brand hover:text-content"
          >
            {`{${tag.name}}`}
          </button>
        ))}
      </div>

      <p className="mt-2 text-xs text-content-subtle">
        One alternative per line — a different one is picked for each win, so a
        floor hearing four a day does not hear the same sentence twice. Leave
        it empty for “{fallback}”.
      </p>

      {lines.length > 0 && (
        <div className="mt-3 rounded-md border border-edge bg-surface px-3 py-2">
          <p className="text-xs text-content-subtle">
            {lines.length === 1
              ? 'On a wall'
              : `On a wall — one of these ${lines.length}`}
          </p>
          <ul className="mt-1 space-y-1">
            {lines.map((line, index) => (
              <li key={index} className="text-sm text-content">
                {fill(line, tags)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * One line with its tags replaced by examples.
 *
 * **Examples, not a real person's numbers.** A preview showing a genuine
 * colleague's figure would be a small privacy leak on a settings page, and the
 * point here is the shape of the sentence rather than any particular win.
 * Anything unrecognised is left visible — that is what the server does too, and
 * it is what makes a typo findable.
 */
function fill(line: string, tags: MergeTag[]): string {
  const examples = new Map(tags.map((tag) => [tag.name, tag.example]));
  return line.replace(
    /\{([a-z_]+)\}/g,
    (whole, name: string) => examples.get(name) ?? whole,
  );
}
