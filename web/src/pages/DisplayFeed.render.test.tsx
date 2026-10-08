// @vitest-environment jsdom
/**
 * The keys a person uses when they are standing at the wall.
 *
 * A wall runs unattended for months and then, twice a year, somebody is at it
 * with a keyboard: setting it up, showing it to a visitor, or trying to read
 * the board that just went past. Every one of those is "hold this" or "go back
 * one", and both are impossible on a screen that only moves on its own.
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import DisplayFeed from './DisplayFeed';

const takeover = vi.hoisted(() => ({
  onRefused: undefined as undefined | ((e: Error & { status: number }) => void),
}));

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {
    constructor(
      readonly status: number,
      message: string,
    ) {
      super(message);
    }
  },
}));
vi.mock('../components/CelebrationTakeover', () => ({
  default: (props: { onRefused?: (e: Error & { status: number }) => void }) => {
    takeover.onRefused = props.onRefused;
    return null;
  },
}));

const { api, ApiError } = await import('../api');

function slide(id: number, title: string) {
  return {
    id,
    kind: 'message',
    dwell_seconds: 20,
    title,
    subtitle: null,
    entries: [],
    total_entrants: 0,
    entity_type: null,
    unit: null,
    decimal_places: 0,
    direction: null,
    current_value: null,
    target_value: null,
    percent: null,
    status: null,
    prize: null,
    ends_at: null,
    state: null,
    final: false,
    achievements: [],
    person: null,
    stats: [],
    streak_days: null,
    panels: [],
    url: null,
    media_kind: null,
    body: `Body ${id}`,
    appearance: {},
  };
}

const CHANNEL = {
  channel_name: 'Main floor',
  organization_name: 'Acme',
  refresh_seconds: 60,
  slides: [slide(1, 'First'), slide(2, 'Second'), slide(3, 'Third')],
};

/**
 * The start of a rotation cycle: three slides of twenty seconds is a minute,
 * so any whole minute is a moment when the first slide is showing on every
 * screen on the channel. Since 4k a wall shows what the shared clock says
 * rather than always opening on slide one, so the tests pin the clock here.
 */
const CYCLE_START = 1_800_000_000_000 - (1_800_000_000_000 % 60_000);

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(CYCLE_START);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(CHANNEL as never);
});

afterEach(() => vi.useRealTimers());

async function wall() {
  render(
    <MemoryRouter initialEntries={['/display/t']}>
      <Routes>
        <Route path="/display/:token" element={<DisplayFeed />} />
      </Routes>
    </MemoryRouter>,
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

const press = (key: string) =>
  act(() => void fireEvent.keyDown(window, { key }));

describe('a wall that somebody is standing at', () => {
  test('rotates on its own', async () => {
    await wall();
    expect(screen.getByText('First')).toBeDefined();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(screen.getByText('Second')).toBeDefined();
  });

  test('space holds it where it is', async () => {
    await wall();

    press(' ');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(screen.getByText('First')).toBeDefined();
  });

  test('and says so, because a stopped rotation looks like a broken one', async () => {
    await wall();

    press(' ');

    expect(screen.getByText('Paused')).toBeDefined();
  });

  test('space again lets it go', async () => {
    await wall();
    press(' ');
    press(' ');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    expect(screen.getByText('Second')).toBeDefined();
  });

  test('the right arrow steps forward', async () => {
    await wall();

    press('ArrowRight');

    expect(screen.getByText('Second')).toBeDefined();
  });

  test('the left arrow steps back, which is the one the clock cannot do', async () => {
    await wall();
    press('ArrowRight');
    press('ArrowRight');

    press('ArrowLeft');

    expect(screen.getByText('Second')).toBeDefined();
  });

  test('stepping back from the first slide wraps to the last', async () => {
    // Rather than sticking, which reads as a key that stopped working.
    await wall();

    press('ArrowLeft');

    expect(screen.getByText('Third')).toBeDefined();
  });

  test('stepping by hand pauses too', async () => {
    // Somebody stepping forward wants to look at what they landed on, not
    // watch it leave.
    await wall();

    press('ArrowRight');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(screen.getByText('Second')).toBeDefined();
  });

  test('nothing is documented on the screen', async () => {
    // A wall with a legend of shortcuts along the bottom has one for ever,
    // read by four hundred people who will never press a key.
    await wall();

    expect(screen.queryByText(/space/i)).toBeNull();
    expect(screen.queryByText(/arrow/i)).toBeNull();
  });
});

describe('every screen on a channel, in step', () => {
  test('a wall opened part-way through shows what the others are showing', async () => {
    // **The bug this was built for.** Two tabs of one wall rotated at
    // different moments, because each counted from when it loaded. Opened 25
    // seconds into the cycle, a wall joins on the second slide — where every
    // other screen is — rather than starting over on the first.
    vi.setSystemTime(CYCLE_START + 25_000);
    await wall();

    expect(screen.getByText('Second')).toBeDefined();
  });

  test('it changes slide when the others do, not a full dwell after it opened', async () => {
    vi.setSystemTime(CYCLE_START + 25_000);
    await wall();

    // Fifteen seconds left on the second slide, not twenty.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });

    expect(screen.getByText('Third')).toBeDefined();
  });

  test('it goes by the server’s clock, not its own', async () => {
    // A television's own clock is routinely seconds out. This one thinks it
    // is the start of the cycle; the server says it is 45 seconds in.
    vi.mocked(api).mockResolvedValue({
      ...CHANNEL,
      server_time: CYCLE_START + 45_000,
    } as never);
    await wall();

    // The first answer sets the clock; the next boundary is when it shows.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByText('Third')).toBeDefined();
  });

  test('letting go of a paused screen puts it back in step', async () => {
    // Somebody standing at it wins, for as long as they hold it. Letting go
    // returns it to where the rest of the room is, not to where it was left.
    await wall();
    press(' ');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(45_000);
    });
    expect(screen.getByText('First')).toBeDefined();

    press(' ');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByText('Third')).toBeDefined();
  });
});

