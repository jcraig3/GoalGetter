// @vitest-environment jsdom
/**
 * Stretch levels: added in the goal form, shown under the progress bar.
 *
 * What has to be true: up to three can be added, an empty one is not sent, a
 * label nobody typed is left to the server's default, and a reached level
 * says so under the bar.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { expect, test } from 'vitest';

import GoalProgress, { type GoalLike } from './GoalProgress';
import StretchFields, { stretchPayload, type StretchDraft } from './StretchFields';

function Harness({ start = [] as StretchDraft[] }) {
  const [levels, setLevels] = useState<StretchDraft[]>(start);
  return (
    <>
      <StretchFields levels={levels} onChange={setLevels} lowerIsBetter={false} />
      <output data-testid="levels">{JSON.stringify(levels)}</output>
    </>
  );
}

test('up to three levels can be added', async () => {
  render(<Harness />);

  for (let i = 0; i < 3; i++) {
    await userEvent.click(screen.getByRole('button', { name: 'Add a stretch level' }));
  }

  expect(screen.getAllByLabelText(/^Level \d$/)).toHaveLength(3);
  expect(screen.queryByRole('button', { name: 'Add a stretch level' })).toBeNull();
});

test('a level can be removed', async () => {
  render(<Harness start={[{ value: '150', label: '' }, { value: '200', label: '' }]} />);

  await userEvent.click(screen.getByRole('button', { name: 'Remove level 1' }));

  expect(JSON.parse(screen.getByTestId('levels').textContent!)).toEqual([{ value: '200', label: '' }]);
});

test('an empty level is not sent, and a blank name is left to the server', () => {
  expect(
    stretchPayload([
      { value: '150', label: ' ' },
      { value: '', label: 'Nothing' },
      { value: '200', label: 'Crushed it' },
    ]),
  ).toEqual([
    { value: '150', label: null },
    { value: '200', label: 'Crushed it' },
  ]);
});

const GOAL: GoalLike = {
  metric_name: 'Calls', direction: 'higher_is_better', target_value: '100', current_value: '160',
  percent: 160, attained: true, elapsed_percent: 40, expected_percent: 40, projected_value: null,
  status: 'hit', unit: 'count', decimal_places: 0,
  stretch: [
    { level: 1, label: 'Stretch', value: '150', reached: true },
    { level: 2, label: 'Crushed it', value: '200', reached: false },
  ],
};

test('a reached level says so under the bar', () => {
  render(<GoalProgress goal={GOAL} />);

  const levels = screen.getByRole('list', { name: 'Stretch levels' });
  expect(levels.textContent).toContain('Stretch');
  expect(levels.textContent).toContain('(reached)');
  expect(screen.getByText(/Crushed it/)).toBeDefined();
});

test('a goal with no levels shows none', () => {
  render(<GoalProgress goal={{ ...GOAL, stretch: [] }} />);

  expect(screen.queryByRole('list', { name: 'Stretch levels' })).toBeNull();
});
