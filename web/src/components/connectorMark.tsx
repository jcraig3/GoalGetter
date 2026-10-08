import { DatabaseIcon, PlugIcon } from './icons';
import {
  AircallLogo,
  ExcelLogo,
  GoogleLogo,
  HubspotLogo,
  InitialLogo,
  MicrosoftLogo,
  SalesforceLogo,
  SheetsLogo,
  SnowflakeLogo,
  ZendeskLogo,
} from './logos';

/**
 * Which mark a connector wears, in one place.
 *
 * Three connector cards, a source list and a wizard step all show this, and a
 * lookup repeated in four files is four places to forget a new provider.
 *
 * **Deliberately not on the API.** A logo is presentation: the backend says a
 * connector is called `freshdesk`, and what that looks like is this file's
 * business. Sending an icon name over the wire would mean shipping a connector
 * required touching a schema.
 *
 * Three tiers, and which tier a connector lands in is a judgement about honesty
 * rather than effort:
 *
 * **The real brand mark** — the official path, taken from Simple Icons, for every
 * product that has one there. Seven of them do.
 *
 * **A letter tile in the brand's colour** — for Pipedrive, Freshdesk, Gong and
 * Close, whose marks are not in Simple Icons because those companies asked to be
 * removed from it. Drawing them from memory instead would be worse than no logo:
 * it misrepresents somebody else's trademark, and looks like a knock-off on the
 * one page where looking legitimate matters. A letter in the brand's own colour
 * reads as deliberate, and swapping in an official SVG is one line here.
 *
 * **A plain icon** — for the ones that are not brands at all. A webhook is a
 * protocol and "any JSON API" is a category; giving either a logo would be
 * inventing a product that does not exist. These inherit the theme like the rest
 * of the interface.
 */

/** A named product, and the colour it is known by. */
const BRANDS: Record<string, { letter: string; colour: string }> = {
  freshdesk: { letter: 'F', colour: '#25c16f' },
  pipedrive: { letter: 'P', colour: '#017737' },
  gong: { letter: 'G', colour: '#8038df' },
  close: { letter: 'C', colour: '#2b6bed' },
};

/** The ones with a mark worth drawing properly. */
const MARKS: Record<string, (p: { className?: string }) => React.ReactElement> = {
  // The products get their own marks; the identity providers keep the parent
  // company's. A source reading a spreadsheet should show the spreadsheet, but
  // "Sign in with Microsoft" is not Excel and showing Excel's green X on it would
  // be answering a different question.
  google_sheets: SheetsLogo,
  microsoft_excel: ExcelLogo,
  google: GoogleLogo,
  microsoft: MicrosoftLogo,
  snowflake: SnowflakeLogo,
  salesforce: SalesforceLogo,
  hubspot: HubspotLogo,
  zendesk: ZendeskLogo,
  aircall: AircallLogo,
};

/**
 * Not brands. A generic icon that says what kind of thing it is.
 *
 * `sql` gets a database rather than a plug, which is the small point of having
 * this map at all: "some sort of connection" is true of every entry on the page
 * and therefore tells a reader nothing.
 */
const GENERIC: Record<string, (p: { className?: string }) => React.ReactElement> = {
  sql: DatabaseIcon,
  webhook: PlugIcon,
  api: PlugIcon,
};

export default function ConnectorMark({
  connector,
  className = 'size-8',
}: {
  connector: string;
  className?: string;
}) {
  const Mark = MARKS[connector];
  if (Mark) return <Mark className={className} />;

  const brand = BRANDS[connector];
  if (brand) {
    return (
      <InitialLogo letter={brand.letter} colour={brand.colour} className={className} />
    );
  }

  // A connector nobody has given a mark to yet. A plug rather than nothing, so a
  // new connector looks unfinished rather than broken.
  const Generic = GENERIC[connector] ?? PlugIcon;
  return <Generic className={`${className} text-content-muted`} />;
}
