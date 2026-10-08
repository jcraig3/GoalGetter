import { SpeakerIcon, SpeakerOffIcon } from '../icons';

/**
 * Whether a TV is playing sound, at a glance (Phase 24).
 *
 * A small speaker in the corner while something with sound is on the screen,
 * crossed out while the browser is holding this tab's sound back. **Never a
 * prompt** (asked for): nobody stands at a TV, and how to allow its sound is
 * on TVs & Channels, which also hears from each screen when it is off.
 */
export default function SoundBadge({ allowed, sounding }: { allowed: boolean | null; sounding: boolean }) {
  if (!sounding || allowed === null) return null;
  return (
    <div
      role="status"
      aria-label={allowed ? 'Sound on' : 'Sound off'}
      className="pointer-events-none fixed bottom-6 right-6 z-[60] rounded-full bg-black/50 p-2 text-white/90"
    >
      {allowed ? <SpeakerIcon className="size-6" /> : <SpeakerOffIcon className="size-6" />}
    </div>
  );
}
