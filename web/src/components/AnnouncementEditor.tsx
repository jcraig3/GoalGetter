import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';

import { api, ApiError } from '../api';
import type { Background } from '../appearance';
import type { Celebration } from '../pages/celebrationQueue';
import AnnouncementScreen from './AnnouncementScreen';
import BackgroundFields from './BackgroundFields';
import CelebrationPreview from './CelebrationPreview';
import Field from './Field';
import MediaField from './MediaField';
import Modal from './Modal';
import PreviewOnTv from './PreviewOnTv';
import { sessionImageUrl } from './wall/types';

export interface Announcement {
  id: number;
  title: string;
  body: string | null;
  hold_seconds: number;
  background: Background | null;
  media_url: string | null;
  media_kind: string | null;
  media_start_seconds: number | null;
  sound_url: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
  times_sent: number;
  last_sent_at: string | null;
}

/**
 * Making or changing an announcement for the TVs (Phase 25).
 *
 * The words, the screen behind them, something for the middle, a sound effect
 * — and beside it all, the announcement itself, drawn exactly as a TV will
 * draw it and kept up to date as it is typed. Silent while editing; **Play
 * it** shows it full-screen, with sound.
 */
export default function AnnouncementEditor({
  editing,
  onSaved,
  onClose,
}: {
  editing: Announcement | null;
  onSaved: (saved: Announcement, sendNow: boolean) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(editing?.title ?? '');
  const [body, setBody] = useState(editing?.body ?? '');
  const [hold, setHold] = useState(String(editing?.hold_seconds ?? 15));
  const [background, setBackground] = useState<Background | null>(editing?.background ?? null);
  const [media, setMedia] = useState(editing?.media_url ?? '');
  const [start, setStart] = useState(editing?.media_start_seconds ? String(editing.media_start_seconds) : '');
  const [sound, setSound] = useState(editing?.sound_url ?? '');
  const [shown, setShown] = useState<Celebration | null>(null);
  const [playing, setPlaying] = useState<Celebration | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const payload = {
    title: title.trim(),
    body: body.trim() || null,
    hold_seconds: Math.min(120, Math.max(5, Number(hold) || 15)),
    background: background && background.kind && background.kind !== 'none' ? background : null,
    media_url: media.trim() || null,
    media_start_seconds: start ? Number(start) : null,
    sound_url: sound || null,
  };
  const key = JSON.stringify(payload);

  // **Drawn as a TV will draw it**, asked of the server a moment after
  // typing stops — so what is checked there (a link, a library file) is
  // checked here too.
  useEffect(() => {
    if (!payload.title) {
      setShown(null);
      return;
    }
    const timer = setTimeout(() => {
      api<Celebration>('/api/tv-announcements/preview', { method: 'POST', body: key })
        .then((found) => {
          setShown(found);
          setProblem(null);
        })
        .catch((error) => {
          // Not the last good one: a stale preview looked like the change
          // (a new background, say) didn't work.
          setShown(null);
          setProblem(error instanceof ApiError ? error.message : 'Couldn’t draw that.');
        });
    }, 400);
    return () => clearTimeout(timer);
    // `key` is the payload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  async function save(sendNow: boolean) {
    setBusy(true);
    setProblem(null);
    try {
      const saved = await api<Announcement>(editing ? `/api/tv-announcements/${editing.id}` : '/api/tv-announcements', {
        method: editing ? 'PATCH' : 'POST',
        body: key,
      });
      onSaved(saved, sendNow);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : 'Couldn’t save that.');
      setBusy(false);
    }
  }

  const middleIsVideo = /^(video:|https?:\/\/(www\.|m\.)?(youtube\.com|youtu\.be)\/)/.test(media.trim());

  return (
    <Modal
      title={editing ? 'Edit announcement' : 'New announcement'}
      onClose={onClose}
      wide
      side={<Preview shown={shown} onPlay={() => shown && setPlaying({ ...shown, id: `play:${Date.now()}` })} />}
    >
      <div className="space-y-5">
        <Field label="Headline" value={title} onChange={setTitle} maxLength={120} placeholder="Lunch is here" />
        <Field
          label="More (optional)"
          value={body}
          onChange={setBody}
          maxLength={500}
          required={false}
          placeholder="In the kitchen, help yourselves"
        />
        <Field
          label="Seconds on screen"
          value={hold}
          onChange={setHold}
          numeric={{ decimals: 0, min: 5, max: 120 }}
          hint="Between 5 and 120"
        />

        <Section title="Behind the words">
          <BackgroundFields value={background} onChange={setBackground} />
          {background?.kind === 'youtube' && (
            <p className="text-xs text-content-subtle">The video fills the screen, with the words on top.</p>
          )}
        </Section>

        <Section title="In the middle (optional)">
          <MediaField
            label="A video or a picture"
            value={media}
            onChange={setMedia}
            kinds={['video', 'image']}
            link="Or paste a YouTube link, or a link to a picture"
          />
          {middleIsVideo && (
            <Field
              label="Start at (seconds)"
              value={start}
              onChange={setStart}
              numeric={{ decimals: 0, min: 0 }}
              required={false}
            />
          )}
        </Section>

        <Section title="Sound effect (optional)">
          <MediaField
            label="Plays first; a video’s own sound comes in after it"
            value={sound}
            onChange={setSound}
            kinds={['audio']}
          />
        </Section>

        {/* Below the form on a narrow screen, where `side` isn't shown. */}
        <div className="lg:hidden">
          <Preview shown={shown} onPlay={() => shown && setPlaying({ ...shown, id: `play:${Date.now()}` })} />
        </div>

        {problem && <p className="text-sm text-danger">{problem}</p>}

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void save(true)}
            disabled={busy || !payload.title}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            Save and send…
          </button>
          <button
            type="button"
            onClick={() => void save(false)}
            disabled={busy || !payload.title}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            Save
          </button>
          <div className="ml-auto">
            <PreviewOnTv
              disabled={!payload.title}
              send={(displayId) =>
                api(`/api/tv-announcements/preview/tv/${displayId}`, { method: 'POST', body: key })
              }
            />
          </div>
        </div>
      </div>

      {playing && <CelebrationPreview celebration={playing} label="Announcement preview" onClose={() => setPlaying(null)} />}
    </Modal>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-3 border-t border-edge pt-4">
      <legend className="pr-2 text-sm font-medium text-content">{title}</legend>
      {children}
    </fieldset>
  );
}

