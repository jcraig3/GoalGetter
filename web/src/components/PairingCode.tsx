import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api';

/**
 * A pairing code on a television, and the wait for somebody to claim it.
 *
 * **The whole point is that nothing here is typed.** Four characters go from
 * the screen to a laptop, read by eye; everything else happens there.
 *
 * Shown in two places: a new screen opening `/pair` (`PairScreen`), and a
 * screen whose link has stopped working — revoked, or deleted from the list —
 * which used to say "Display disconnected" and wait for somebody with a
 * ladder and a keyboard (6.1). Now it offers a code, and an admin connects it
 * again from their desk.
 *
 * Runs unattended like the wall itself, so it obeys the same rules: never show
 * an error to a room, and recover without anybody pressing anything. A code
 * that lapses is replaced rather than left on screen looking valid.
 */
interface Started {
  code: string;
  secret: string;
  expires_in_seconds: number;
}

/** How often to ask whether somebody has claimed us. */
const POLL_MS = 3000;

export default function PairingCode({
  heading = 'To finish setting this screen up',
  previousToken,
  onPaired,
}: {
  /** The line over the code: what this screen is waiting for. */
  heading?: string;
  /**
   * The link a disconnected screen used to have, sent with the request so
   * the code is tied to that display and the admin inbox can name it and
   * reconnect it in one press (6.2). It unlocks nothing: the link stays dead.
   */
  previousToken?: string;
  /** Told the screen's new address once an admin has claimed the code. */
  onPaired: (url: string) => void;
}) {
  const [code, setCode] = useState<string | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const secret = useRef<string | null>(null);
  const paired = useRef(onPaired);
  paired.current = onPaired;

  const ask = useCallback(async () => {
    setBusy(true);
    try {
      const started = await api<Started>('/api/displays/pair/start', {
        method: 'POST',
        ...(previousToken ? { body: JSON.stringify({ previous_token: previousToken }) } : {}),
      });
      secret.current = started.secret;
      setCode(started.code);
      setSecondsLeft(started.expires_in_seconds);
    } catch {
      // A screen that cannot reach the server keeps the code it has and tries
      // again on the next tick. Error text on a wall helps nobody.
    } finally {
      setBusy(false);
    }
  }, [previousToken]);

  useEffect(() => {
    void ask();
  }, [ask]);

  // Count down, and ask for a fresh code when this one lapses. A screen left
  // on overnight shows a working code in the morning rather than a dead one.
  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft]);

  useEffect(() => {
    if (code && secondsLeft === 0 && !busy) void ask();
  }, [code, secondsLeft, busy, ask]);

  // Ask whether anybody has claimed us yet.
  useEffect(() => {
    const timer = setInterval(() => {
      const held = secret.current;
      if (!held) return;
      void (async () => {
        try {
          const found = await api<{ url: string }>(`/api/displays/pair/${held}`);
          if (found?.url) paired.current(found.url);
        } catch {
          // 204 while waiting, 404 once expired — the countdown above deals
          // with the second, and neither is worth saying to a room.
        }
      })();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    // The wall's own scope, so this looks like the screens it is about to
    // become rather than like a page of the app.
    <div className="wall flex min-h-screen flex-col items-center justify-center bg-bg px-10 py-8 text-center">
      <p className="text-wall-3xl text-content-muted">{heading}</p>

      <p className="mt-10 font-mono text-wall-8xl font-semibold tracking-[0.2em] text-content">
        {code ?? '····'}
      </p>

      <p className="mt-10 max-w-4xl text-wall-2xl text-content-muted">
        In GoalGetter, go to <strong className="text-content">TVs &amp; Channels</strong>{' '}
        → <strong className="text-content">Connect a TV</strong> and enter this
        code.
      </p>

      {code && (
        <p className="mt-6 text-wall-xl text-content-subtle">
          {/* Said, because a code that changes while somebody is walking to a
              laptop looks like a fault rather than a timeout. */}
          The code changes every few minutes. If it has moved on, use whatever
          is on screen.
        </p>
      )}
    </div>
  );
}