describe('a screen that has been refused (QA-15)', () => {
  test('a revoked link says so on its next poll', async () => {
    await wall();
    vi.mocked(api).mockRejectedValue(new ApiError(404, 'Not found'));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(62_000);
    });

    // Offering a code to connect it again, not just a dead end (6.1).
    expect(screen.getByText(/This screen was disconnected/)).toBeDefined();
  });

  test('and says so within seconds when the celebrations feed hears first', async () => {
    // That one asks every three seconds; the channel only once a minute, which
    // is how a revoked screen played on for a minute and a half.
    await wall();
    expect(screen.getByText('First')).toBeDefined();

    act(() => takeover.onRefused?.(new ApiError(404, 'Not found')));

    // Offering a code to connect it again, not just a dead end (6.1).
    expect(screen.getByText(/This screen was disconnected/)).toBeDefined();
  });

  test('the wrong network takes the board off the screen and gives the reason', async () => {
    await wall();
    const reason = 'This screen is outside the network allowed for this channel.';
    vi.mocked(api).mockRejectedValue(new ApiError(403, reason));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(62_000);
    });

    expect(screen.getByText(reason)).toBeDefined();
    expect(screen.queryByText('First')).toBeNull();
  });

  test('and comes back when the network is allowed again', async () => {
    await wall();
    vi.mocked(api).mockRejectedValueOnce(new ApiError(403, 'Not here.'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(62_000);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(62_000);
    });

    expect(screen.queryByText('Not here.')).toBeNull();
  });
});

describe('night mode and nothing scheduled (6.10)', () => {
  test('a quiet wall shows the clock in the office time, not the slides', async () => {
    vi.mocked(api).mockResolvedValue({
      ...CHANNEL,
      slides: [],
      quiet: { mode: 'clock', until: null },
      time_zone: 'Asia/Tokyo',
    } as never);
    await wall();

    const quiet = screen.getByTestId('quiet-screen');
    expect(quiet.dataset.mode).toBe('clock');
    const tokyo = new Intl.DateTimeFormat(undefined, {
      hour: 'numeric',
      minute: '2-digit',
      timeZone: 'Asia/Tokyo',
    }).format(CYCLE_START);
    expect(screen.getByText(tokyo)).toBeDefined();
    expect(screen.queryByText('First')).toBeNull();
  });

  test('and goes back to the rotation when the quiet ends', async () => {
    vi.mocked(api).mockResolvedValueOnce({
      ...CHANNEL,
      slides: [],
      quiet: { mode: 'dark', until: '2027-01-15T07:00:00-05:00' },
    } as never);
    await wall();
    expect(screen.getByTestId('quiet-screen').dataset.mode).toBe('dark');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(62_000);
    });

    expect(screen.queryByTestId('quiet-screen')).toBeNull();
    expect(screen.getByText(/First|Second|Third/)).toBeDefined();
  });

  test('a channel with no slides at all still says it is empty', async () => {
    vi.mocked(api).mockResolvedValue({ ...CHANNEL, slides: [] } as never);
    await wall();
    expect(screen.getByText('Nothing on this channel yet.')).toBeDefined();
  });
});
