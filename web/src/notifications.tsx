import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import { api } from './api';

export interface Notification {
  id: number;
  event_key: string;
  title: string;
  body: string | null;
  link_url: string | null;
  created_at: string;
  read_at: string | null;
  celebrated_at: string | null;
  celebrate: boolean;
  from_name: string | null;
}

interface Feed {
  notifications: Notification[];
  unread: number;
}

interface Value {
  notifications: Notification[];
  unread: number;
  refresh: () => Promise<void>;
  markRead: (id: number) => Promise<void>;
  markAllRead: () => Promise<void>;
  markCelebrated: (id: number) => Promise<void>;
  /** Clear one from the bell (12.1) — still the win everywhere else. */
  dismiss: (id: number) => Promise<void>;
  /** Clear the bell; resolves to what was cleared, for the Undo. */
  dismissAll: () => Promise<number[]>;
  /** The Undo. */
  restore: (ids: number[]) => Promise<void>;
}

/** How often the feed refreshes. Detection runs on a job cycle measured in
 *  minutes, so polling faster only asks for changes that cannot have happened
 *  yet. This is the dial to turn if celebrations should feel more immediate. */
const POLL_MS = 60_000;

const NotificationContext = createContext<Value | null>(null);

/**
 * One poll, shared by the bell and the celebration overlay.
 *
 * They read the same rows for different purposes — the bell wants unread, the
 * overlay wants uncelebrated — and two independent polls would double the
 * requests while letting the two disagree about what exists. Nothing is more
 * confusing than a badge saying 3 beside a celebration for something the badge
 * has not noticed.
 */
export function NotificationProvider({ children }: { children: ReactNode }) {
  const [feed, setFeed] = useState<Feed>({ notifications: [], unread: 0 });

  const refresh = useCallback(async () => {
    try {
      setFeed(await api<Feed>('/api/notifications'));
    } catch {
      // A failed poll keeps the last known state. The next tick corrects it,
      // and an error banner every time a laptop wakes up would be worse than
      // a number that is briefly stale.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const markRead = useCallback(
    async (id: number) => {
      await api(`/api/notifications/${id}/read`, { method: 'POST' });
      await refresh();
    },
    [refresh],
  );

  const markAllRead = useCallback(async () => {
    await api('/api/notifications/read-all', { method: 'POST' });
    await refresh();
  }, [refresh]);

  const dismiss = useCallback(
    async (id: number) => {
      // Gone from the list at once; the request only confirms it.
      setFeed((was) => ({
        notifications: was.notifications.filter((n) => n.id !== id),
        unread: was.unread - (was.notifications.find((n) => n.id === id)?.read_at === null ? 1 : 0),
      }));
      await api(`/api/notifications/${id}/dismiss`, { method: 'POST' });
      await refresh();
    },
    [refresh],
  );

  const dismissAll = useCallback(async () => {
    setFeed({ notifications: [], unread: 0 });
    const { ids } = await api<{ ids: number[] }>('/api/notifications/dismiss-all', {
      method: 'POST',
    });
    await refresh();
    return ids;
  }, [refresh]);

  const restore = useCallback(
    async (ids: number[]) => {
      await api('/api/notifications/restore', { method: 'POST', body: JSON.stringify({ ids }) });
      await refresh();
    },
    [refresh],
  );

  const markCelebrated = useCallback(async (id: number) => {
    await api(`/api/notifications/${id}/celebrated`, { method: 'POST' });
    // Deliberately no refresh. This fires as the overlay closes, and pulling
    // the feed out from under a component mid-animation is how you get a
    // celebration that flickers back for a frame.
  }, []);

  return (
    <NotificationContext.Provider
      value={{
        notifications: feed.notifications,
        unread: feed.unread,
        refresh,
        markRead,
        markAllRead,
        markCelebrated,
        dismiss,
        dismissAll,
        restore,
      }}
    >
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications(): Value {
  const value = useContext(NotificationContext);
  if (!value) {
    throw new Error('useNotifications must be used inside a NotificationProvider');
  }
  return value;
}

/**
 * Ask the bell to look again now, after something that may have told this
 * person something — a recognition, a badge.
 *
 * It otherwise waits for its minute, so a count visibly lagged the thing that
 * caused it (QA-35). A no-op outside the shell, where there is no bell.
 */
export function useRefreshNotifications(): () => void {
  const value = useContext(NotificationContext);
  return useCallback(() => {
    void value?.refresh();
  }, [value]);
}

/**
 * Celebratory and not yet shown, oldest first.
 *
 * The feed arrives newest-first, which is right for a list and wrong for a
 * sequence of events — Monday's win should not play after Friday's.
 *
 * Reversing in place is safe here only because `filter` has already returned a
 * new array. An earlier version had a defensive `.slice()` in between, and a
 * mutation proved it could be deleted without changing any result. The test
 * that the input is not mutated stays, because the property matters even
 * though it now comes for free.
 */
export function pendingCelebrations(notifications: Notification[]): Notification[] {
  return notifications.filter((n) => n.celebrate && n.celebrated_at === null).reverse();
}
