import { useEffect } from 'react';

/** The nav's Goals target, in the brand colour: the tab's icon until an
 *  organization sets a logo. */
export const DEFAULT_ICON = '/favicon.svg';

function iconLink(): HTMLLinkElement {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  return link;
}

export function setSiteIcon(url: string | null) {
  const link = iconLink();
  if (url) {
    // A logo can be a PNG, a JPEG or an SVG: the browser works it out.
    link.removeAttribute('type');
    link.href = url;
  } else {
    link.type = 'image/svg+xml';
    link.href = DEFAULT_ICON;
  }
}

/**
 * **The browser tab shows the organization's logo** when one is set in
 * Settings → Branding, and the Goals target otherwise. Back to the target when
 * the page that set it goes (signing out, say).
 */
export function useSiteIcon(url: string | null) {
  useEffect(() => {
    setSiteIcon(url);
    return () => setSiteIcon(null);
  }, [url]);
}
