// @vitest-environment jsdom
/**
 * Writing what a wall says.
 *
 * **The preview is the point of the control.** A merge tag is the one kind of
 * text where what you type is not what anybody reads, so the version with the
 * names filled in has to be on screen while you write it — otherwise the first
 * proofread happens on a television.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import MessageField from './MessageField';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const TAGS = [
  { name: 'name', describes: 'Who did it', example: 'Peter Parker' },
  { name: 'value', describes: 'The figure', example: '$6,200' },
];

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(TAGS as never);
});

function draw(value = '') {
  const onChange = vi.fn();
  render(
    <MessageField value={value} onChange={onChange} fallback="Peter — $6,200" />,
  );
  return onChange;
}

describe('MessageField', () => {
  test('offers the tags the server says exist', async () => {
    // Served rather than listed here, so the picker and the validation cannot
    // disagree — the quiet version of that is a picker offering a tag the
    // server refuses.
    draw();

    expect(await screen.findByText('{name}')).toBeDefined();
    expect(screen.getByText('{value}')).toBeDefined();
  });

  test('fills the tags in, so the preview is what a room reads', async () => {
    draw('{name} just closed {value}');

    await waitFor(() =>
      expect(screen.getByText('Peter Parker just closed $6,200')).toBeDefined(),
    );
  });

  test('leaves an unknown tag visible in the preview', async () => {
    // The same thing the server does, and it is what makes a typo findable.
    draw('{name} of {squad}');

    await waitFor(() =>
      expect(screen.getByText('Peter Parker of {squad}')).toBeDefined(),
    );
  });

  test('shows each alternative separately', async () => {
    draw('{name} did it\n{name} again');

    await waitFor(() =>
      expect(screen.getByText(/one of these 2/)).toBeDefined(),
    );
    expect(screen.getByText('Peter Parker did it')).toBeDefined();
    expect(screen.getByText('Peter Parker again')).toBeDefined();
  });

  test('no preview at all when nothing is written', () => {
    // An empty box has nothing to preview, and an empty panel under it would
    // read as a preview of nothing rather than as no preview.
    draw('');

    expect(screen.queryByText(/On a wall/)).toBeNull();
  });

  test('says what the wall falls back to', () => {
    draw('');

    expect(screen.getByText(/Peter — \$6,200/)).toBeDefined();
  });

  test('a tag button appends when nothing is focused', async () => {
    const onChange = draw('Well done ');

    fireEvent.click(await screen.findByText('{name}'));

    expect(onChange).toHaveBeenCalledWith('Well done {name}');
  });

  test('survives the tag list never arriving', () => {
    // A failed fetch must not stop somebody writing a message; the preview is
    // an aid, not the task.
    vi.mocked(api).mockRejectedValue(new Error('offline'));

    expect(() => draw('{name} did it')).not.toThrow();
  });
});
