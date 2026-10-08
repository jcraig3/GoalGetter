/** "agent" → "Agent": a stored key said as a word (review §7). */
export function capitalised(word: string): string {
  return word.replace(/^./, (c) => c.toUpperCase());
}
