import { clockTime, dayMonth } from '../time';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useNotifications, type Notification } from '../notifications';
import { toast } from '../toast';
import { BellIcon, CloseIcon } from './icons';

/** "Today", "Yesterday", or the date — the grouping people actually think in. */
function dayLabel(iso: string): string {
  const then = new Date(iso);
  const today = new Date();
  const days = Math.floor(
    (new Date(today.toDateString()).getTime() - new Date(then.toDateString()).getTime()) /
      86_400_000,
  );
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  return dayMonth(then, today);
}

function timeLabel(iso: string): string {
  return clockTime(iso);
}

/**
 * The bell, and the panel behind it.
 *
 * The feed comes from the shared context rather than a poll of its own, so the
 * badge and the celebration overlay can never disagree about what exists.
 */
export default function NotificationBell() {
  const { notifications: items, unread, markRead, markAllRead, dismiss, dismissAll, restore } =
    useNotifications();
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  // Each row's own button, so focus can land on the next one after a clear.
  const rowButtons = useRef(new Map<number, HTMLButtonElement>());
  // Emptied by clearing, rather than empty from the start (P4-15).
  const [clearedHere, setClearedHere] = useState(false);

  // Escape and click-outside, because a panel that can only be closed by the
  // button that opened it is a trap for anyone not using a mouse.
  useEffect(() => {
    if (!open) return;

    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    function onClick(event: MouseEvent) {
      if (!panel.current?.contains(event.target as Node)) setOpen(false);
    }

    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  // **Cleared, with a way back** (12.1): one press, no question first — the
  // Undo is the safety, and it is still the win on Recognition and the walls.
  async function clearOne(notification: Notification) {
    // **Focus to the next row, not the page** (P4-4): after ✕ it dropped to
    // <body>, and a keyboard user was back at the top of the app.
    const at = items.findIndex((n) => n.id === notification.id);
    const next = items[at + 1] ?? items[at - 1];
    setClearedHere(true);
    await dismiss(notification.id).catch(() => undefined);
    window.requestAnimationFrame(() => {
      const target = next ? rowButtons.current.get(next.id) : null;
      (target ?? panel.current?.querySelector<HTMLElement>('[data-panel-heading]'))?.focus();
    });
    toast('Cleared from your notifications', undefined, {
      label: 'Undo',
      run: () => void restore([notification.id]),
    });
  }

  async function clearAll() {
    setClearedHere(true);
    const ids = await dismissAll().catch(() => [] as number[]);
    if (ids.length === 0) return;
    toast(`Cleared ${ids.length} notification${ids.length === 1 ? '' : 's'}`, undefined, {
      label: 'Undo',
      run: () => void restore(ids),
    });
  }

  async function openItem(notification: Notification) {
    setOpen(false);
    if (notification.read_at === null) await markRead(notification.id);
    if (notification.link_url) navigate(notification.link_url);
  }

  return (
    <div className="relative" ref={panel}>
      <button
        onClick={() => setOpen((was) => !was)}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        className="relative rounded-md p-2 text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
      >
        <BellIcon />
        {unread > 0 && (
          <span
            // Capped, because the badge is a prompt to look rather than a
            // figure anybody needs precisely, and four digits would not fit.
            className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-brand px-1 text-center text-[10px] font-medium leading-4 text-white"
          >
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        // A sheet across a phone, under the top bar (Q2-8): anchored to the
        // bell, a 320-pixel panel hung 17 pixels off a 375-pixel screen.
        <div className="fixed inset-x-2 top-14 z-40 overflow-hidden rounded-lg border border-edge bg-surface shadow-lg sm:absolute sm:inset-x-auto sm:right-0 sm:top-auto sm:mt-2 sm:w-96">
          <div className="flex items-center justify-between gap-3 border-b border-edge px-4 py-3">
            <h2 data-panel-heading tabIndex={-1} className="text-sm font-medium text-content outline-none">
              Notifications
            </h2>
            <div className="flex items-center gap-3">
              {unread > 0 && (
                <button
                  onClick={() => void markAllRead()}
                  className="text-xs text-brand hover:underline"
                >
                  Mark all read
                </button>
              )}
              {items.length > 0 && (
                <button
                  onClick={() => void clearAll()}
                  className="text-xs text-content-muted hover:text-content hover:underline"
                >
                  Clear all
                </button>
              )}
            </div>
          </div>

          {items.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-content-muted">
              {clearedHere
                ? 'All caught up.'
                : 'Nothing yet. Goals you hit and recognition you are sent turn up here.'}
            </p>
          ) : (
            <ul className="max-h-96 overflow-y-auto">
              {items.map((notification, index) => {
                const day = dayLabel(notification.created_at);
                const startsDay =
                  index === 0 || dayLabel(items[index - 1]!.created_at) !== day;
                return (
                  <li key={notification.id}>
                    {startsDay && (
                      <p className="bg-bg px-4 py-1 text-caption uppercase tracking-wide text-content-subtle">
                        {day}
                      </p>
                    )}
                    <div className="group relative">
                      <button
                        ref={(node) => {
                          if (node) rowButtons.current.set(notification.id, node);
                          else rowButtons.current.delete(notification.id);
                        }}
                        onClick={() => void openItem(notification)}
                        className="flex w-full gap-3 py-3 pl-4 pr-14 text-left transition-colors hover:bg-surface-hover sm:pr-10"
                      >
                        {/* Unread is a dot rather than a background wash: a
                            coloured row behind text is the first thing to fail a
                            contrast check, and the dot survives any theme. */}
                        <span
                          aria-hidden="true"
                          className={`mt-1.5 size-2 shrink-0 rounded-full ${
                            notification.read_at === null ? 'bg-brand' : 'bg-transparent'
                          }`}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm text-content">
                            {notification.title}
                          </span>
                          {notification.body && (
                            <span className="block truncate text-xs text-content-subtle">
                              {notification.body}
                            </span>
                          )}
                          <span className="mt-0.5 block text-xs text-content-subtle">
                            {notification.from_name
                              ? `${notification.from_name} · ${timeLabel(notification.created_at)}`
                              : timeLabel(notification.created_at)}
                          </span>
                        </span>
                      </button>
                      {/* A sibling, not inside the row: a button in a button is
                          invalid, and pressing it would open the thing too. */}
                      <button
                        type="button"
                        onClick={() => void clearOne(notification)}
                        aria-label={`Clear “${notification.title}”`}
                        title="Clear"
                        // **Faint, never hidden** (P4-4): invisible until
                        // hover, most people only ever found "Clear all".
                        // 44 px to tap on a phone; smaller beside a mouse.
                        className="absolute right-0 top-0 rounded p-3 text-content-subtle transition-all hover:bg-surface-raised hover:text-content sm:right-2 sm:top-2.5 sm:p-1 sm:opacity-40 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                      >
                        <CloseIcon />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
