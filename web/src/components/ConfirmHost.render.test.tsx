// @vitest-environment jsdom
/**
 * "Are you sure?" in the app's own dialog, and dialogs that behave.
 *
 * What has to be true: the question keeps its words and names its action,
 * the safe answer has focus, Escape answers no without closing the form
 * underneath, a typed-into form asks before Escape throws it away (QA-24),
 * and closing a dialog puts focus back on the button that opened it.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { expect, test } from 'vitest';

import { ask, reading } from '../confirm';
import ConfirmHost from './ConfirmHost';
import Modal from './Modal';

test('the yes button names the action, and deleting is drawn as a danger', () => {
  expect(reading('Delete "Phoenix" permanently?')).toEqual({
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    danger: true,
  });
  expect(reading('Issue a new address?')).toEqual({
    confirmLabel: 'Continue',
    cancelLabel: 'Cancel',
    danger: false,
  });
});

test('never "Cancel" beside "Cancel" (P3-4)', () => {
  expect(reading('Cancel this competition?')).toEqual({
    confirmLabel: 'Yes, cancel it',
    cancelLabel: 'Keep it',
    danger: true,
  });
});

test('asks in words, with focus on Cancel, and says what was answered', async () => {
  render(<ConfirmHost />);
  let answer: Promise<boolean> = Promise.resolve(false);
  act(() => {
    answer = ask('Remove "Main floor" from this channel?');
  });

  expect(screen.getByRole('alertdialog').textContent).toContain('Remove "Main floor"');
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));

  await userEvent.click(screen.getByRole('button', { name: 'Remove' }));
  await expect(answer).resolves.toBe(true);
  expect(screen.queryByRole('alertdialog')).toBeNull();
});

test('Escape answers no', async () => {
  render(<ConfirmHost />);
  let answer: Promise<boolean> = Promise.resolve(true);
  act(() => {
    answer = ask('Stop emailing "Weekly"?');
  });

  fireEvent.keyDown(window, { key: 'Escape' });

  await expect(answer).resolves.toBe(false);
});

function Opener() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        New goal
      </button>
      {open && (
        // A new arrow every render — the case that used to lose focus.
        <Modal title="New goal" onClose={() => setOpen(false)}>
          <input aria-label="Target" />
        </Modal>
      )}
      <ConfirmHost />
    </>
  );
}

test('closing puts focus back on the button that opened it', async () => {
  render(<Opener />);
  await userEvent.click(screen.getByRole('button', { name: 'New goal' }));

  await userEvent.click(screen.getByRole('button', { name: 'Close' }));

  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'New goal' }));
});

test('Escape on a typed-into form asks first, and its own Escape leaves the form open', async () => {
  render(<Opener />);
  await userEvent.click(screen.getByRole('button', { name: 'New goal' }));
  await userEvent.type(screen.getByLabelText('Target'), '250000');

  fireEvent.keyDown(document, { key: 'Escape' });
  expect(await screen.findByRole('alertdialog')).toBeDefined();

  // No to "discard?" — the form and what was typed are still there.
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
  expect((screen.getByLabelText('Target') as HTMLInputElement).value).toBe('250000');
});

test('an untouched form closes straight away', async () => {
  render(<Opener />);
  await userEvent.click(screen.getByRole('button', { name: 'New goal' }));

  fireEvent.keyDown(document, { key: 'Escape' });

  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.queryByRole('alertdialog')).toBeNull();
});
