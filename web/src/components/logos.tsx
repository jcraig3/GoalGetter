/**
 * Brand marks for integration tiles.
 *
 * Separate from `icons.tsx` because these are not icons: they carry fixed
 * brand colours and filled shapes rather than inheriting `currentColor` in a
 * 1.75px stroke. Mixing them would mean the icon rules stop holding for half
 * the file.
 *
 * Drawn inline rather than fetched. A logo loaded from a vendor CDN would be a
 * third-party request on every page load of a self-hosted internal tool, and
 * would break entirely on an air-gapped deployment.
 */

type LogoProps = { className?: string };

const base = 'size-8 shrink-0';

/** The Microsoft four-square mark, in its published colours. */
export function MicrosoftLogo({ className }: LogoProps) {
  return (
    <svg
      className={`${base} ${className ?? ''}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <rect x="1" y="1" width="10" height="10" fill="#F25022" />
      <rect x="13" y="1" width="10" height="10" fill="#7FBA00" />
      <rect x="1" y="13" width="10" height="10" fill="#00A4EF" />
      <rect x="13" y="13" width="10" height="10" fill="#FFB900" />
    </svg>
  );
}

/**
 * Microsoft Teams: a "T" on a tile in Teams' purple.
 *
 * **A simple mark, not a copy of Microsoft's.** Their Teams logo is a layered
 * drawing with its own usage rules; a card only needs to be recognisable at a
 * glance, and the purple and the letter do that.
 */
export function TeamsLogo({ className }: LogoProps) {
  return (
    <svg className={`${base} ${className ?? ''}`} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="1.5" y="3" width="16" height="16" rx="3" fill="#5B5FC7" />
      <path d="M5.5 7.5h8M9.5 7.5v8" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="19.5" cy="7" r="2.5" fill="#7B83EB" />
      <path d="M17 10.5h5v5a2.5 2.5 0 0 1-2.5 2.5H19" fill="#7B83EB" />
    </svg>
  );
}

/**
 * Slack: a hash on a tile in Slack's aubergine.
 *
 * **A simple mark, not a copy of Slack's.** The real logo has its own usage
 * rules; a card only needs to be recognisable, and the colour and the channel
 * sign do that.
 */
export function SlackLogo({ className }: LogoProps) {
  return (
    <svg className={`${base} ${className ?? ''}`} viewBox="0 0 24 24" aria-hidden="true">
      <rect x="2" y="2" width="20" height="20" rx="5" fill="#4A154B" />
      <path
        d="M10 6.5 8.5 17.5M15.5 6.5 14 17.5M6.5 10h11M6 14h11"
        stroke="#fff"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Mail. Not a brand — SMTP is a protocol, so there is nothing to be faithful
 * to and this inherits the theme like the rest of the interface.
 */
export function MailLogo({ className }: LogoProps) {
  return (
    <svg
      className={`${base} ${className ?? ''}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="2" y="4.5" width="20" height="15" rx="2.5" />
      <path d="m3 6.5 8.1 6.2a1.5 1.5 0 0 0 1.8 0L21 6.5" />
    </svg>
  );
}

/**
 * The Google "G", in its four published colours.
 *
 * Reproduced faithfully because it is a mark people recognise instantly and a
 * wrong version of it looks like a phishing page. Note that the **Sign in with
 * Google button** has its own published branding rules — minimum size, exact
 * wording, specific asset — which are stricter than showing the mark on a card.
 * That button is a separate job from this file.
 */
export function GoogleLogo({ className }: LogoProps) {
  return (
    <svg
      className={`${base} ${className ?? ''}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path
        fill="#4285F4"
        d="M23 12.2c0-.8-.07-1.6-.2-2.3H12v4.4h6.1a5.2 5.2 0 0 1-2.3 3.4v2.8h3.6c2.1-1.9 3.3-4.8 3.3-8.3Z"
      />
      <path
        fill="#34A853"
        d="M12 23.5c3 0 5.5-1 7.4-2.7l-3.6-2.8c-1 .7-2.3 1.1-3.8 1.1a6.7 6.7 0 0 1-6.3-4.6H2v2.9A11.5 11.5 0 0 0 12 23.5Z"
      />
      <path
        fill="#FBBC05"
        d="M5.7 14.5a6.9 6.9 0 0 1 0-4.4V7.2H2a11.5 11.5 0 0 0 0 10.2l3.7-2.9Z"
      />
      <path
        fill="#EA4335"
        d="M12 5.4c1.7 0 3.2.6 4.4 1.7l3.2-3.2A11.5 11.5 0 0 0 2 7.2l3.7 2.9A6.7 6.7 0 0 1 12 5.4Z"
      />
    </svg>
  );
}

/**
 * A provider's initial on a coloured tile.
 *
 * **For every brand whose mark cannot be drawn faithfully from memory.** A
 * hand-approximated logo is worse than no logo: it misrepresents somebody else's
 * trademark and looks like a knock-off, which on an integrations page is exactly
 * the wrong impression. A letter in the provider's own colour reads as
 * deliberate, is honest about what it is, and swaps out for an official SVG later
 * without touching anything but this file.
 */
export function InitialLogo({
  letter,
  colour,
  className,
}: LogoProps & { letter: string; colour: string }) {
  return (
    <svg
      className={`${base} ${className ?? ''}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <rect width="24" height="24" rx="6" fill={colour} />
      <text
        x="12"
        y="12"
        textAnchor="middle"
        dominantBaseline="central"
        // Not a Tailwind class: this is inside an SVG, and the tile has to look
        // the same wherever it is dropped.
        fontSize="13"
        fontWeight="600"
        fill="#fff"
        // The one font stack that exists everywhere, since a self-hosted
        // deployment may have no webfont at all.
        fontFamily="system-ui, sans-serif"
      >
        {letter}
      </text>
    </svg>
  );
}

/**
 * Official product marks.
 *
 * **Path data from Simple Icons** (simpleicons.org), which is CC0 — public domain,
 * no attribution required — and which takes each mark from the brand's own press
 * kit. That is the difference between these and what preceded them: they are the
 * real shapes rather than careful guesses at them.
 *
 * Each is a single monochrome path filled with the brand's published colour, which
 * is how Simple Icons ships them. A one-colour mark is also the version that
 * survives being drawn at 28 pixels beside a line of text, which is the only size
 * any of these is ever shown at here.
 *
 * **Copied rather than depended on.** `npm i simple-icons` for seven icons pulls
 * three thousand, and the argument at the top of this file still holds: a
 * self-hosted deployment may be air-gapped, so nothing here may be fetched at
 * runtime.
 *
 * **Four brands are deliberately absent** — Pipedrive, Freshdesk, Gong and Close.
 * Simple Icons does not carry them, because those companies asked to be removed
 * from it. They keep letter tiles, which is the honest thing to show rather than a
 * drawing from memory of a trademark whose owner has said no.
 */
function BrandMark({
  path,
  colour,
  className,
}: LogoProps & { path: string; colour: string }) {
  return (
    <svg
      className={`${base} ${className ?? ''}`}
      viewBox="0 0 24 24"
      fill={colour}
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}

const SNOWFLAKE_PATH =
  'M24 3.459c0 .646-.418 1.18-1.141 1.18-.723 0-1.142-.534-1.142-1.18 0-.647.419-1.18 1.142-1.18.723 0 1.141.533 1.141 1.18zm-.228 0c0-.533-.38-.951-.913-.951s-.913.38-.913.95c0 .533.38.952.913.952.57 0 .913-.419.913-.951zm-1.37-.533h.495c.266 0 .456.152.456.38 0 .153-.076.229-.19.305l.19.266v.038h-.266l-.19-.266h-.229v.266h-.266zm.495.228h-.229v.267h.229c.114 0 .152-.038.152-.114.038-.077-.038-.153-.152-.153zM7.602 12.4c.038-.151.076-.304.076-.456 0-.114-.038-.228-.038-.342-.114-.343-.304-.647-.646-.838l-4.87-2.777c-.685-.38-1.56-.152-1.94.533-.381.685-.153 1.56.532 1.94l2.701 1.56-2.701 1.56c-.685.38-.913 1.256-.533 1.94.38.685 1.256.914 1.94.533l4.832-2.777c.343-.267.571-.533.647-.876zm1.332 2.626c-.266-.038-.57.038-.837.19l-4.832 2.777c-.685.38-.913 1.256-.532 1.94.38.686 1.255.914 1.94.533l2.701-1.56v3.12c0 .8.647 1.408 1.446 1.408.799 0 1.407-.647 1.407-1.408v-5.592c0-.761-.57-1.37-1.293-1.408zm4.946-6.088c.266.038.57-.038.837-.19l4.832-2.777c.685-.38.913-1.256.532-1.94-.38-.686-1.255-.914-1.94-.533l-2.701 1.56V1.975c0-.799-.647-1.408-1.446-1.408-.799 0-1.446.609-1.446 1.408V7.53c0 .76.609 1.37 1.332 1.407zM3.265 5.97l4.832 2.777c.266.152.533.19.837.19.723-.038 1.331-.684 1.331-1.407V1.975c0-.799-.646-1.408-1.407-1.408-.799 0-1.446.647-1.446 1.408v3.12l-2.701-1.56c-.685-.38-1.56-.152-1.94.533-.419.646-.19 1.521.494 1.902zm9.093 6.011a.412.412 0 00-.114-.266l-.57-.571a.346.346 0 00-.267-.114.412.412 0 00-.266.114l-.571.57a.411.411 0 00-.114.267c0 .076.038.19.114.267l.57.57a.345.345 0 00.267.114c.076 0 .19-.038.266-.114l.571-.57a.412.412 0 00.114-.267zm1.598.533L11.94 14.53c-.039.038-.153.114-.229.114h-.608a.411.411 0 01-.267-.114L8.82 12.514a.408.408 0 01-.076-.229v-.608c0-.076.038-.19.114-.267l2.016-2.016a.41.41 0 01.267-.114h.608a.41.41 0 01.267.114l2.016 2.016a.347.347 0 01.114.267v.608c-.076.077-.114.19-.19.229zm5.593 5.44l-4.832-2.777c-.266-.152-.57-.19-.837-.152-.723.038-1.332.684-1.332 1.408v5.554c0 .8.647 1.408 1.408 1.408.799 0 1.446-.647 1.446-1.408v-3.12l2.7 1.56c.686.38 1.561.152 1.941-.533.419-.646.19-1.521-.494-1.94zm2.549-7.533l-2.701 1.56 2.7 1.56c.686.38.914 1.256.533 1.94-.38.685-1.255.913-1.94.533l-4.832-2.778a1.644 1.644 0 01-.647-.798c-.037-.153-.076-.305-.076-.457 0-.114.039-.228.039-.342.114-.343.342-.647.646-.837l4.832-2.778c.685-.38 1.56-.152 1.94.533.457.609.19 1.484-.494 1.864';

const SALESFORCE_PATH =
  'M10.006 5.415a4.195 4.195 0 013.045-1.306c1.56 0 2.954.9 3.69 2.205.63-.3 1.35-.45 2.1-.45 2.85 0 5.159 2.34 5.159 5.22s-2.31 5.22-5.176 5.22c-.345 0-.69-.044-1.02-.104a3.75 3.75 0 01-3.3 1.95c-.6 0-1.155-.15-1.65-.375A4.314 4.314 0 018.88 20.4a4.302 4.302 0 01-4.05-2.82c-.27.062-.54.076-.825.076-2.204 0-4.005-1.8-4.005-4.05 0-1.5.811-2.805 2.01-3.51-.255-.57-.39-1.2-.39-1.846 0-2.58 2.1-4.65 4.65-4.65 1.53 0 2.85.705 3.72 1.8';

const HUBSPOT_PATH =
  'M18.164 7.93V5.084a2.198 2.198 0 001.267-1.978v-.067A2.2 2.2 0 0017.238.845h-.067a2.2 2.2 0 00-2.193 2.193v.067a2.196 2.196 0 001.252 1.973l.013.006v2.852a6.22 6.22 0 00-2.969 1.31l.012-.01-7.828-6.095A2.497 2.497 0 104.3 4.656l-.012.006 7.697 5.991a6.176 6.176 0 00-1.038 3.446c0 1.343.425 2.588 1.147 3.607l-.013-.02-2.342 2.343a1.968 1.968 0 00-.58-.095h-.002a2.033 2.033 0 102.033 2.033 1.978 1.978 0 00-.1-.595l.005.014 2.317-2.317a6.247 6.247 0 104.782-11.134l-.036-.005zm-.964 9.378a3.206 3.206 0 113.215-3.207v.002a3.206 3.206 0 01-3.207 3.207z';

const ZENDESK_PATH =
  'M12.914 2.904V16.29L24 2.905H12.914zM0 2.906C0 5.966 2.483 8.45 5.543 8.45s5.542-2.484 5.543-5.544H0zm11.086 4.807L0 21.096h11.086V7.713zm7.37 7.84c-3.063 0-5.542 2.48-5.542 5.543H24c0-3.06-2.48-5.543-5.543-5.543z';

const SHEETS_PATH =
  'M11.318 12.545H7.91v-1.909h3.41v1.91zM14.728 0v6h6l-6-6zm1.363 10.636h-3.41v1.91h3.41v-1.91zm0 3.273h-3.41v1.91h3.41v-1.91zM20.727 6.5v15.864c0 .904-.732 1.636-1.636 1.636H4.909a1.636 1.636 0 0 1-1.636-1.636V1.636C3.273.732 4.005 0 4.909 0h9.318v6.5h6.5zm-3.273 2.773H6.545v7.909h10.91v-7.91zm-6.136 4.636H7.91v1.91h3.41v-1.91z';

const EXCEL_PATH =
  'M23 1.5q.41 0 .7.3.3.29.3.7v19q0 .41-.3.7-.29.3-.7.3H7q-.41 0-.7-.3-.3-.29-.3-.7V18H1q-.41 0-.7-.3-.3-.29-.3-.7V7q0-.41.3-.7Q.58 6 1 6h5V2.5q0-.41.3-.7.29-.3.7-.3zM6 13.28l1.42 2.66h2.14l-2.38-3.87 2.34-3.8H7.46l-1.3 2.4-.05.08-.04.09-.64-1.28-.66-1.29H2.59l2.27 3.82-2.48 3.85h2.16zM14.25 21v-3H7.5v3zm0-4.5v-3.75H12v3.75zm0-5.25V7.5H12v3.75zm0-5.25V3H7.5v3zm8.25 15v-3h-6.75v3zm0-4.5v-3.75h-6.75v3.75zm0-5.25V7.5h-6.75v3.75zm0-5.25V3h-6.75v3Z';

const AIRCALL_PATH =
  'M23.451 5.906a6.978 6.978 0 0 0-5.375-5.39C16.727.204 14.508 0 12 0S7.273.204 5.924.516a6.978 6.978 0 0 0-5.375 5.39C.237 7.26.034 9.485.034 12s.203 4.74.515 6.094a6.978 6.978 0 0 0 5.375 5.39C7.273 23.796 9.492 24 12 24s4.727-.204 6.076-.516a6.978 6.978 0 0 0 5.375-5.39c.311-1.354.515-3.578.515-6.094 0-2.515-.203-4.74-.515-6.094zm-5.873 12.396l-.003.001c-.428.152-1.165.283-2.102.377l-.147.014a.444.444 0 0 1-.45-.271 1.816 1.816 0 0 0-1.296-1.074c-.351-.081-.928-.134-1.58-.134s-1.229.053-1.58.134a1.817 1.817 0 0 0-1.291 1.062.466.466 0 0 1-.471.281 8 8 0 0 0-.129-.012c-.938-.094-1.676-.224-2.105-.377l-.003-.001a.76.76 0 0 1-.492-.713c0-.032.003-.066.005-.098.073-.979.666-3.272 1.552-5.89C8.5 8.609 9.559 6.187 10.037 5.714a1.029 1.029 0 0 1 .404-.26l.004-.002c.314-.106.892-.178 1.554-.178.663 0 1.241.071 1.554.178l.005.002a1.025 1.025 0 0 1 .405.26c.478.472 1.537 2.895 2.549 5.887.886 2.617 1.479 4.91 1.552 5.89.002.032.005.066.005.098a.76.76 0 0 1-.491.713z';

export const SnowflakeLogo = (p: LogoProps) => (
  <BrandMark {...p} path={SNOWFLAKE_PATH} colour="#29B5E8" />
);
export const SalesforceLogo = (p: LogoProps) => (
  <BrandMark {...p} path={SALESFORCE_PATH} colour="#00A1E0" />
);
export const HubspotLogo = (p: LogoProps) => (
  <BrandMark {...p} path={HUBSPOT_PATH} colour="#FF7A59" />
);
export const ZendeskLogo = (p: LogoProps) => (
  <BrandMark {...p} path={ZENDESK_PATH} colour="#03363D" />
);
export const SheetsLogo = (p: LogoProps) => (
  <BrandMark {...p} path={SHEETS_PATH} colour="#34A853" />
);
export const ExcelLogo = (p: LogoProps) => (
  <BrandMark {...p} path={EXCEL_PATH} colour="#217346" />
);
export const AircallLogo = (p: LogoProps) => (
  <BrandMark {...p} path={AIRCALL_PATH} colour="#00B388" />
);
