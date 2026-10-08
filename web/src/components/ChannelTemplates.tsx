import { useEffect, useState } from 'react';

import { api } from '../api';
import { toast } from '../toast';
import Field from './Field';
import Modal from './Modal';
import {
  CHANNEL_TEMPLATES,
  describeSlides,
  type ChannelTemplate,
  type Eligible,
  type ScreenDraft,
} from '../pages/starterTemplates';

/** A name not already taken: "Sales floor", then "Sales floor 2". */
export function freeName(name: string, taken: string[]): string {
  const used = new Set(taken.map((t) => t.trim().toLowerCase()));
  if (!used.has(name.toLowerCase())) return name;
  let n = 2;
  while (used.has(`${name} ${n}`.toLowerCase())) n += 1;
  return `${name} ${n}`;
}

/** A slide as the confirm step lists it: "Deals board", "Recent wins". */
export function slideLabel(slide: ScreenDraft, eligible: Eligible): string {
  if (slide.kind === 'leaderboard') {
    const name = eligible.leaderboards.find((b) => b.id === slide.leaderboard_id)?.name ?? 'A board';
    return slide.appearance?.ranked_layout === 'podium' ? `${name}, as a podium` : name;
  }
  if (slide.kind === 'competition') {
    return eligible.competitions.find((c) => c.id === slide.competition_id)?.name ?? 'A competition';
  }
  return slide.title ?? 'Recent wins';
}

/**
 * A channel started from a template (6.4): made, filled, and opened in its
 * editor.
 *
 * **Confirmed first** (7.9). It used to make the channel on the click, with
 * no name and no word of what would go in it — and a second click made a
 * second "Sales floor". Now the click opens one step: the name, the slides it
 * will add, and Create.
 *
 * **The slides come from what a channel for everyone may show**, asked of the
 * server — the same rule the editor's pickers use — so a template never adds
 * something a save would refuse. The editor it opens previews every slide
 * with real numbers (5j), and anything can be changed there; nothing reaches a
 * TV until one is pointed at it.
 */
export default function ChannelTemplates({
  onClose,
  onMade,
}: {
  onClose: () => void;
  /** Told the new channel's id once its slides are in. */
  onMade: (channelId: number) => void;
}) {
  const [eligible, setEligible] = useState<Eligible | null>(null);
  const [taken, setTaken] = useState<string[]>([]);
  const [chosen, setChosen] = useState<ChannelTemplate | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Eligible>('/api/channels/eligible')
      .then(setEligible)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load what a channel can show.'));
    api<{ name: string }[]>('/api/channels')
      .then((all) => setTaken(all.map((c) => c.name)))
      .catch(() => setTaken([]));
  }, []);

  function choose(template: ChannelTemplate) {
    setChosen(template);
    setName(freeName(template.name, taken));
    setError(null);
  }

  const slides = chosen && eligible ? chosen.slides(eligible) : [];

  async function make() {
    if (!chosen || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const channel = await api<{ id: number }>('/api/channels', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim() }),
      });
      for (const slide of slides) {
        await api(`/api/channels/${channel.id}/screens`, {
          method: 'POST',
          body: JSON.stringify(slide),
        });
      }
      toast(`“${name.trim()}” made with ${describeSlides(slides)}`);
      onMade(channel.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not make that channel.');
      setBusy(false);
    }
  }

  return (
    <Modal
      title={chosen ? `New channel: ${chosen.name}` : 'Start from a template'}
      description={
        chosen
          ? 'Check the name and what goes in it. Everything can be changed in its editor afterwards, where each slide is previewed.'
          : 'A channel with its slides already in, from what you have now.'
      }
      onClose={onClose}
    >
      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {!chosen && (
        <ul className="space-y-2">
          {CHANNEL_TEMPLATES.map((t) => (
            <li key={t.key}>
              <button
                type="button"
                onClick={() => choose(t)}
                className="w-full rounded-lg border border-edge px-4 py-3 text-left transition-colors hover:border-brand hover:bg-surface-hover"
              >
                <span className="block text-content">{t.name}</span>
                <span className="mt-0.5 block text-sm text-content-muted">{t.blurb}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {chosen && (
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void make();
          }}
        >
          <Field
            label="Name"
            value={name}
            onChange={setName}
            hint={
              name !== chosen.name && taken.some((t) => t.toLowerCase() === chosen.name.toLowerCase())
                ? `You already have a channel called “${chosen.name}”.`
                : undefined
            }
          />
          <h3 className="mt-5 text-sm text-content-muted">
            {eligible === null ? 'Working out its slides…' : `It will have ${slides.length} ${slides.length === 1 ? 'slide' : 'slides'}`}
          </h3>
          {eligible !== null && (
            <ol className="mt-2 divide-y divide-edge rounded-md border border-edge text-sm">
              {slides.map((slide, i) => (
                <li key={i} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="w-5 shrink-0 text-right tabular-nums text-content-subtle">{i + 1}</span>
                  <span className="text-content">{slideLabel(slide, eligible)}</span>
                  <span className="ml-auto text-xs text-content-subtle">
                    {slide.kind === 'leaderboard' ? 'Board' : slide.kind === 'competition' ? 'Competition' : 'Wins'}
                  </span>
                </li>
              ))}
            </ol>
          )}
          <div className="mt-6 flex items-center gap-3">
            <button
              type="submit"
              disabled={busy || eligible === null || !name.trim()}
              className="rounded-md bg-brand px-4 py-2 text-white disabled:opacity-50"
            >
              {busy ? 'Creating…' : 'Create channel'}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setChosen(null)}
              className="rounded-md border border-edge px-4 py-2 text-content hover:bg-surface-hover"
            >
              Back
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
