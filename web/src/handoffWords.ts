/** What the server says happened to a link it made: emailed, or not, and why. */
export interface Delivery {
  emailed?: boolean;
  /** Why the email failed. Null when it went, or when there was nowhere to send from. */
  email_detail?: string | null;
  /** The link uses localhost, so it opens only on the computer that made it. */
  link_is_local?: boolean;
}

const LASTS = {
  invitation: 'it works once and expires in 7 days',
  reset: 'it works once and expires in 2 hours',
} as const;

/**
 * The sentence above a link to hand over, saying whether it was also emailed.
 *
 * The server always reported it and the page never said: "Send them this link"
 * after it had already gone to their inbox, and the same words when the send
 * failed. The link is shown either way — email is an extra, never the only way.
 */
export function handoffMessage(
  kind: keyof typeof LASTS,
  person: { name: string; email: string },
  delivery: Delivery,
): string {
  const lasts = LASTS[kind];
  const noun = kind === 'invitation' ? 'Invitation' : 'Password reset link';
  const said = delivery.emailed
    ? `${noun} emailed to ${person.email}. The link is here too, if you would rather send it yourself — ${lasts}.`
    : delivery.email_detail
      ? `Could not email it: ${delivery.email_detail.replace(/\.?$/, '.')} Send ${person.name} this link yourself — ${lasts}.`
      : `${noun} ready for ${person.name}. Send them this link — ${lasts}.`;
  return delivery.link_is_local
    ? `${said} It uses localhost, so it only opens on this computer: open GoalGetter by its network address and make it again, or set APP_URL.`
    : said;
}
