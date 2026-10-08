import { describe, expect, it } from 'vitest';

import { pendingCelebrations, type Notification } from './notifications';

/** The API's shape, with only the fields the selection actually reads set. */
function notification(overrides: Partial<Notification> & { id: number }): Notification {
  return {
    event_key: 'goal.achieved',
    title: 'Something',
    body: null,
    link_url: null,
    created_at: '2026-08-12T15:00:00Z',
    read_at: null,
    celebrated_at: null,
    celebrate: true,
    from_name: null,
    ...overrides,
  };
}

describe('which notifications get an overlay', () => {
  it('shows a celebratory one that has not been shown', () => {
    expect(pendingCelebrations([notification({ id: 1 })]).map((n) => n.id)).toEqual([1]);
  });

  it('ignores routine ones', () => {
    // Only the catalogue decides what interrupts. Everything else waits in the
    // bell to be found.
    const routine = notification({ id: 1, celebrate: false, event_key: 'goal.assigned' });
    expect(pendingCelebrations([routine])).toEqual([]);
  });

  it('never shows the same one twice', () => {
    const shown = notification({ id: 1, celebrated_at: '2026-08-12T15:01:00Z' });
    expect(pendingCelebrations([shown])).toEqual([]);
  });

  it('still shows one that has been read but never celebrated', () => {
    // Reading is not seeing. Somebody who opened the bell and clicked through
    // has still not had the moment.
    const read = notification({ id: 1, read_at: '2026-08-12T15:01:00Z' });
    expect(pendingCelebrations([read]).map((n) => n.id)).toEqual([1]);
  });

  it('plays a backlog oldest first', () => {
    // The feed arrives newest-first, which is right for a list and wrong for a
    // sequence of events — a Monday win should not play after a Friday one.
    const feed = [
      notification({ id: 3, created_at: '2026-08-12T15:00:00Z' }),
      notification({ id: 2, created_at: '2026-08-11T15:00:00Z' }),
      notification({ id: 1, created_at: '2026-08-10T15:00:00Z' }),
    ];
    expect(pendingCelebrations(feed).map((n) => n.id)).toEqual([1, 2, 3]);
  });

  it('does not mutate the feed it was given', () => {
    // It reverses, and reversing in place would quietly reorder the bell.
    const feed = [notification({ id: 2 }), notification({ id: 1 })];
    pendingCelebrations(feed);
    expect(feed.map((n) => n.id)).toEqual([2, 1]);
  });

  it('returns nothing for an empty feed', () => {
    expect(pendingCelebrations([])).toEqual([]);
  });
});
