import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig, type BuildOptions } from 'vite';

// Set by the webbuild container.
//
// **Careful running an ad-hoc build in that container.** `BUILD_WATCH` is set on
// the container, not on the command, so `docker compose exec webbuild npx vite
// build --outDir …` silently becomes a *watcher* rather than a one-shot build. One
// of those was left running for a day and a half, rebuilding into a path a
// mistyped `--outDir` had created inside the repo, recreating it within seconds
// every time the directory was deleted. Pass `BUILD_WATCH=false` for a one-shot
// build, or just read the watcher's own output — it is already building.
const watch = process.env.BUILD_WATCH === 'true';

// Docker Desktop does not forward filesystem events from a Windows path into a
// Linux container, so the watcher must poll or it never sees an edit.
//
// The cast is deliberate. Vite 8 builds with rolldown, whose re-exported
// WatcherOptions type does not declare `chokidar` — but it is honored at
// runtime. Measured both ways: with this option an edit is served in ~0.4s;
// without it, edits are never picked up. Remove the cast when the types
// include it.
const watchOptions = {
  chokidar: { usePolling: true, interval: 300 },
} as BuildOptions['watch'];

// In the container this points outside the watched source folder.
//
// Writing the build into ./dist makes the watcher rebuild forever: the build
// output lands inside the folder being watched, which triggers the next build.
// Measured at ~160 idle rebuilds per 30 seconds. Chokidar's `ignored` option
// does not help — rolldown does not honor it — so the output has to physically
// live somewhere the watcher isn't looking.
const outDir = process.env.BUILD_OUT_DIR || 'dist';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir,
    // Required when outDir sits outside the project root, and safe: nothing
    // else lives in that directory.
    emptyOutDir: true,
    sourcemap: true,
    watch: watch ? watchOptions : null,
  },
});
