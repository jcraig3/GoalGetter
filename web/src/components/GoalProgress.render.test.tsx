// @vitest-environment jsdom
/** How a goal's progress reads, running and finished (7.2). */
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import GoalProgress, { type GoalLike } from './GoalProgress';

const DAY = 86_400_000;

function goal(overrides: Partial<GoalLike> = {}): GoalLike {
  return {
    metric_name: 'Revenue',
    direction: 'higher_is_better',
    target_value: '250000',
    current_value: '0',
    percent: 0,
    attained: false,
    elapsed_percent: 100,
    expected_percent: 100,
    projected_value: '0',
    status: 'missed',
    unit: 'currency',
    decimal_places: 2,
    unit_label: null,
    period_end: new Date(Date.now() - DAY).toISOString(),
    ...overrides,
  };
}

describe('a finished goal', () => {
  test('says how it finished, not its pace (Q2-13)', () => {
    const { container } = render(<GoalProgress goal={goal()} />);
    expect(container.textContent).toContain('Finished at $0 · missed by $250,000');
    expect(container.textContent).not.toContain('on pace for');
    expect(container.textContent).not.toContain('Period over');
  });

  test('a hit one is not "missed by"', () => {
    const { container } = render(
      <GoalProgress goal={goal({ current_value: '260000', attained: true, status: 'hit', percent: 104 })} />,
    );
    expect(container.textContent).toContain('Finished at $260,000');
    expect(container.textContent).not.toContain('missed by');
  });
});

describe('a running goal', () => {
  test('still says the time left and the pace', () => {
    render(
      <GoalProgress
        goal={goal({
          status: 'behind',
          elapsed_percent: 50,
          expected_percent: 50,
          current_value: '10000',
          projected_value: '20000',
          period_end: new Date(Date.now() + 10 * DAY).toISOString(),
        })}
      />,
    );
    expect(screen.getByText(/days left/)).toBeDefined();
    expect(screen.getByText(/on pace for/)).toBeDefined();
  });
});
