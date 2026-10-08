import { dayAndTime } from '../time';
import { useEffect, useState } from 'react';

import { api } from '../api';
import Modal from './Modal';
import { Tab } from './Tabs';
import TeamsSettings from './TeamsSettings';
import { Comparison, DECISIONS, SourceBrowser, useMirror } from './TeamsMirror';
import Loading from './Loading';

type Section = 'announcements' | 'structure' | 'people';

/**
 * Everything Microsoft Teams, behind its own card.
 *
 * **Its own door, like Excel and Snowflake**, rather than a section inside the
 * Microsoft 365 connection. It had grown to three jobs — posting wins, turning
 * Teams and channels into teams and offices, and comparing everybody's place —
 * and a dialog that already held sign-in, directory sync, mail and Excel made
 * all of them a long scroll away.
 *
 * **Three tabs, in the order the work happens**: what to post, what each Team
 * or channel is, and then who that moves. Announcements need no Microsoft 365
 * connection at all, so that tab works on its own; the other two say what to
 * switch on when they cannot.
 */
export default function TeamsIntegration({
  onClose,
  onOpenMicrosoft,
  initial = 'announcements',
}: {
  onClose: () => void;
  /** Where Microsoft Teams is switched on and off. */
  onOpenMicrosoft?: () => void;
  initial?: Section;
}) {
  const [section, setSection] = useState<Section>(initial);
  const [on, setOn] = useState<boolean | null>(null);

  useEffect(() => {
    api<{ enabled: boolean }>('/api/announcements/destinations')
      .then((listing) => setOn(listing.enabled))
      .catch(() => setOn(null));
  }, []);
  const { mirror, loaded, error, busy, act } = useMirror();
  const decisions = mirror ? DECISIONS.reduce((n, s) => n + (mirror.counts[s] ?? 0), 0) : 0;
  const linked = mirror ? mirror.sources.filter((s) => s.link).length : 0;

  return (
    <Modal
      title="Microsoft Teams"
      description="Post wins into channels, and use Teams and channels as your teams and offices."
      onClose={onClose}
      wide
    >
      {/* **Configured here, switched there.** Everything below can be set up
          while it is off; nothing is posted or read on a schedule until it is on. */}
      {on === false && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <span className="text-content">
            Microsoft Teams is switched off, so nothing is posted and Teams is not read on a
            schedule. You can still set everything up here.
          </span>
          {onOpenMicrosoft && (
            <button type="button" onClick={onOpenMicrosoft} className="text-brand hover:underline">
              Switch it on in Microsoft 365
            </button>
          )}
        </div>
      )}

      <div className="mb-4 flex flex-wrap gap-1 border-b border-edge pb-3" role="group" aria-label="Section">
        <Tab active={section === 'announcements'} onClick={() => setSection('announcements')}>
          Announcements
        </Tab>
        <Tab active={section === 'structure'} onClick={() => setSection('structure')}>
          Teams &amp; offices{linked > 0 ? ` (${linked})` : ''}
        </Tab>
        <Tab active={section === 'people'} onClick={() => setSection('people')}>
          People
          {decisions > 0 && (
            <span className="ml-1.5 rounded-full bg-warning/15 px-1.5 text-xs text-warning">{decisions}</span>
          )}
        </Tab>
      </div>

      {section === 'announcements' ? (
        <TeamsSettings />
      ) : !loaded ? (
        <Loading />
      ) : !mirror || !mirror.available ? (
        <p className="rounded-md border border-dashed border-edge px-4 py-6 text-sm text-content-muted">
          This reads your Microsoft 365 tenant. Switch on <strong>Tenant user sync</strong> in the
          Microsoft 365 connection, and your Teams and channels appear here.
        </p>
      ) : (
        <div className="space-y-4">
          {error && (
            <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          {section === 'structure' && (
            <>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <p className="max-w-xl text-sm text-content-muted">
                  Choose what each Team or channel is here. Its people then belong on that team or in
                  that office. Moving people by hand still works, and those moves are kept.
                </p>
                <div className="text-right">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void act('/read', { method: 'POST' })}
                    className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-60"
                  >
                    {busy ? 'Working…' : 'Read from Microsoft Teams'}
                  </button>
                  {mirror.read_at && (
                    <p className="mt-1 text-xs text-content-subtle">
                      Last read {dayAndTime(mirror.read_at)}
                    </p>
                  )}
                </div>
              </div>
              {mirror.note && (
                <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-content">
                  {mirror.note}
                </p>
              )}
              <SourceBrowser mirror={mirror} busy={busy} act={act} />
            </>
          )}

          {section === 'people' && <Comparison mirror={mirror} busy={busy} act={act} />}
        </div>
      )}
    </Modal>
  );
}
