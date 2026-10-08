import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

/**
 * Unmount what a test rendered, before the next one renders.
 *
 * **Testing Library does this itself only when vitest's globals are on**, and
 * they are not here — every other test in this suite imports `expect` and
 * `describe` explicitly. Without it each render is appended to the same
 * document, so a query matches the component under test *and* every copy left
 * behind by the tests before it.
 *
 * That failure is worth naming because it does not look like a leak. It reads as
 * "found multiple elements", which invites the fix of asking for all of them —
 * and then the test passes while asserting against a stale render from two tests
 * ago.
 */
afterEach(cleanup);
