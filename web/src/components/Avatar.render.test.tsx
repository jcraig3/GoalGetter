// @vitest-environment jsdom
/**
 * A face, or initials.
 *
 * The case worth testing is the fallback: initials are the ordinary answer, not
 * an error, and a photo that fails to load must go back to them rather than
 * leaving a broken-image icon on a leaderboard.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import Avatar from './Avatar';

describe('Avatar', () => {
  test('draws initials when there is no photograph', () => {
    render(<Avatar name="Peter Parker" />);

    expect(screen.getByText('PP')).toBeDefined();
    expect(document.querySelector('img')).toBeNull();
  });

  test('builds the signed-in url from the content hash', () => {
    render(<Avatar name="Peter Parker" digest="abc123" />);

    expect(document.querySelector('img')?.getAttribute('src')).toBe(
      '/api/images/abc123',
    );
  });

  test('a ready-made url wins, for a screen with no session', () => {
    render(
      <Avatar
        name="Peter Parker"
        digest="abc123"
        src="/api/display/t/assets/abc123"
      />,
    );

    expect(document.querySelector('img')?.getAttribute('src')).toBe(
      '/api/display/t/assets/abc123',
    );
  });

  test('falls back to initials when the photograph will not load', () => {
    // A broken-image icon on a leaderboard is worse than the letters it
    // replaced.
    render(<Avatar name="Peter Parker" digest="gone" />);

    fireEvent.error(document.querySelector('img')!);

    expect(screen.getByText('PP')).toBeDefined();
    expect(document.querySelector('img')).toBeNull();
  });

  test('is decorative, because the name is always beside it', () => {
    render(<Avatar name="Peter Parker" digest="abc123" />);

    expect(document.querySelector('img')?.getAttribute('aria-hidden')).toBe(
      'true',
    );
    expect(document.querySelector('img')?.getAttribute('alt')).toBe('');
  });
});
