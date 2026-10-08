// @vitest-environment jsdom
/**
 * A board with more rows than fit, on a 1920×1080 stage.
 *
 * What has to be true: it shows as many as fit rather than running off the
 * bottom (QA-3), turns to the rest partway through the slide by the shared
 * clock — so every screen is on the same page — says there is more than one
 * page, and holds still while somebody is standing at it.
 *
 * jsdom does no layout, so the slide's body is given one: 700 pixels tall,
 * with each row taking 100, so seven fit.
 */
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import Board from './Board';
import { WallRotation, type Rotation } from './paging';
import type { Entry } from './types';

function entry(rank: number): Entry {
  return {
    rank,
    entity_id: rank,
    entity_name: `Person ${rank}`,
    team_name: null,
    value: String(1000 - rank),
    movement: null,
  };
}

const ENTRIES = Array.from({ length: 10 }, (_, i) => entry(i + 1));
const START = 1_800_000_000_000;

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(START);
  // A body 700 tall, holding 100 per row it contains.
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.hasAttribute('data-wall-body') ? 700 : 0;
  });
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.querySelectorAll('li').length * 100;
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function wall(rotation: Rotation | null, paged = true) {
  return render(
    <WallRotation.Provider value={rotation}>
      <div data-wall-body="">
        <Board slide={{ entries: ENTRIES, unit: 'count', decimal_places: 0 }} paged={paged} />
      </div>
    </WallRotation.Provider>,
  );
}

const rotation = (paused = false): Rotation => ({
  now: () => Date.now(),
  start: START,
  length: 20_000,
  paused,
});

test('shows no more than fit, shared evenly across the pages', () => {
  // Seven fit, so ten is two pages — of five each, not seven and three.
  wall(rotation());

  expect(screen.getByText('Person 5')).toBeDefined();
  expect(screen.queryByText('Person 6')).toBeNull();
  expect(screen.getByRole('img', { name: 'Page 1 of 2' })).toBeDefined();
});

test('turns to the rest halfway through the slide', async () => {
  wall(rotation());

  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });

  expect(screen.queryByText('Person 5')).toBeNull();
  expect(screen.getByText('Person 6')).toBeDefined();
  expect(screen.getByText('Person 10')).toBeDefined();
  expect(screen.getByRole('img', { name: 'Page 2 of 2' })).toBeDefined();
});

test('a screen that joins late opens on the page the others are showing', () => {
  vi.setSystemTime(START + 15_000);

  wall(rotation());

  expect(screen.getByText('Person 6')).toBeDefined();
});

test('holds its page while somebody is standing at the screen', async () => {
  wall(rotation(true));

  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000);
  });

  expect(screen.getByText('Person 1')).toBeDefined();
});

test('the preview, with no rotation, shows the first page', () => {
  wall(null);

  expect(screen.getByText('Person 1')).toBeDefined();
  expect(screen.queryByText('Person 6')).toBeNull();
});

test('a panel in a comparison never pages', () => {
  wall(rotation(), false);

  expect(screen.getByText('Person 10')).toBeDefined();
  expect(screen.queryByRole('img', { name: /Page/ })).toBeNull();
});
