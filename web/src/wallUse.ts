/**
 * What deleting a board, goal or contest does to the TVs, said in its confirm
 * (8.6). Its slides go with it — the database cascades — and a room's wall
 * just stops showing it, so the confirm names the channels first.
 */
import { api } from './api';

export interface Using {
  channel_id: number;
  channel_name: string;
  slides: number;
}

/** "Removes 1 slide from Sales floor and 2 from Lobby." */
export function usingWords(using: Using[]): string {
  if (using.length === 0) return '';
  const parts = using.map((u, i) =>
    i === 0
      ? `${u.slides} slide${u.slides === 1 ? '' : 's'} from ${u.channel_name}`
      : `${u.slides} from ${u.channel_name}`,
  );
  const list = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
  return `It also comes off the TVs: removes ${list}.`;
}

/**
 * The question to ask before archiving, or null when it is on no TV (P3-2):
 * archiving is undone in a click, so it asks only when a wall would change.
 */
export async function archiveQuestion(
  kind: 'leaderboard' | 'goal',
  id: number,
  name: string,
): Promise<string | null> {
  try {
    const using = await api<Using[]>(`/api/channels/using?kind=${kind}&id=${id}`);
    if (using.length === 0) return null;
    const where = using
      .map((u) => `${u.channel_name} (${u.slides} slide${u.slides === 1 ? '' : 's'})`)
      .join(', ');
    return `Archive “${name}”?\n\nIt stops playing on ${where}. Restore it to bring it back.`;
  } catch {
    return null;
  }
}

/** The sentence for a confirm, or "" when it is on no channel or cannot be asked. */
export async function wallWords(kind: 'leaderboard' | 'goal' | 'competition', id: number): Promise<string> {
  try {
    const using = await api<Using[]>(`/api/channels/using?kind=${kind}&id=${id}`);
    const said = usingWords(using);
    return said ? `\n\n${said}` : '';
  } catch {
    return '';
  }
}
