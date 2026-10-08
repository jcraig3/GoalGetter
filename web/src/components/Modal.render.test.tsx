// @vitest-environment jsdom
/** A dialog asks before throwing away changes — any change, not only typing (P4-14). */
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import Modal from './Modal';

const ask = vi.hoisted(() => vi.fn(async () => false));
vi.mock('../confirm', () => ({ ask }));

test('a dropdown change is a change: closing asks first', async () => {
  const onClose = vi.fn();
  render(
    <Modal title="Edit" onClose={onClose}>
      <select aria-label="Period" defaultValue="month">
        <option value="month">Month</option>
        <option value="week">Week</option>
      </select>
    </Modal>,
  );
  fireEvent.change(screen.getByLabelText('Period'), { target: { value: 'week' } });
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));

  await vi.waitFor(() =>
    expect(ask).toHaveBeenCalledWith('Discard your changes?', expect.objectContaining({ confirmLabel: 'Discard' })),
  );
  expect(onClose).not.toHaveBeenCalled();
});

test('untouched, it closes straight away', async () => {
  const onClose = vi.fn();
  ask.mockClear();
  render(
    <Modal title="Edit" onClose={onClose}>
      <p>Nothing to change</p>
    </Modal>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(ask).not.toHaveBeenCalled();
});

test("a form's own Cancel asks too, once something changed (P5-10)", async () => {
  const onClose = vi.fn();
  const formCancel = vi.fn();
  ask.mockClear();
  ask.mockResolvedValueOnce(true);
  render(
    <Modal title="Edit" onClose={onClose}>
      <input aria-label="Name" />
      <button type="button" onClick={formCancel}>
        Cancel
      </button>
    </Modal>,
  );
  fireEvent.input(screen.getByLabelText('Name'), { target: { value: 'x' } });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

  await vi.waitFor(() =>
    expect(ask).toHaveBeenCalledWith('Discard your changes?', expect.objectContaining({ cancelLabel: 'Keep editing' })),
  );
  await vi.waitFor(() => expect(onClose).toHaveBeenCalled());
  // The form's own handler never ran: the Modal decided.
  expect(formCancel).not.toHaveBeenCalled();
});

test('untouched, a form’s own Cancel just closes', () => {
  const formCancel = vi.fn();
  ask.mockClear();
  render(
    <Modal title="Edit" onClose={() => {}}>
      <button type="button" onClick={formCancel}>
        Cancel
      </button>
    </Modal>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(formCancel).toHaveBeenCalled();
  expect(ask).not.toHaveBeenCalled();
});
