// @vitest-environment jsdom
/** The deployment's address in Settings (11.7): offered, never guessed in. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';

import WebAddressField, { isLocalAddress } from './WebAddressField';

function draw(props: Partial<Parameters<typeof WebAddressField>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <WebAddressField
      value={null}
      saved={null}
      fallback="http://localhost:8080"
      detected="http://192.168.1.20:8080"
      onChange={onChange}
      {...props}
    />,
  );
  return onChange;
}

test('the address the browser is on is offered in one press', async () => {
  const onChange = draw();
  await userEvent.click(
    screen.getByRole('button', { name: 'Use http://192.168.1.20:8080' }),
  );
  expect(onChange).toHaveBeenCalledWith('http://192.168.1.20:8080');
});

test('nothing is offered when it is already the address', () => {
  draw({ value: 'http://192.168.1.20:8080', saved: 'http://192.168.1.20:8080' });
  expect(screen.queryByRole('button')).toBeNull();
});

test('a localhost address is called out', () => {
  draw();
  expect(screen.getByText(/Only opens on this computer/)).toBeTruthy();
});

test('on localhost, it says how to get an address offered', () => {
  draw({ detected: 'http://localhost:8080' });
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.getByText(/Open GoalGetter by its network address/)).toBeTruthy();
});

test('a plain http address that is not localhost is said to break Microsoft sign-in', () => {
  draw({ value: 'http://172.19.96.1:8080', saved: 'http://172.19.96.1:8080' });
  expect(screen.getByText(/Microsoft sign-in needs https:\/\/ here/)).toBeTruthy();
});

test('https and localhost are both fine for Microsoft', () => {
  draw({ value: 'https://goals.acme.example', saved: 'https://goals.acme.example' });
  expect(screen.queryByText(/Microsoft sign-in needs https/)).toBeNull();
});

test('changing it says the sign-in addresses move too', () => {
  draw({ value: 'https://goals.acme.example', saved: null });
  expect(screen.getByText(/add the new sign-in addresses in Azure/)).toBeTruthy();
});

test('what counts as local', () => {
  expect(isLocalAddress('http://localhost:8080')).toBe(true);
  expect(isLocalAddress('http://127.0.0.1')).toBe(true);
  expect(isLocalAddress('http://192.168.1.20:8080')).toBe(false);
  expect(isLocalAddress('not a url')).toBe(false);
});
