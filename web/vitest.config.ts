import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Test config, separate from `vite.config.ts`.
 *
 * **Its own file because the build config is not about tests.** `vite.config.ts`
 * carries the watcher polling, the rolldown cast and the container's output
 * path — none of which a test run wants, and all of which would have to be read
 * around by anybody changing how tests work.
 *
 * `environment` is per-file rather than global: the pure-function tests that make
 * up most of this suite run measurably faster without a DOM, and switching them
 * all to jsdom to accommodate a handful of render tests would be paying for a
 * browser in nine hundred places to use it in ten. A render test opts in with
 * `// @vitest-environment jsdom` at the top of the file.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'node',
    restoreMocks: true,
    // Unmounts each render. Testing Library only registers this itself when
    // vitest globals are on; see the file for why that matters.
    setupFiles: ['./src/test-setup.ts'],
  },
});
