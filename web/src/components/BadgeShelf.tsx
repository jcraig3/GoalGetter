import { useEffect, useState } from 'react';

import { api } from '../api';
import {
  type Held,
  type Progress,
  progressPercent,
  remainingLabel,
  timesLabel,
} from '../pages/badgesCopy';
import { BadgeMark } from './badgeMarks';

interface Mine {
  held: Held[];
  progress: Progress[];
}

/**
 * Your badges, and the ones you are partway to.
 *
 * **This is the part of the page that survives a season reset.** Points go to
 * zero every quarter, deliberately; a badge for ten big deals in March is
 * still true in December. So it sits below the season table rather than
 * inside it — it is not about where anybody stands this season.
 *
 * Renders nothing at all when there is nothing to show. An empty "Badges"
 * heading on the page of somebody who has none yet is a small daily reminder
 * of it, and the season table above already tells them how to get going.
 */
export default function BadgeShelf() {
  const [mine, setMine] = useState<Mine | null>(null);

  useEffect(() => {
    // Quietly absent on failure rather than an error box: this is the lower
    // half of a page whose upper half has its own error handling, and a
    // second red box for a secondary panel is noise.
    api<Mine>('/api/points/badges/mine')
      .then(setMine)
      .catch(() => setMine({ held: [], progress: [] }));
  }, []);

  if (!mine || (mine.held.length === 0 && mine.progress.length === 0)) {
    return null;
  }

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">Badges</h2>

      {mine.progress.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm text-content-muted">Almost there</h3>
          <ul className="mt-2 space-y-3">
            {mine.progress.map((row) => (
              <li key={row.badge_id} className="flex items-center gap-3">
                {/* Greyed until it is earned: the colour is the reward. */}
                <span className="shrink-0 opacity-60 grayscale">
                  <BadgeMark icon={row.icon} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="text-content">{row.name}</span>
                    <span className="text-sm text-content">
                      {remainingLabel(row)}
                    </span>
                  </div>
                  <div
                    className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-hover"
                    role="progressbar"
                    aria-label={`${row.name} progress`}
                    aria-valuenow={row.have}
                    aria-valuemin={0}
                    aria-valuemax={row.need}
                  >
                    <div
                      className="h-full bg-brand"
                      style={{ width: `${progressPercent(row)}%` }}
                    />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {mine.held.length > 0 && (
        <div className="mt-5">
          <h3 className="text-sm text-content-muted">Earned</h3>
          <ul className="mt-2 flex flex-wrap gap-3">
            {mine.held.map((row) => (
              <li
                key={row.badge_id}
                title={row.description || row.reason}
                className="flex items-center gap-2 rounded-md border border-edge px-3 py-2"
              >
                <BadgeMark icon={row.icon} className="h-8 w-8" />
                <span className="text-sm text-content">{row.name}</span>
                {timesLabel(row) && (
                  <span className="text-xs tabular-nums text-content-muted">
                    {timesLabel(row)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
