// @vitest-environment jsdom
/**
 * A number field that refuses a keystroke says why (QA-6).
 *
 * Typing `-5` or `abc` into a goal's target used to do nothing at all, so the
 * field looked broken rather than strict.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { expect, test } from 'vitest';

import Field, { allowedNumbers } from './Field';

function Target() {
  const [value, setValue] = useState('');
  return (
    <Field
      label="Target"
      value={value}
      onChange={setValue}
      numeric={{ decimals: 4, min: 0 }}
      hint="The number to reach."
    />
  );
}

test('a refused keystroke says what the field takes, instead of vanishing', async () => {
  render(<Target />);

  await userEvent.type(screen.getByLabelText('Target'), '-');

  expect(screen.getByText('A number, 0 or more.')).toBeDefined();
  expect(screen.getByLabelText('Target').getAttribute('aria-invalid')).toBe('true');
});

test('and goes back to the hint once something it takes is typed', async () => {
  render(<Target />);
  const input = screen.getByLabelText('Target');

  await userEvent.type(input, 'a');
  await userEvent.type(input, '5');

  expect(screen.queryByText('A number, 0 or more.')).toBeNull();
  expect(screen.getByText('The number to reach.')).toBeDefined();
  expect((input as HTMLInputElement).value).toBe('5');
});

test('the rule, in words', () => {
  expect(allowedNumbers({ decimals: 0, min: 1, max: 50 })).toBe('Whole number, 1–50.');
  expect(allowedNumbers({ decimals: 2, allowNegative: true })).toBe('A number.');
  expect(allowedNumbers({ decimals: 0 })).toBe('Whole number, 0 or more.');
});
