/** The staff photo upload's own logic: file kinds, junk, and which photo won. */
import { expect, test } from 'vitest';

import { isJunk, kindOf, markReplaced, type PhotoRow } from './staffPhotos';

test('a file is a zip, a picture or neither — by type, then by name', () => {
  expect(kindOf({ name: 'headshots.zip', type: 'application/x-zip-compressed' })).toBe('zip');
  expect(kindOf({ name: 'headshots.ZIP', type: '' })).toBe('zip');
  expect(kindOf({ name: 'pparker.jpg', type: 'image/jpeg' })).toBe('image');
  expect(kindOf({ name: 'pparker.WEBP', type: '' })).toBe('image');
  expect(kindOf({ name: 'notes.txt', type: 'text/plain' })).toBe('other');
});

test('what an operating system leaves in a folder is skipped', () => {
  expect(isJunk('.DS_Store')).toBe(true);
  expect(isJunk('__MACOSX/._pparker.jpg')).toBe(true);
  expect(isJunk('Thumbs.db')).toBe(true);
  expect(isJunk('pparker.jpg')).toBe(false);
});

test('two photos for one person: the later wins, and the earlier says so', () => {
  const rows: PhotoRow[] = [
    { key: '1', filename: 'pparker.jpg', status: 'matched', detail: 'Photo set.', user_id: 7 },
    { key: '2', filename: 'mjwatson.jpg', status: 'matched', detail: 'Photo set.', user_id: 8 },
    { key: '3', filename: 'peter.parker.png', status: 'matched', detail: 'Photo set.', user_id: 7 },
  ];
  const marked = markReplaced(rows);
  expect(marked[0]!.detail).toBe('Replaced by peter.parker.png, which came later.');
  expect(marked[1]!.detail).toBe('Photo set.');
  expect(marked[2]!.detail).toBe('Photo set.');
});
