import { expect, test } from 'vitest';

import { handoffMessage } from './handoffWords';

const SAM = { name: 'Sam Rivera', email: 'sam@acme.example' };

test('emailed says so, and offers the link too', () => {
  expect(handoffMessage('invitation', SAM, { emailed: true })).toBe(
    'Invitation emailed to sam@acme.example. The link is here too, if you would rather send it yourself — it works once and expires in 7 days.',
  );
});

test('a failed send says why, and asks for the link to be sent by hand', () => {
  expect(handoffMessage('reset', SAM, { emailed: false, email_detail: 'The mail server refused the sender' })).toBe(
    'Could not email it: The mail server refused the sender. Send Sam Rivera this link yourself — it works once and expires in 2 hours.',
  );
});

test('nowhere to send from is not a failure', () => {
  expect(handoffMessage('invitation', SAM, { emailed: false, email_detail: null })).toBe(
    'Invitation ready for Sam Rivera. Send them this link — it works once and expires in 7 days.',
  );
});

test('a localhost link is called out', () => {
  expect(handoffMessage('invitation', SAM, { emailed: true, link_is_local: true })).toMatch(
    /only opens on this computer/,
  );
});
