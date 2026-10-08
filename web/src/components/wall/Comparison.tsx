import Board from './Board';
import { useWallShape } from './WallStage';
import { sessionImageUrl, type ImageUrl, type Slide } from './types';

/**
 * Two to four boards, side by side.
 *
 * **A question no single board can answer.** "Who is calling and who is
 * closing" is two boards, and a rotation showing them ninety seconds apart asks
 * the room to hold one in their head while they wait for the other. Side by
 * side, the person who is top of one and bottom of the other is visible in a
 * glance — which is the conversation a sales floor actually wants to have.
 *
 * **Each panel keeps its own units.** Two boards on one slide are still two
 * metrics; a shared format would print seven deals as $7.00. The server sends
 * each panel the fields a leaderboard slide carries, and `Board` formats each
 * one from its own.
 */
export default function Comparison({
  slide,
  imageUrl = sessionImageUrl,
  rows = 5,
  showValues = true,
}: {
  slide: Slide;
  imageUrl?: ImageUrl;
  rows?: number;
  showValues?: boolean;
}) {
  const panels = slide.panels;
  // **Stacked on a portrait wall** (6.11): four columns in 1080 pixels is four
  // columns of ellipses. Two or three go one above another; four make a
  // square.
  const portrait = useWallShape() === 'portrait';
  if (panels.length === 0) return null;
  const columns = portrait ? (panels.length === 4 ? 2 : 1) : panels.length;

  return (
    // An explicit column count rather than auto-fit: the number of panels is
    // 2, 3 or 4 and known, and auto-fit would reflow two wide boards into one
    // column on a screen that has room for both.
    <div
      className="grid gap-6"
      style={{
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
      }}
    >
      {panels.map((panel, index) => (
        <section key={`${panel.title}-${index}`} className="min-w-0">
          <h2 className="truncate text-wall-3xl font-semibold text-content">
            {panel.title}
          </h2>
          {panel.subtitle && (
            <p className="mt-1 truncate text-wall-xl text-content-muted">
              {panel.subtitle}
            </p>
          )}
          <div className="mt-4">
            {panel.entries.length > 0 ? (
              <Board
                slide={panel}
                imageUrl={imageUrl}
                size="panel"
                rows={rows}
                showValues={showValues}
              />
            ) : (
              // A column with nothing in it is a real state on a new metric,
              // and saying so beats a blank space the room reads as a bug.
              <p className="text-wall-xl text-content-subtle">Nobody yet.</p>
            )}
          </div>
        </section>
      ))}
    </div>
  );
}
