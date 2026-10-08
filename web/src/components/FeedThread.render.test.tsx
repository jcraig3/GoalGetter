// @vitest-environment jsdom
/** Reactions and comments under a feed entry (6.15). */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import FeedThread, { whoReacted } from './FeedThread';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../auth', () => ({ useAuth: () => ({ user: { id: 9 }, can: () => false }) }));
const toasts = vi.hoisted(() => ({ last: null as null | { label: string; run: () => void } }));
vi.mock('../toast', () => ({
  TOAST_MS: 5000,
  UNDO_TOAST_MS: 10_000,
  toast: (_message: string, _link: unknown, action: { label: string; run: () => void }) => {
    toasts.last = action;
  },
}));

const { api } = await import('../api');

const COMMENT = {
  id: 1,
  body: 'Nobody deserved it more',
  created_at: new Date().toISOString(),
  author_id: 9,
  author_name: 'Me',
  author_photo_digest: null,
};

beforeEach(() => {
  vi.mocked(api).mockReset();
});

describe('a feed entry thread', () => {
  test('shows the reactions and who gave them', () => {
    render(
      <FeedThread
        entryId={4}
        reactions={[{ reaction: 'clap', count: 2, mine: true, names: ['Ann', 'Bob'] }]}
        comments={[]}
      />,
    );
    const clap = screen.getByRole('button', { name: 'Applause: Ann and Bob' });
    expect(clap.getAttribute('aria-pressed')).toBe('true');
    expect(clap.textContent).toContain('2');
  });

  test('reacting sends the reaction and shows what came back', async () => {
    vi.mocked(api).mockResolvedValue({
      reactions: [{ reaction: 'fire', count: 1, mine: true, names: ['Me'] }],
      comments: [],
    } as never);
    render(<FeedThread entryId={4} reactions={[]} comments={[]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Add a reaction' }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'On fire' }));
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith('/api/feed/4/reactions', {
      method: 'POST',
      body: JSON.stringify({ reaction: 'fire' }),
    });
    expect(screen.getByRole('button', { name: 'On fire: Me' })).toBeDefined();
  });

  test('comments fold away until opened, and your own can be removed', async () => {
    vi.useFakeTimers();
    render(<FeedThread entryId={4} reactions={[]} comments={[COMMENT]} />);
    expect(screen.queryByText('Nobody deserved it more')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '1 comment' }));
    expect(screen.getByText('Nobody deserved it more')).toBeDefined();

    // Gone at once, deleted only once the Undo has had its chance (Q2-17).
    vi.mocked(api).mockResolvedValue({ reactions: [], comments: [] } as never);
    fireEvent.click(screen.getByRole('button', { name: 'Remove comment' }));
    expect(screen.queryByText('Nobody deserved it more')).toBeNull();
    expect(vi.mocked(api)).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(vi.mocked(api)).toHaveBeenCalledWith('/api/feed/comments/1', { method: 'DELETE' });
    vi.useRealTimers();
  });

  test('a removed comment can be put back', async () => {
    vi.useFakeTimers();
    render(<FeedThread entryId={4} reactions={[]} comments={[COMMENT]} />);
    fireEvent.click(screen.getByRole('button', { name: '1 comment' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove comment' }));
    expect(toasts.last?.label).toBe('Undo');

    act(() => toasts.last!.run());
    expect(screen.getByText('Nobody deserved it more')).toBeDefined();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(11_000);
    });
    expect(vi.mocked(api)).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  test('posting a comment clears the box', async () => {
    vi.mocked(api).mockResolvedValue({ reactions: [], comments: [COMMENT] } as never);
    render(<FeedThread entryId={4} reactions={[]} comments={[]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Comment' }));
    const box = screen.getByLabelText('Add a comment') as HTMLInputElement;
    fireEvent.change(box, { target: { value: 'Nobody deserved it more' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Post' }));
    });
    expect(box.value).toBe('');
    expect(screen.getByText('Nobody deserved it more')).toBeDefined();
  });
});

describe('who reacted', () => {
  test('reads like a sentence', () => {
    expect(whoReacted(['Ann'])).toBe('Ann');
    expect(whoReacted(['Ann', 'Bob', 'Cat'])).toBe('Ann, Bob and Cat');
    expect(whoReacted(['Ann', 'Bob', 'Cat', 'Dan', 'Eve'])).toBe('Ann, Bob and 3 others');
  });
});
