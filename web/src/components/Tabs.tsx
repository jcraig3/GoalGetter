import type { ReactNode } from 'react';

/**
 * One tab in a small filter row.
 *
 * Extracted from the goals page, which had it first, so that offices, teams
 * and channels do not each grow their own. Three copies of a button style is
 * how a design system quietly stops being one.
 *
 * `aria-pressed` rather than the tab role: this is a set of toggle buttons
 * that filter a list below, not a tablist with panels, and claiming otherwise
 * makes a screen reader promise navigation that is not there.
 */
export function Tab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-md px-3 py-1.5 text-sm transition-colors ${
        active
          ? 'bg-brand-subtle text-content'
          : 'text-content-muted hover:bg-surface-hover hover:text-content'
      }`}
    >
      {children}
    </button>
  );
}

/**
 * The Active / Archived pair, which three pages now want identically.
 *
 * A tab rather than a checkbox because archived things are a *different list*,
 * not the same list with extra rows: what you can do to them differs, and
 * mixing them means every row has to say which kind it is.
 */
export function ArchiveTabs({
  showArchived,
  onChange,
  activeLabel = 'Active',
}: {
  showArchived: boolean;
  onChange: (archived: boolean) => void;
  activeLabel?: string;
}) {
  return (
    <div className="mb-4 flex gap-2">
      <Tab active={!showArchived} onClick={() => onChange(false)}>
        {activeLabel}
      </Tab>
      <Tab active={showArchived} onClick={() => onChange(true)}>
        Archived
      </Tab>
    </div>
  );
}
