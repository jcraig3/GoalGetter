import { useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';

/**
 * A square action button that shows its name on hover and focus.
 *
 * Rows of actions get wide fast, and three word-buttons per screen pushed the
 * useful columns off the side of the table. Icons buy that space back, but an
 * icon alone is a guess — so the label is always present in the accessible
 * tree (`aria-label`) and appears visually on hover or keyboard focus. Nobody
 * has to click something to find out what it does.
 *
 * **Drawn above the button, outside the table** (QA-25). The name used to sit
 * to the button's left inside the row, so in a row of three it lay across its
 * neighbours — "Renar · Archiv · Delete" — and a scrolling table clipped it.
 * It is now rendered at the end of the page, positioned from the button's own
 * rectangle: above it, or below when there is no room above, and kept on
 * screen sideways. Nothing clips it and nothing sits under it.
 *
 * Not a `title` attribute: the browser delays that about a second, it cannot
 * be styled, and it never appears for keyboard users.
 */
export default function IconButton({
  label,
  icon,
  onClick,
  href,
  to,
  danger = false,
}: {
  label: string;
  icon: ReactNode;
  /** Provide exactly one of these three. */
  onClick?: () => void;
  /** An external URL. Opens in a new tab — that is what `href` means here. */
  href?: string;
  /**
   * A route inside the app.
   *
   * Separate from `href` because that one opens a new tab, which is right for a
   * wall link and wrong for "edit this person". Before this existed, the Users
   * page hand-rolled a styled `<Link>` with a `title` attribute — so it looked
   * like these buttons but got the browser's a-second-later unstyled tooltip
   * that keyboard users never see, which is the whole thing this component was
   * written to avoid.
   */
  to?: string;
  /** Destructive actions turn red on hover rather than sitting red always. */
  danger?: boolean;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; below: boolean } | null>(null);

  const shell =
    'relative flex size-8 items-center justify-center rounded-md border border-edge text-content-muted transition-colors ' +
    (danger
      ? 'hover:border-danger hover:text-danger'
      : 'hover:bg-surface-hover hover:text-content');

  // Where to draw the name, from where the button is right now.
  const show = (event: { currentTarget: Element }) => {
    const r = event.currentTarget.getBoundingClientRect();
    const below = r.top < 40;
    setTip({ x: r.left + r.width / 2, y: below ? r.bottom + 6 : r.top - 6, below });
  };
  const hide = () => setTip(null);
  const handlers = {
    onMouseEnter: show,
    onMouseLeave: hide,
    // Keyboard focus shows it too; a mouse click's focus does not need it.
    onFocus: (event: React.FocusEvent<Element>) => {
      let keyboard = true;
      try {
        keyboard = event.currentTarget.matches(':focus-visible');
      } catch {
        // An engine without the selector: show it, as it always did.
      }
      if (keyboard) show(event);
    },
    onBlur: hide,
  };

  const body = (
    <>
      {icon}
      {tip &&
        createPortal(
          <span
            role="presentation"
            aria-hidden="true"
            style={{
              position: 'fixed',
              top: tip.y,
              // Centred on the button, but never off either edge of the window.
              left: Math.min(Math.max(tip.x, 60), window.innerWidth - 60),
              transform: `translate(-50%, ${tip.below ? '0' : '-100%'})`,
            }}
            // pointer-events-none so the name can never sit between the
            // cursor and the button it describes.
            className="pointer-events-none z-[80] whitespace-nowrap rounded border border-edge bg-surface px-2 py-1 text-xs text-content shadow-sm"
          >
            {label}
          </span>,
          document.body,
        )}
    </>
  );

  if (to) {
    return (
      <Link to={to} aria-label={label} className={shell} {...handlers}>
        {body}
      </Link>
    );
  }

  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        // noopener stops the opened page reaching back through window.opener.
        rel="noopener noreferrer"
        aria-label={label}
        className={shell}
        {...handlers}
      >
        {body}
      </a>
    );
  }

  return (
    <button type="button" onClick={onClick} aria-label={label} className={shell} {...handlers}>
      {body}
    </button>
  );
}
