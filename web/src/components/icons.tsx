/**
 * Inline SVG icons.
 *
 * Hand-written rather than an icon library: we need about ten, and a library
 * costs 50–200 KB plus a dependency to keep current. Each is a 24px stroke
 * icon using `currentColor`, so it inherits text colour and needs no theming.
 */

type IconProps = { className?: string };

const base = 'size-5 shrink-0';

function Svg({
  className,
  children,
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      className={`${base} ${className ?? ''}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      // Decorative: the adjacent text label is what a screen reader announces.
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

/** Announcements (Phase 25): a megaphone. */
export const MegaphoneIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10v4a1 1 0 0 0 1 1h3l6 4V5L7 9H4a1 1 0 0 0-1 1Z" />
    <path d="M17 9a4 4 0 0 1 0 6M7 15l1 4h2" />
  </Svg>
);

/** Sound on: a speaker with its waves (Phase 24, a TV's sound). */
export const SpeakerIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M11 5 6 9H3v6h3l5 4V5Z" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
  </Svg>
);

/** Sound off: the speaker, crossed out. */
export const SpeakerOffIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M11 5 6 9H3v6h3l5 4V5Z" />
    <path d="m16 9 5 6M21 9l-5 6" />
  </Svg>
);

export const InboxIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 13.5 5.5 5h13l2.5 8.5V19H3v-5.5Z" />
    <path d="M3 13.5h5l1.5 2.5h5l1.5-2.5h5" />
  </Svg>
);

export const ImageIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <circle cx="9" cy="10" r="1.75" />
    <path d="m21 16-5-5-9 9" />
  </Svg>
);

export const HomeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V21h14V9.5" />
  </Svg>
);

export const TrophyIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0V4Z" />
    <path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3" />
  </Svg>
);

export const TargetIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="5" />
    <circle cx="12" cy="12" r="1.5" />
  </Svg>
);

export const UsersIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M16 19v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 17.5V19" />
    <circle cx="10" cy="8" r="3.25" />
    <path d="M20 19v-1.5a3.5 3.5 0 0 0-2.75-3.42M15.5 5.2a3.25 3.25 0 0 1 0 5.6" />
  </Svg>
);

export const FlagIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 21V4M5 4h10l-1.5 3L15 10H5" />
  </Svg>
);

export const PlugIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 3v6M15 3v6M7 9h10v3a5 5 0 0 1-10 0V9ZM12 17v4" />
  </Svg>
);

/** Stacked discs. For a data source that is a database rather than a product —
 *  "some sort of connection" is true of every row on the integrations page and
 *  therefore tells a reader nothing. */
export const DatabaseIcon = (p: IconProps) => (
  <Svg {...p}>
    <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
    <path d="M4.5 5.5v13c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3v-13" />
    <path d="M4.5 12c0 1.66 3.36 3 7.5 3s7.5-1.34 7.5-3" />
  </Svg>
);

/** Alias for the nav's settings glyph. Same shape, different job: this one
 *  labels "adjust this connection" rather than "organization settings". */
export const CogIcon = (p: IconProps) => <SettingsIcon {...p} />;

export const SettingsIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
  </Svg>
);

/** A painter's palette, for the Appearance tab. */
export const PaletteIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3a9 9 0 1 0 0 18c.83 0 1.5-.67 1.5-1.5 0-.39-.15-.74-.39-1a1.5 1.5 0 0 1 1.06-2.56H16a5 5 0 0 0 5-5c0-4.42-4.03-8-9-8Z" />
    <circle cx="7.5" cy="12" r="1" />
    <circle cx="9.5" cy="8" r="1" />
    <circle cx="14" cy="7.5" r="1" />
    <circle cx="17" cy="11" r="1" />
  </Svg>
);

export const MenuIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Svg>
);

export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Svg>
);

export const LogoutIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" />
    <path d="M10 8 6 12l4 4M6 12h9" />
  </Svg>
);

export const TvIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="5" width="19" height="12.5" rx="2" />
    <path d="M8 21h8M12 17.5V21" />
  </Svg>
);

export const BellIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M18 8.5a6 6 0 1 0-12 0c0 5-2 6.5-2 6.5h16s-2-1.5-2-6.5" />
    <path d="M10.5 19a1.8 1.8 0 0 0 3 0" />
  </Svg>
);

export const MedalIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="15" r="6" />
    <path d="M8.5 9.5 6 2.5h12l-2.5 7" />
    <path d="m12 12.5 1 2 2.2.3-1.6 1.5.4 2.2-2-1-2 1 .4-2.2-1.6-1.5 2.2-.3z" />
  </Svg>
);

export const PencilIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3z" />
    <path d="M14.5 6.5l3 3" />
  </Svg>
);

export const CopyIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="9" y="9" width="11.5" height="11.5" rx="2" />
    <path d="M5.5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5v1" />
  </Svg>
);

export const TrashIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 6.5h16" />
    <path d="M9.5 6.5V4.5A1 1 0 0 1 10.5 3.5h3a1 1 0 0 1 1 1v2" />
    <path d="M6.5 6.5 7.5 20a1.5 1.5 0 0 0 1.5 1.4h6a1.5 1.5 0 0 0 1.5-1.4l1-13.5" />
    <path d="M10.5 10.5v7M13.5 10.5v7" />
  </Svg>
);

export const PauseIcon = (p: IconProps) => (
  <Svg {...p}>
    {/* Filled, unlike the rest: two thin outlined bars read as noise at 16px,
        and this pair has to be recognisable instantly. */}
    <path d="M9.5 5v14M14.5 5v14" strokeWidth="2.5" />
  </Svg>
);

export const PlayIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 5.5l10 6.5-10 6.5V5.5Z" fill="currentColor" />
  </Svg>
);

export const MailIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 6.5h18v11H3z" />
    <path d="m3.5 7 8.5 6 8.5-6" />
  </Svg>
);

export const KeyIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14.5 3.5a5 5 0 1 0-4.2 7.7L4 17.5V21h3.5l1-1v-2h2v-2h1.8l1-1a5 5 0 0 0 1.2.2Z" />
    <path d="M16.5 7.5h.01" />
  </Svg>
);

export const ChevronDownIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 9.5 12 15.5l6-6" />
  </Svg>
);

export const ArchiveIcon = (p: IconProps) => (
  <Svg {...p}>
    {/* A box with a lid: archiving puts something away intact, which is the
        distinction from the bin next to it. */}
    <path d="M3 7.5h18V5.5A1.5 1.5 0 0 0 19.5 4h-15A1.5 1.5 0 0 0 3 5.5v2Z" />
    <path d="M4.5 7.5V19a1.5 1.5 0 0 0 1.5 1.5h12A1.5 1.5 0 0 0 19.5 19V7.5" />
    <path d="M10 11.5h4" />
  </Svg>
);

export const RestoreIcon = (p: IconProps) => (
  <Svg {...p}>
    {/* An arrow curving back anticlockwise — the same box, coming out again. */}
    <path d="M3.5 5.5v5h5" />
    <path d="M4.2 10.5a8 8 0 1 1 1.9 7.1" />
  </Svg>
);

export const BuildingIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 21V5.5A1.5 1.5 0 0 1 5.5 4h7A1.5 1.5 0 0 1 14 5.5V21" />
    <path d="M14 10h4.5A1.5 1.5 0 0 1 20 11.5V21M2.5 21h19" />
    <path d="M7 8h4M7 12h4M7 16h4" />
  </Svg>
);

export const SparkIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l2.1 5.4L19.5 10l-5.4 2.1L12 17.5l-2.1-5.4L4.5 10l5.4-1.6L12 3Z" />
  </Svg>
);

export const ChartIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
  </Svg>
);

export const RulerIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="7" width="19" height="10" rx="2" />
    <path d="M7 7v3M12 7v4M17 7v3" />
  </Svg>
);

export const RepeatIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 9V8a3 3 0 0 1 3-3h10l-2.5-2.5M20 15v1a3 3 0 0 1-3 3H7l2.5 2.5" />
  </Svg>
);

export const SearchIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-4.5-4.5" />
  </Svg>
);
