/** What a delete does to the TVs, in its confirm (8.6). */
import { expect, test } from 'vitest';

import { usingWords } from './wallUse';

test('names each channel and how many slides go', () => {
  expect(usingWords([])).toBe('');
  expect(usingWords([{ channel_id: 1, channel_name: 'Sales floor', slides: 1 }])).toBe(
    'It also comes off the TVs: removes 1 slide from Sales floor.',
  );
  expect(
    usingWords([
      { channel_id: 1, channel_name: 'Lobby', slides: 2 },
      { channel_id: 2, channel_name: 'Sales floor', slides: 1 },
    ]),
  ).toBe('It also comes off the TVs: removes 2 slides from Lobby and 1 from Sales floor.');
});
