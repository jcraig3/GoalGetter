// @vitest-environment jsdom
/**
 * Company branding, where the company's other details are.
 *
 * **The property worth protecting is that editing the brand does not erase the
 * wall.** Both live in one `appearance` object and the PATCH replaces it
 * wholesale, so a Settings page that sent only its own fields would wipe every
 * layout, background and type choice the moment somebody changed a colour.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';

import BrandFields from './BrandFields';
import type { Appearance } from '../appearance';

const RESOLVED = {
  logo: null,
  slogan: null,
  primary: '#6366f1',
  secondary: '#818cf8',
  accent: '#34d399',
  font: 'system',
  font_scale: 1,
  panel_opacity: 0.72,
  panel_blur: 12,
  panel_radius: 16,
  ranked_layout: 'list',
  goal_layout: 'gauge',
  row_count: 10,
  show_values: true,
  name_display: 'full',
  end_time_format: 'default',
  milestones: 'all',
  background: null,
} as Appearance;

function draw(chosen: Record<string, unknown> = {}) {
  const onChange = vi.fn();
  render(
    <BrandFields chosen={chosen} resolved={RESOLVED} onChange={onChange} />,
  );
  return onChange;
}

describe('BrandFields', () => {
  test('shows the built-in colour until somebody chooses one', () => {
    draw();

    expect(
      (screen.getByLabelText('Primary') as HTMLInputElement).value,
    ).toBe('#6366f1');
  });

  test('shows the chosen one once they have', () => {
    draw({ primary: '#ff0000' });

    expect(
      (screen.getByLabelText('Primary') as HTMLInputElement).value,
    ).toBe('#ff0000');
  });

  test('sends only the field that changed', () => {
    // The caller merges. Sending a whole appearance from here would make this
    // component responsible for not erasing the wall, which is not its job.
    const onChange = draw();

    fireEvent.change(screen.getByLabelText('Primary'), {
      target: { value: '#ff0000' },
    });

    expect(onChange).toHaveBeenCalledWith({ primary: '#ff0000' });
  });

  test('a hex can be typed as well as picked', () => {
    // A brand colour arrives as a hex code in an email from a designer.
    const onChange = draw();

    fireEvent.change(screen.getByLabelText('Primary hex'), {
      target: { value: '#123456' },
    });

    expect(onChange).toHaveBeenCalledWith({ primary: '#123456' });
  });

  test('no reset offered until something is set', () => {
    // A reset on a value nobody chose is a button that does nothing and
    // invites the question of what it would have done.
    draw();

    expect(screen.queryByText('Use the default colours')).toBeNull();
  });

  test('resetting removes the keys rather than writing the defaults back', () => {
    // Writing #6366f1 in would pin this deployment to today's built-in, so a
    // later change to it would stop reaching anybody who pressed reset.
    const onChange = draw({ primary: '#ff0000' });

    fireEvent.click(screen.getByText('Use the default colours'));

    expect(onChange).toHaveBeenCalledWith({
      primary: undefined,
      secondary: undefined,
      accent: undefined,
    });
  });

  test('an emptied slogan clears rather than storing an empty string', () => {
    const onChange = draw({ slogan: 'Always be closing' });

    fireEvent.change(screen.getByLabelText('Slogan'), {
      target: { value: '' },
    });

    expect(onChange).toHaveBeenCalledWith({ slogan: null });
  });

  test('offers one logo, for light and dark alike', () => {
    draw();

    expect(screen.getByText('Logo')).toBeDefined();
    expect(screen.queryByText(/dark backgrounds/)).toBeNull();
  });
});