/** The announcement at TV size, scaled into the space there is. */
function Preview({ shown, onPlay }: { shown: Celebration | null; onPlay: () => void }) {
  return (
    <div className="space-y-2">
      <ScaledScreen>
        {shown ? (
          <AnnouncementScreen celebration={shown} fileUrl={sessionImageUrl} quiet />
        ) : (
          <div className="flex size-full items-center justify-center bg-bg text-4xl text-content-subtle">
            Your announcement
          </div>
        )}
      </ScaledScreen>
      <button
        type="button"
        onClick={onPlay}
        disabled={!shown}
        className="text-sm text-brand hover:underline disabled:opacity-50"
      >
        Play it, with sound
      </button>
    </div>
  );
}

const SCREEN_WIDTH = 1920;
const SCREEN_HEIGHT = 1080;

/**
 * A 1920×1080 screen drawn small. **The transform is what holds it**: a
 * transformed box contains its `position: fixed` children, so the very
 * component a TV fills the screen with fills this instead.
 */
function ScaledScreen({ children }: { children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.25);
  useLayoutEffect(() => {
    const node = box.current;
    if (!node) return;
    const measure = () => setScale(node.clientWidth / SCREEN_WIDTH);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={box} className="relative w-full overflow-hidden rounded-lg border border-edge" style={{ aspectRatio: '16 / 9' }}>
      <div
        style={{ width: SCREEN_WIDTH, height: SCREEN_HEIGHT, transform: `scale(${scale})`, transformOrigin: 'top left' }}
        className="absolute left-0 top-0"
      >
        {children}
      </div>
    </div>
  );
}
