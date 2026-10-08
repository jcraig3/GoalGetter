import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import M365Places from '../components/M365Places';
import { Link } from 'react-router-dom';

import { api } from '../api';
import {
  dataSources,
  type ConnectorOption,
  type Provider,
  type Source,
} from '../dataSources';
import AccountConnectButton from '../components/AccountConnectButton';
import ConnectorPicker from '../components/ConnectorPicker';
import ErrorNote from '../components/ErrorNote';
import SsoRoleRules, { type RoleRule } from '../components/SsoRoleRules';
import TeamsIntegration from '../components/TeamsIntegration';
import TeamsSettings from '../components/TeamsSettings';
import ProviderSetup from '../components/ProviderSetup';
import Field from '../components/Field';
import Modal from '../components/Modal';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import SourceHealthPill from '../components/SourceHealthPill';
import Toggle from '../components/Toggle';
import ConnectorMark from '../components/connectorMark';
import { ChevronDownIcon, CogIcon } from '../components/icons';
import { MailLogo, SlackLogo, TeamsLogo } from '../components/logos';
import { directory, type DirectoryStatus } from '../directory';
import { excel as excelApi, type ExcelStatus } from '../excel';
import { sheets as sheetsApi, type SheetsStatus } from '../sheets';
import { warehouse as warehouseApi, type WarehouseStatus } from '../warehouse';
import WarehouseSetup from '../components/WarehouseSetup';
import { flipSignIn, signsInWith } from './ssoSettings';
import { sourceHealth } from './sourceWizard';
import {
  acceptsMore,
  addLabel,
  groupSources,
  worksheetOf,
} from './sourceGroups';
import { ask } from '../confirm';
import Loading from '../components/Loading';

/**
 * How signing in behaves — and nothing about *who* it signs in with.
 *
 * The credential moved to the provider connection, because one Entra app
 * registration serves signing in and reading spreadsheets and there is no reason
 * to hold two copies of it. `provider` names which connection to use; `issuer` and
 * `connected` are read back off that connection so this panel can explain why it
 * cannot be switched on yet.
 */
interface SsoSettings {
  enabled: boolean;
  provider: string | null;
  issuer: string | null;
  connected: boolean;
  scopes: string;
  button_label: string;
  auto_provision: boolean;
  require_sso: boolean;
  /** Roles from groups on each sign-in. */
  role_sync: boolean;
  role_rules: RoleRule[];
}

/** The mail server's settings, as the panel edits them. */
interface SmtpSettings {
  enabled: boolean;
  host: string;
  port: number;
  security: string;
  username: string;
  /** Whether a password is stored. Never the password. */
  password_set: boolean;
  from_address: string;
  from_name: string;
  /** Whether there is enough here to attempt a send — decided by the server, so
   *  the page and the sender cannot disagree about what "configured" means. */
  usable: boolean;
}

interface TestResult {
  ok: boolean;
  detail: string;
  authorization_endpoint: string | null;
}

/**
 * What can be connected.
 *
 * Data, not markup — adding an integration is one entry here plus a panel,
 * rather than another block of near-identical card JSX to keep in sync.
 */
interface Integration {
  key: string;
  name: string;
  category: string;
  summary: string;
  Logo: (p: { className?: string }) => React.ReactElement;
  /** Absent until the backend exists. The tile says so rather than pretending. */
  available: boolean;
}

/**
 * What is left here after the provider connections took their own section.
 *
 * **Microsoft used to be in this list as well as in the connections list**, which
 * was the duplication that started all of this: one card offering to set up
 * sign-on, and a separate row offering to register the same app for Excel.
 *
 * SMTP stays because it genuinely is a different kind of thing — a mail server
 * with a username and password, not an application registered with a provider.
 * A Microsoft deployment will eventually not need it at all, since `Mail.Send` on
 * the same connection sends invitations without any of this.
 */
const CATALOGUE: Integration[] = [
  {
    key: 'smtp',
    name: 'Email',
    category: 'Notifications',
    summary:
      'Sends invitations and password reset links — through Microsoft 365 or your own mail server. Without it they still work: an admin copies the link and hands it over.',
    Logo: MailLogo,
    available: true,
  },
];

export default function Integrations() {
  const [sso, setSso] = useState<SsoSettings | null>(null);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [connectors, setConnectors] = useState<ConnectorOption[]>([]);
  // Snowflake is set up in a dialog on this page rather than in the wizard: its
  // setup is a credential for the whole deployment plus a list of queries.
  const [warehouseOpen, setWarehouseOpen] = useState(false);
  //: **A connected warehouse is an integration before it has a single query.**
  //: Grouping is by data source, so Snowflake stayed under "Available" — beside
  //: the things nobody has set up — right up until the first query existed. The
  //: credential is the connection; the queries are what it powers.
  const [warehouse, setWarehouse] = useState<WarehouseStatus | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  //: What the Microsoft Teams card says about itself. Asked separately and
  //: silently: an organization that never uses Teams gets no red box.
  const [teams, setTeams] = useState<{ enabled: boolean; channels: number; linked: number } | null>(
    null,
  );
  //: How many Slack channels are posting — the Slack card's status.
  const [slack, setSlack] = useState<number | null>(null);
  const loadSlack = () =>
    api<{ destinations: { enabled: boolean }[] }>('/api/announcements/destinations?kind=slack')
      .then((found) => setSlack(found.destinations.filter((d) => d.enabled).length))
      .catch(() => setSlack(null));
  //: The Email card's status line: which way mail goes, if any.
  const [mail, setMail] = useState<{ microsoft: string | null; smtp: boolean } | null>(null);

  const loadTeams = () =>
    Promise.all([
      api<{ enabled: boolean; destinations: { enabled: boolean }[] }>(
        '/api/announcements/destinations?kind=teams',
      ).catch(() => null),
      api<{ sources: { link: unknown }[] }>('/api/admin/directory/mirror').catch(() => null),
    ]).then(([posting, mirror]) =>
      setTeams({
        enabled: !!posting?.enabled,
        channels: posting ? posting.destinations.filter((d) => d.enabled).length : 0,
        linked: mirror ? mirror.sources.filter((s) => s.link).length : 0,
      }),
    );

  const loadMail = () =>
    Promise.all([
      directory.status().catch(() => null),
      api<SmtpSettings>('/api/admin/smtp').catch(() => null),
    ]).then(([tenant, smtp]) =>
      setMail({
        microsoft: tenant?.mail_enabled && tenant.mail_from ? tenant.mail_from : null,
        smtp: !!(smtp?.enabled && smtp.usable),
      }),
    );

  // Everything the Microsoft 365 box can switch shows up on these cards too.
  const reloadAll = () => {
    void load();
    void loadTeams();
    void loadMail();
    void loadSlack();
  };

  const load = () =>
    // Only what is running: the API leaves out drafts and removed sources, so the
    // page has nothing to filter and cannot disagree with the API about what
    // counts as active.
    Promise.all([
      api<SsoSettings>('/api/admin/sso'),
      dataSources.list(),
      dataSources.connectors(),
      dataSources.providers(),
      // Silent on failure: a deployment that never touches a warehouse is not an
      // error worth a red box on the integrations page.
      warehouseApi.read().catch(() => null),
    ])
      .then(([settings, list, available, registrations, wh]) => {
        setSso(settings);
        setSources(list);
        setConnectors(available);
        setProviders(registrations);
        setWarehouse(wh);
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load.'),
      );

  useEffect(() => {
    reloadAll();
  }, []);

  return (
    <>
      <PageHeader
        title="Integrations"
        description="Connect the systems your people and performance data already live in."
        actions={
          // One button rather than help text scattered through the wizard. The
          // wizard's own hints answer "what goes in this box"; this answers
          // "where do I get it", which is a different question asked in a
          // different place — usually somebody else's admin console.
          <Link
            to="/integrations/help"
            className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Need help?
          </Link>
        }
      />

      {/* Said once, at the top, because it is the thing most likely to
          surprise someone: these are not per-user connections. */}
      <p className="mb-6 rounded-md border border-edge bg-surface px-3 py-2 text-sm text-content-muted">
        Everything here is shared by the whole organization, not by you.
        Whatever account is used to connect is the account GoalGetter keeps
        using, for everyone.
      </p>

      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}

      <DataSources
        sources={sources}
        connectors={connectors}
        warehouse={warehouse}
        onOpenWarehouse={() => setWarehouseOpen(true)}
      />

      {warehouseOpen && (
        <SnowflakePanel
          sources={sources ?? []}
          onClose={() => {
            setWarehouseOpen(false);
            // Connecting or disconnecting in there changes whether Snowflake
            // belongs in the list above.
            void load();
          }}
        />
      )}

      <Connections providers={providers} sso={sso} onOpen={setOpen} />

      <Section title="Messaging and notifications">
        {/* **Its own card, not a section of the Microsoft 365 connection.**
            Posting to a channel needs no app registration, and organising
            people by their Teams had grown into three screens of its own. */}
        <Card
          integration={{
            key: 'teams',
            name: 'Microsoft Teams',
            category: 'Messaging',
            summary: !teams?.enabled
              ? 'Post wins into Teams channels, and use your Teams and channels as teams and offices. Switch it on in Microsoft 365.'
              : teams && (teams.channels > 0 || teams.linked > 0)
                ? [
                    teams.channels > 0 &&
                      `Posting to ${teams.channels} ${teams.channels === 1 ? 'channel' : 'channels'}.`,
                    teams.linked > 0 &&
                      `${teams.linked} ${teams.linked === 1 ? 'Team or channel' : 'Teams and channels'} in use as teams or offices.`,
                  ]
                    .filter(Boolean)
                    .join(' ')
                : 'Post wins into Teams channels, and use your Teams and channels as teams and offices.',
            Logo: TeamsLogo,
            available: true,
          }}
          connected={!!teams?.enabled}
          onOpen={() => setOpen('teams')}
        />
        <Card
          integration={{
            key: 'slack',
            name: 'Slack',
            category: 'Messaging',
            summary: slack
              ? `Posting to ${slack} ${slack === 1 ? 'channel' : 'channels'}.`
              : 'Post wins into Slack channels, through an incoming webhook per channel.',
            Logo: SlackLogo,
            available: true,
          }}
          connected={!!slack}
          onOpen={() => setOpen('slack')}
        />
        {CATALOGUE.map((integration) => (
          <Card
            key={integration.key}
            integration={{
              ...integration,
              summary: mail?.microsoft
                ? `Sending through Microsoft 365, from ${mail.microsoft}.`
                : mail?.smtp
                  ? 'Sending through your mail server.'
                  : integration.summary,
            }}
            connected={!!(mail?.microsoft || mail?.smtp)}
            onOpen={() => setOpen(integration.key)}
          />
        ))}
      </Section>

      {providers.map(
        (provider) =>
          open === provider.provider && (
            <ConnectionPanel
              key={provider.provider}
              provider={provider}
              sso={sso}
              onClose={() => setOpen(null)}
              onSaved={(saved) =>
                setProviders((all) =>
                  all.map((p) => (p.provider === saved.provider ? saved : p)),
                )
              }
              onSso={(saved) => setSso(saved)}
              onReload={reloadAll}
              onOpenTeams={() => setOpen('teams')}
              onOpenEmail={() => setOpen('smtp')}
            />
          ),
      )}

      {open === 'smtp' && (
        <EmailPanel
          microsoft={providers.find((p) => p.provider === 'microsoft')}
          onClose={() => {
            setOpen(null);
            void loadMail();
          }}
        />
      )}
      {open === 'slack' && (
        <Modal
          title="Slack"
          description="Post wins into Slack channels. Each channel is added with its own incoming webhook link — no app registration needed."
          onClose={() => {
            setOpen(null);
            void loadSlack();
          }}
          wide
        >
          <TeamsSettings kind="slack" />
        </Modal>
      )}
      {open === 'teams' && (
        <TeamsIntegration
          onClose={() => {
            setOpen(null);
            void loadTeams();
          }}
          onOpenMicrosoft={() => setOpen('microsoft')}
        />
      )}
    </>
  );
}

/**
 * Where the performance numbers come from.
 *
 * First on the page, and a list rather than a catalogue, because these are
 * *instances*: an organization can have three webhooks feeding three metrics,
 * where it has exactly one Microsoft connection. Each row is a link to that
 * source's own page — there is far more to say about one than fits here.
 */
/**
 * Where the performance numbers come from.
 *
 * First on the page, and it shows **only what is actually running**. Two things
 * are deliberately absent, and the API leaves them out rather than the page
 * filtering them:
 *
 * **Drafts** — connect flows nobody finished. Cancelling deletes one outright, and
 * anything abandoned another way is swept within a day. A half-built source
 * imports nothing, so listing it turns an abandoned click into a chore.
 *
 * **Removed** — their rows survive so their facts can still say where they came
 * from, but they are finished business. A source page still loads by URL, so
 * nothing is stranded; it just is not in the way.
 *
 * Underneath, the connectors that could be added. A list of what you have plus a
 * grid of what you could have is the shape every integrations page settles on,
 * because "what else can this talk to?" is the other question people arrive with.
 */
function DataSources({
  sources,
  connectors,
  warehouse,
  onOpenWarehouse,
}: {
  sources: Source[] | null;
  connectors: ConnectorOption[];
  /** The warehouse connection, which is an integration before it has queries. */
  warehouse: WarehouseStatus | null;
  onOpenWarehouse: () => void;
}) {
  //: Connected, but with nothing hanging off it yet. Rendered as its own group
  //: so the card sits with the things that *are* set up rather than under
  //: "Available" — where it read as untouched, and the way back to add a query
  //: was to press "Connect" on something already connected.
  const connectedWarehouse =
    warehouse?.connected === true &&
    !(sources ?? []).some((source) => source.connector === 'snowflake');

  // Whose files the spreadsheets are read as, for the Excel group's header. One
  // request for the page rather than one per row, and silent on failure: a
  // deployment with no Microsoft connection is not an error worth a red box on
  // the data sources list.
  const [excel, setExcel] = useState<ExcelStatus | null>(null);
  useEffect(() => {
    excelApi
      .status()
      .then(setExcel)
      .catch(() => setExcel(null));
  }, []);

  // One moment for the whole list, so twenty rows are judged against the same
  // clock rather than each calling `new Date()` a millisecond apart.
  const now = new Date();
  const live = sources ?? [];

  return (
    <section className="mb-10">
      <h2 className="text-h2 text-content">Data sources</h2>
      <p className="mt-1 mb-4 text-sm text-content-muted">
        Where your performance numbers come from. Everything on a leaderboard,
        goal or competition is imported from one of these.
      </p>

      {sources === null ? (
        <Loading />
      ) : live.length === 0 && !connectedWarehouse ? (
        <p className="rounded-lg border border-dashed border-edge px-4 py-6 text-sm text-content-muted">
          Nothing connected yet. Until something is, the only numbers in
          GoalGetter are the ones typed in by hand — pick something below to
          start.
        </p>
      ) : (
        /* **Grouped by connector, one group per integration.** Four spreadsheets
           used to be four loose cards all called Microsoft Excel, each looking
           like a separate connection — when there is one Microsoft connection,
           one signed-in account, and four sheets inside it.

           The sheets stay separate rows on purpose. Per-source health is what
           somebody opens this page for, and one collapsed row would hide "Q3
           Pipeline has been failing for three days" behind a click. */
        <div className="space-y-5">
          {connectedWarehouse && (
            <div className="overflow-hidden rounded-lg border border-edge bg-surface">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                <ConnectorMark connector="snowflake" className="size-6" />
                <div className="min-w-40 flex-1">
                  <p className="font-medium text-content">Snowflake</p>
                  <p className="text-xs text-content-subtle">
                    Connected to {warehouse?.account} — no queries yet
                  </p>
                </div>
                <button
                  type="button"
                  onClick={onOpenWarehouse}
                  className="shrink-0 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
                >
                  Add a query
                </button>
              </div>
            </div>
          )}

          {groupSources(live).map((group) => (
            <div
              key={group.connector}
              className="overflow-hidden rounded-lg border border-edge bg-surface"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-edge px-4 py-3">
                <ConnectorMark connector={group.connector} className="size-6" />
                <div className="min-w-40 flex-1">
                  <p className="font-medium text-content">
                    {group.connector_name}
                  </p>
                  <p className="text-xs text-content-subtle">
                    {group.sources.length}{' '}
                    {group.connector === 'microsoft_excel' ||
                    group.connector === 'google_sheets'
                      ? group.sources.length === 1
                        ? 'spreadsheet'
                        : 'spreadsheets'
                      : group.sources.length === 1
                        ? 'source'
                        : 'sources'}
                    {excel &&
                    group.connector === 'microsoft_excel' &&
                    excel.connected
                      ? ` · reading as ${excel.connected_as}`
                      : ''}
                  </p>
                </div>
                {/* **The whole point of the grouping.** Adding the second
                    spreadsheet is now one press from the list of the first,
                    rather than a trip back through the connector gallery. */}
                {acceptsMore(group.connector) && (
                  <Link
                    to={`/integrations/connect?connector=${group.connector}`}
                    className="shrink-0 rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover"
                  >
                    {addLabel(group.connector)}
                  </Link>
                )}
              </div>

              <ul className="divide-y divide-edge">
                {group.sources.map((source) => {
                  const health = sourceHealth(source, now);
                  const sheet = worksheetOf(source);
                  return (
                    <li key={source.id}>
                      <Link
                        to={
                          // A source that needs reconnecting goes back to the
                          // flow that would finish it, rather than to a page of
                          // empty sections.
                          health.resumable
                            ? `/integrations/connect/${source.id}`
                            : `/integrations/sources/${source.id}`
                        }
                        className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-surface-hover"
                      >
                        <div className="min-w-40 flex-1">
                          <p className="font-medium text-content">
                            {/* A source made before the wizard was fixed is
                                still called by its connector's key —
                                "microsoft_excel" — so say what it is instead
                                (review #10). Renaming it is still the fix. */}
                            {source.name === source.connector
                              ? group.connector_name
                              : source.name}
                          </p>
                          <p className="text-xs text-content-subtle">
                            {/* The tab, because four sources off one workbook
                                differ only by tab — without it they are four
                                identical rows. */}
                            {sheet && `“${sheet}” · `}
                            {source.mappings.length > 0
                              ? source.mappings
                                  .map((m) => m.metric_name)
                                  .join(', ')
                              : 'nothing mapped yet'}
                          </p>
                        </div>
                        <div className="min-w-0 flex-[2]">
                          <SourceHealthPill
                            source={source}
                            now={now}
                            withDetail
                          />
                        </div>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}

      <AddSource
        connectors={connectors}
        // A connected warehouse counts, or the heading below reads "Available"
        // under a card that is plainly already connected.
        many={live.length > 0 || connectedWarehouse}
        onOpenWarehouse={onOpenWarehouse}
      />
    </section>
  );
}

/**
 * What else this build can connect to.
 *
 * A card per connector rather than one "Connect a source" button, because the
 * button hides the answer to "does it work with our CRM?" behind a click — which
 * is the question people arrive on this page holding.
 *
 * Links rather than buttons, because this is a page somebody browses: a connector
 * is worth opening in a new tab, and a middle click should do what it does
 * everywhere else.
 */
function AddSource({
  connectors,
  many,
  onOpenWarehouse,
}: {
  connectors: ConnectorOption[];
  many: boolean;
  /** Snowflake is set up in a dialog on this page rather than in the wizard. */
  onOpenWarehouse: () => void;
}) {
  if (connectors.length === 0) return null;

  return (
    <div className="mt-6 border-t border-edge pt-6">
      {/* Stronger than the picker's own group headings, which use the subtle
          uppercase caption. Two headings in identical styling, one nested inside
          the other, reads as two lists rather than a list and its sections. */}
      <h3 className="mb-4 font-medium text-content">
        {many ? 'Add another' : 'Available'}
      </h3>
      {/* **Snowflake opens in place; everything else starts a wizard.** Its
          setup is a credential for the whole deployment plus a list of queries —
          a dialog, not a page — and making it a link to somewhere it never goes
          would break the back button for the sake of a consistency nobody asked
          for. See `ConnectorPicker`. */}
      <ConnectorPicker
        connectors={connectors}
        to={(key) =>
          key === 'snowflake' ? null : `/integrations/connect?connector=${key}`
        }
        onChoose={(key) => {
          if (key === 'snowflake') onOpenWarehouse();
        }}
      />
    </div>
  );
}

/**
 * What this deployment is connected to, and what each connection powers.
 *
 * **One card per provider, not one per feature.** There used to be two places on
 * this page offering to set up Microsoft: a "Provider sign-ins" row for the app
 * registration a connector needs, and a "Microsoft 365" card for single sign-on.
 * They were the same Entra app registration, and neither said so — an admin
 * created it once and pasted the same client id and secret into both forms.
 *
 * Now the credential is the connection, and signing in, reading spreadsheets and
 * syncing people are things it powers. The checklist on each card doubles as the
 * explanation of what connecting is *for*, which is the question somebody arrives
 * at this section holding.
 */
function Connections({
  providers,
  sso,
  onOpen,
}: {
  providers: Provider[];
  sso: SsoSettings | null;
  onOpen: (key: string) => void;
}) {
  if (providers.length === 0) return null;

  return (
    <section className="mb-10">
      <h2 className="text-h2 text-content">Connections</h2>
      <p className="mt-1 mb-4 text-sm text-content-muted">
        Set up once for the whole deployment. One application per provider
        covers everything below it — signing in, reading data, and anything
        added later.
      </p>

      <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(20rem,1fr))]">
        {providers.map((provider) => (
          <ConnectionCard
            key={provider.provider}
            provider={provider}
            sso={sso}
            onOpen={() => onOpen(provider.provider)}
          />
        ))}
      </div>
    </section>
  );
}

function ConnectionCard({
  provider,
  sso,
  onOpen,
}: {
  provider: Provider;
  sso: SsoSettings | null;
  onOpen: () => void;
}) {
  const connected = provider.client_secret_set;

  return (
    <div className="flex flex-col rounded-lg border border-edge bg-surface p-5">
      <div className="flex items-start gap-3">
        <ConnectorMark connector={provider.provider} className="size-8" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-content">
            {provider.provider_name}
          </p>
          {/* Not the tenant's GUID on the card: it is an identifier for
              support, not something anybody reads (review #10). It is in
              the connection's Details. */}
          {provider.tenant_id && (
            <p className="truncate text-xs text-content-subtle">Your organization&rsquo;s tenant</p>
          )}
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
            connected
              ? 'bg-success/15 text-success'
              : 'bg-surface-hover text-content-subtle'
          }`}
        >
          {connected ? 'Connected' : 'Not connected'}
        </span>
      </div>

      {/* The list is the reason to connect, so it is shown whether or not the
          connection exists yet — an unconnected card that said nothing about what
          it unlocks would be a card nobody has a reason to click. */}
      <ul className="mt-4 flex-1 space-y-1.5 text-sm">
        {provider.capabilities.map((capability) => (
          <li
            key={capability.key}
            className={`flex items-start gap-2 ${
              capability.active ? 'text-content' : 'text-content-subtle'
            }`}
            title={capability.detail}
          >
            <span aria-hidden className="mt-px w-4 shrink-0 text-center">
              {capability.active ? '✓' : '○'}
            </span>
            <span className="min-w-0">
              {capability.name}
              {!capability.built && (
                <span className="ml-1.5 text-xs text-content-subtle">
                  · coming soon
                </span>
              )}
              {capability.key === 'sso' &&
                capability.active &&
                sso?.require_sso && (
                  <span className="ml-1.5 text-xs text-content-subtle">
                    · required
                  </span>
                )}
            </span>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={onOpen}
        className={`mt-4 w-full rounded-md px-3 py-2 text-sm font-medium transition-colors ${
          connected
            ? 'border border-edge text-content-muted hover:bg-surface-hover hover:text-content'
            : 'bg-brand text-white hover:bg-brand-hover'
        }`}
      >
        {connected ? 'Settings' : 'Connect'}
      </button>
    </div>
  );
}

/**
 * One connection, opened.
 *
 * The credential form, and — for a provider that can sign people in — the sign-in
 * settings underneath it. Together in one panel because they are one connection:
 * splitting them is what produced two half-configured Microsofts in the first
 * place.
 */
function ConnectionPanel({
  provider,
  sso,
  onClose,
  onSaved,
  onSso,
  onReload,
  onOpenTeams,
  onOpenEmail,
}: {
  provider: Provider;
  sso: SsoSettings | null;
  onClose: () => void;
  onSaved: (saved: Provider) => void;
  onSso: (saved: SsoSettings) => void;
  onReload: () => void;
  onOpenTeams: () => void;
  onOpenEmail: () => void;
}) {
  const signsIn = provider.capabilities.some((c) => c.key === 'sso');

  // Only once there is a credential to use, and only for a capability that
  // actually ships — a panel unlocking nothing is a panel somebody spends an
  // afternoon on. Asked per capability rather than for the pair, because they are
  // separate panels now and a deployment that syncs but never sends mail should
  // not be shown an empty one.
  const has = (key: string) =>
    provider.client_secret_set &&
    provider.capabilities.some((c) => c.key === key && c.built);

  return (
    <Modal
      title={provider.provider_name}
      description={
        provider.used_by.length > 0
          ? `Used by ${provider.used_by.join(', ')}.`
          : 'One application for everything this connection powers.'
      }
      onClose={onClose}
      wide
    >
      <ProviderSetup
        provider={provider}
        compact
        onForgotten={() => {
          onClose();
          onReload();
        }}
        onSaved={(saved) => {
          onSaved(saved);
          // The capability list is derived server-side, so it can change as a
          // result of saving — a Microsoft connection that just gained a tenant
          // can now sign people in.
          onReload();
        }}
      />

      {/* **One stack of equals, in the order a deployment meets them.** Sign in
          first because it is what everybody notices; the sync next because it is
          what fills the product with people; mail last because most deployments
          never switch it on. Each is collapsed once it is working, so a finished
          connection is four short rows rather than a page of settings. */}
      <div className="mt-4 space-y-3">
        {signsIn && sso && (
          <SignInSettings
            provider={provider}
            settings={sso}
            onSaved={(saved) => {
              onSso(saved);
              onReload();
            }}
          />
        )}

        {/* Google has no tenant sync or mail here, so its data capability stands
            alone rather than travelling with them. */}
        {provider.provider === 'google' && has('data') && (
          <SheetsSettings provider={provider} />
        )}

        {(has('directory') || has('email') || has('data')) && (
          <TenantFeatures
            provider={provider}
            syncs={has('directory')}
            mails={has('email')}
            onOpenEmail={onOpenEmail}
            onChanged={onReload}
            between={
              provider.provider === 'microsoft' && has('data') ? (
                <ExcelSettings provider={provider} />
              ) : null
            }
          />
        )}

        {/* **Switched here, set up in its own card** — like Email. Shown whether
            or not the connection above is set up: a channel can be reached
            through a Workflows link, which needs no app registration. */}
        {provider.provider === 'microsoft' && (
          <TeamsSwitch onOpen={onOpenTeams} onChanged={onReload} />
        )}
      </div>
    </Modal>
  );
}

/**
 * Everything Snowflake, behind the Snowflake card.
 *
 * **One door.** This was briefly a *Warehouse* section sitting open on the
 * integrations page, above the data sources — which put a six-field credential
 * form permanently in front of every deployment, including the ones that will
 * never touch a warehouse. The connector card is where somebody goes looking for
 * Snowflake, so it is where Snowflake lives.
 *
 * Inside, the same two-part shape as the Microsoft dialog: the **connection**
 * first, because nothing can be tested without it, and then the **queries** that
 * run against it. Each query is a real data source with its own schedule and its
 * own health — the list here is a summary and a way through, not a second place
 * to manage them.
 */
function SnowflakePanel({
  sources,
  onClose,
}: {
  sources: Source[];
  onClose: () => void;
}) {
  const [status, setStatus] = useState<WarehouseStatus | null>(null);

  useEffect(() => {
    warehouseApi
      .read()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  const queries = sources.filter((s) => s.connector === 'snowflake');
  const now = new Date();

  return (
    <Modal
      title="Snowflake"
      description="Connect once, then add a query for each table or view you want measured."
      onClose={onClose}
      wide
    >
      {status === null ? (
        <Loading />
      ) : !status.available ? (
        <p className="rounded-md border border-warning px-3 py-2 text-sm text-warning">
          This build does not ship the Snowflake driver, so a connection here
          could never run. Rebuild the API image with{' '}
          <code>--build-arg API_EXTRAS=&quot;[snowflake]&quot;</code>.
        </p>
      ) : (
        <div className="space-y-4">
          {/* **Numbered, because the two-step shape is the whole point.** Every
              other tool asks for the account, the key, the warehouse *and* the
              query on one form, once per table — six answers repeated for the
              second query and five chances to disagree about which warehouse is
              meant. Saying "once" and "each" out loud is what makes the second
              query feel like two fields instead of a form. */}
          <div>
            <p className="text-sm font-medium text-content">
              1. Connect the warehouse
              <span className="ml-2 text-xs font-normal text-content-subtle">
                once for the whole deployment
              </span>
            </p>
            <div className="mt-2">
              <WarehouseSetup onConnected={setStatus} compact canDisconnect />
            </div>
          </div>

          {/* **Shown before it can be used, dimmed, rather than hidden.** It
              used to appear only once connected, which meant the dialog opened
              as a bare six-field credential form with nothing saying what the
              credential was *for* — somebody could fill in an account identifier
              without ever seeing that the point of it is queries. Greyed-out
              says "this is next"; absent says "this is everything". */}
          <div className={status.connected ? undefined : 'opacity-60'}>
            <p className="text-sm font-medium text-content">
              2. Add a query
              <span className="ml-2 text-xs font-normal text-content-subtle">
                {status.connected
                  ? 'one per table or view'
                  : 'once the connection above is made'}
              </span>
            </p>
            {!status.connected ? (
              <div className="mt-2 rounded-lg border border-dashed border-edge p-4">
                <p className="text-sm text-content-muted">
                  Each query becomes a data source with its own schedule and
                  health. Nothing is read until you write one.
                </p>
              </div>
            ) : (
              <div className="mt-2 rounded-lg border border-edge bg-surface p-4">
                <p className="text-sm text-content">
                  {queries.length === 0
                    ? 'Nothing yet.'
                    : `${queries.length} ${queries.length === 1 ? 'query' : 'queries'}.`}{' '}
                  <span className="text-content-muted">
                    Each becomes a data source with its own schedule and health.
                  </span>
                </p>

                {queries.length > 0 && (
                  <ul className="mt-3 divide-y divide-edge rounded-md border border-edge">
                    {queries.map((source) => (
                      <li key={source.id}>
                        <Link
                          to={`/integrations/sources/${source.id}`}
                          onClick={onClose}
                          className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2 transition-colors hover:bg-surface-hover"
                        >
                          <span className="min-w-32 flex-1">
                            <span className="block truncate text-sm text-content">
                              {source.name}
                            </span>
                            <span className="block truncate text-xs text-content-subtle">
                              {source.mappings.length > 0
                                ? source.mappings
                                    .map((m) => m.metric_name)
                                    .join(', ')
                                : 'nothing mapped yet'}
                            </span>
                          </span>
                          <SourceHealthPill source={source} now={now} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="mt-4 border-t border-edge pt-4">
                  <Link
                    to="/integrations/connect?connector=snowflake"
                    onClick={onClose}
                    className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
                  >
                    {queries.length === 0
                      ? 'Write the first query'
                      : 'Add another query'}
                  </Link>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-caption uppercase tracking-wide text-content-subtle">
        {title}
      </h2>
      {/* auto-fill with a minimum, not a fixed column count: the tiles stay a
          sensible width on an ultrawide monitor instead of stretching to half
          a metre each. */}
      <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(17rem,1fr))]">
        {children}
      </div>
    </section>
  );
}

function Card({
  integration,
  connected,
  onOpen,
}: {
  integration: Integration;
  connected: boolean;
  onOpen: () => void;
}) {
  const { name, category, summary, Logo, available } = integration;

  return (
    <div className="flex flex-col rounded-lg border border-edge bg-surface p-5">
      <div className="flex items-start gap-3">
        <Logo className="size-8 text-content-muted" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-content">{name}</p>
          <p className="text-xs text-content-subtle">{category}</p>
        </div>
        {connected && (
          <span className="shrink-0 rounded-full bg-success/15 px-2 py-0.5 text-xs text-success">
            Connected
          </span>
        )}
      </div>

      <p className="mt-3 flex-1 text-sm text-content-muted">{summary}</p>

      <div className="mt-4">
        {connected ? (
          // A cog rather than "Disconnect": the destructive action lives
          // inside the panel, behind the settings it might destroy.
          <button
            onClick={onOpen}
            aria-label={`${name} settings`}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            <CogIcon className="size-4" />
            Settings
          </button>
        ) : (
          <button
            onClick={onOpen}
            disabled={!available}
            title={available ? undefined : 'Not built yet'}
            className="w-full rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            {available ? 'Connect' : 'Coming soon'}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * The Exchange command that scopes `Mail.Send` to one mailbox.
 *
 * A function rather than a literal in the JSX because PowerShell's line
 * continuation is a backtick, and a backtick inside a template literal has to be
 * escaped — which is exactly the sort of thing that survives a copy-paste as a
 * stray backslash and then fails in somebody's console.
 */
function accessPolicyCommand(appId: string, mailbox: string): string {
  const tick = '`';
  return [
    `New-ApplicationAccessPolicy ${tick}`,
    `  -AppId ${appId} ${tick}`,
    `  -PolicyScopeGroupId ${mailbox} ${tick}`,
    `  -AccessRight RestrictAccess ${tick}`,
    '  -Description "GoalGetter sends as this mailbox only"',
  ].join('\n');
}

/**
 * One capability of a connection, opened only when you want it.
 *
 * **Every section of the settings dialog has the same anatomy**, and that is the
 * whole point of the component. Before it, three sibling sections were three
 * different shapes: one card with disclosures, one form ending in a button row
 * halfway down the dialog, and one stack of switches with a fourth section nested
 * inside it. Reading the dialog meant re-learning where things were each time,
 * and the Save belonging to the middle section looked like it belonged to the
 * dialog.
 *
 * Now: a title, what it does in one line, whether it is on, and — collapsed —
 * nothing else. Anything that has to be committed sits in a footer at the bottom
 * of its own section, so a button is never ambiguous about what it saves.
 *
 * **Open when it is off, collapsed when it is on.** A section that is off is
 * either unfinished or deliberately unused, and both are worth seeing; one that
 * is working has nothing to say until it is asked.
 */
function SettingsPanel({
  title,
  summary,
  on,
  children,
}: {
  title: string;
  summary: string;
  on: boolean;
  children: ReactNode;
}) {
  // **The initial state only, and deliberately so.** Bound straight to `on`, a
  // panel would collapse under the hand that flipped a switch inside it: turning
  // sync on re-renders with `on` true, and React re-applies the attribute. So the
  // prop decides how it opens and the reader decides everything after that.
  const [open, setOpen] = useState(!on);

  return (
    <details
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="group rounded-lg border border-edge bg-surface"
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
        <ChevronDownIcon
          aria-hidden
          className="size-4 shrink-0 -rotate-90 text-content-subtle transition-transform group-open:rotate-0"
        />
        <div className="min-w-0 flex-1">
          <p className="font-medium text-content">{title}</p>
          <p className="truncate text-sm text-content-muted">{summary}</p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
            on
              ? 'bg-success/15 text-success'
              : 'bg-surface-hover text-content-subtle'
          }`}
        >
          {on ? 'On' : 'Off'}
        </span>
      </summary>
      <div className="border-t border-edge px-5 py-4">{children}</div>
    </details>
  );
}

function PanelFooter({ children }: { children: ReactNode }) {
  return (
    <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-edge pt-4">
      {children}
    </div>
  );
}

/** Said once, in the sections that have no Save, so its absence is not a doubt. */
function SavesItself() {
  return (
    <p className="mt-4 text-xs text-content-subtle">
      Changes here save as you make them.
    </p>
  );
}

/**
 * Tenant user sync, and — separately — the account that sends mail.
 *
 * **Two features, and only one of them needs an account.** They were briefly one
 * section on the theory that both did. Reading a directory acts as the
 * application: the registration and its admin consent are the whole of it, and a
 * delegated version bought an expiry date and no security — the sync stopped when
 * whoever connected it left, months later, looking like an unrelated fault.
 *
 * Sending mail is the opposite. `Mail.Send` as an application permission grants
 * send-as for **every mailbox in the tenant**; the delegated shared version can
 * only send as mailboxes the connected account already holds *Send As* rights on.
 * There the account buys a real restriction, set in Exchange by the customer.
 *
 * **They are siblings now, not parent and child.** Mail used to be a disclosure
 * inside the sync section, which said mail was part of syncing — it is not, and a
 * deployment wanting one and not the other is the normal case. One component
 * still owns both because one request answers both: `directory.status()` carries
 * the sync settings and the mail settings together, and fetching it twice to draw
 * two boxes would be two chances to disagree.
 */
function TenantFeatures({
  provider,
  syncs,
  mails,
  between,
  onOpenEmail,
  onChanged,
}: {
  provider: Provider;
  /** Email is switched here and set up in the Email card. */
  onOpenEmail: () => void;
  /** Something the Microsoft 365 card ticks off changed. */
  onChanged: () => void;
  /** The directory capability ships, and there is a credential to use it with. */
  syncs: boolean;
  /** Likewise for sending mail. */
  mails: boolean;
  /**
   * Panels that belong between these two in reading order but cannot be owned by
   * this component, because they answer to a different status request. Excel is
   * the one — it is a data capability, not a property of the tenant connection,
   * so it has its own endpoint and its own account.
   */
  between?: ReactNode;
}) {
  const [status, setStatus] = useState<DirectoryStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = () =>
    directory
      .status()
      .then(setStatus)
      .catch(() => setStatus(null));

  useEffect(() => {
    void reload();
  }, []);

  if (status === null) return null;

  const syncing = status.enabled && status.provider === provider.provider;

  async function act(work: () => Promise<DirectoryStatus>) {
    setBusy(true);
    setError(null);
    try {
      setStatus(await work());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {syncs && (
        <SettingsPanel
          title="Tenant user sync"
          summary="Reads your directory on a schedule and stages people for approval."
          on={syncing}
        >
          {/* Which mode this connection was provisioned in, and what that means
              for the switches under it. Shown rather than assumed, because the
              two fail differently and a screen hiding the difference would make
              the failure unattributable. */}
          <p className="text-sm text-content-muted">
            Nobody gets an account without a decision.{' '}
            {status.auth_mode === 'delegated'
              ? 'This connection signs in as a service account; changing that means re-running the automatic setup, since the permissions differ.'
              : 'This connection runs as the application — nothing to sign in, nothing to expire.'}
          </p>

          {/* The delegated mode's one extra step, and the warning that matters
              more than the step: whoever signs in is what the sync becomes. */}
          {status.account_required && !status.account_connected && (
            <div className="mt-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
              <p className="text-sm text-content">
                Sign in the account this acts as
              </p>
              <p className="mt-1 mb-2 text-sm text-content-muted">
                <strong>Use a service account, not your own.</strong> Whatever
                signs in here is what the sync acts as from then on — your own
                account and it stops the day you leave. A licensed account
                nobody uses interactively is the right choice.
              </p>
              <AccountConnectButton
                provider={provider.provider}
                label="Sign in an account"
                onConnected={() => void reload()}
              />
            </div>
          )}

          {status.account_required && status.account_connected && (
            <p className="mt-4 rounded-md border border-success bg-success/5 px-3 py-2 text-sm text-content">
              <span aria-hidden>✓ </span>Acting as{' '}
              <strong>{status.connected_as || 'a signed-in account'}</strong>
              <button
                type="button"
                onClick={() =>
                  void act(() => directory.forgetAccount(provider.provider))
                }
                disabled={busy}
                className="ml-3 text-xs text-content-muted underline transition-colors hover:text-danger disabled:opacity-50"
              >
                sign out
              </button>
            </p>
          )}

          <div className="mt-4 space-y-3">
            <Toggle
              label="Enable tenant user sync"
              hint="Off, nothing is read and no accounts appear. On, people show up in Users → Directory sync waiting to be approved."
              checked={syncing}
              disabled={
                busy || (status.account_required && !status.account_connected)
              }
              onChange={(v) =>
                void act(() => directory.setEnabled(provider.provider, v))
              }
            />

            {/* **Not a preference — it decides who reaches the approval queue.**
                A tenant is full of accounts nobody signs in with, and a licence is
                the closest thing a directory has to "this person works here". For
                six hundred accounts it is the difference between a list somebody
                reads and one they wave through. */}
            {syncing && (
              <Toggle
                label="Ignore unlicensed accounts"
                hint="Skips accounts holding no Microsoft licence — service accounts, shared mailboxes, and leavers who were disabled rather than deleted. They never reach the approval queue."
                checked={status.ignore_unlicensed}
                disabled={busy}
                onChange={(v) =>
                  void act(() =>
                    directory.setEnabled(provider.provider, true, undefined, v),
                  )
                }
              />
            )}
          </div>

          {syncing && (
            <div className="mt-4 max-w-xs">
              <Select
                label="How often"
                value={String(status.sync_hours)}
                onChange={(v) =>
                  void act(() =>
                    directory.setEnabled(provider.provider, true, Number(v)),
                  )
                }
                options={[
                  { value: '1', label: 'Every hour' },
                  { value: '6', label: 'Every 6 hours' },
                  { value: '24', label: 'Daily — recommended' },
                  { value: '168', label: 'Weekly' },
                ]}
              />
            </div>
          )}

          {error && (
            <ErrorNote message={error} onDismiss={() => setError(null)} />
          )}

          <SavesItself />

          {syncing && (
            <>
              <PanelFooter>
                <Link
                  to="/users?tab=directory"
                  className="rounded-md border border-edge px-4 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
                >
                  Choose who syncs &rarr;
                </Link>
                {/* **Always offered, not saved for the error.** Reading a
                    directory needs Microsoft *app roles*, which some tenants
                    reserve to a Privileged Role Administrator — the setup presses
                    consent on the admin's behalf and says so when it could not.
                    Every deployment meets this once, and the fix is a link, so the
                    link lives on the page. */}
                {provider.client_id && provider.tenant_id && (
                  <a
                    href={`https://login.microsoftonline.com/${provider.tenant_id}/adminconsent?client_id=${provider.client_id}`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
                  >
                    Grant admin consent
                  </a>
                )}
              </PanelFooter>

              {provider.client_id && provider.tenant_id && (
                <p className="mt-3 text-xs text-content-subtle">
                  Reading your directory needs tenant-wide admin consent
                  {status.auth_mode === 'application'
                    ? ' from a Privileged Role Administrator'
                    : ''}
                  , once per directory. The automatic setup tries this for you;
                  if syncing returns a permission error, it could not.
                </p>
              )}
            </>
          )}
        </SettingsPanel>
      )}

      {syncing && (
        <SettingsPanel
          title="Offices and departments"
          summary="Sorts synced people into offices and teams by their Microsoft 365 office and department."
          on
        >
          <div className="px-5 pb-5">
            <M365Places />
          </div>
        </SettingsPanel>
      )}

      {between}

      {mails && (
        <MailSwitch
          provider={provider}
          status={status}
          onSaved={(saved) => {
            setStatus(saved);
            onChanged();
          }}
          onOpen={onOpenEmail}
        />
      )}
    </>
  );
}

/**
 * Which mailbox invitations and reset links come from.
 *
 * **One form, one Save, at the bottom.** This has now been through two worse
 * shapes. First a *Save address* button that appeared between the address and the
 * switch only once the field was dirty — so the form changed shape as you typed,
 * and the control committing your change sat between two that did not. Then three
 * numbered boxes with a button in each, which fixed the ambiguity by repeating it
 * three times.
 *
 * What it is instead: the address and the switch are edited freely and committed
 * together by one Save, because they are one decision — a mailbox nobody sends
 * from and sending with no mailbox are each half a setting. The test sits beside
 * that Save and is deliberately unavailable until it is pressed, since the server
 * sends from the *stored* address and testing an unsaved one would answer a
 * question nobody asked.
 *
 * **Nothing signs in for any of it.** Same application registration and client
 * credentials as the directory sync, so there is no host, port or password — which
 * also sidesteps SMTP AUTH, disabled by default in Microsoft tenants now.
 */
function MailSettings({
  provider,
  status,
  busy,
  onSaved,
  onBusy,
  onError,
}: {
  provider: Provider;
  status: DirectoryStatus;
  busy: boolean;
  onSaved: (status: DirectoryStatus) => void;
  onBusy: (busy: boolean) => void;
  onError: (error: string | null) => void;
}) {
  const [from, setFrom] = useState(status.mail_from);
  // Switched in the Microsoft 365 box; saving the mailbox keeps it as it is.
  const enabled = status.mail_enabled;
  const [to, setTo] = useState('');
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(
    null,
  );

  const dirty = from.trim() !== status.mail_from;
  // The server sends from what is stored, so a test only means anything once the
  // stored value is the one on screen.
  const testable = Boolean(status.mail_from) && !dirty;

  async function save() {
    onBusy(true);
    onError(null);
    setResult(null);
    try {
      onSaved(await directory.setMail(provider.provider, enabled, from.trim()));
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      onBusy(false);
    }
  }

  async function sendTest() {
    setTesting(true);
    setResult(null);
    try {
      setResult(await directory.testMail(provider.provider, to.trim()));
    } catch (e) {
      setResult({
        ok: false,
        detail: e instanceof Error ? e.message : 'Could not send that.',
      });
    } finally {
      setTesting(false);
    }
  }

  return (
    <SettingsPanel
      title="Through Microsoft 365"
      summary={
        status.mail_enabled
          ? `Sending from ${status.mail_from}.`
          : 'Sends from a mailbox in your tenant once it is switched on in Microsoft 365.'
      }
      on={status.mail_enabled}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <p className="text-sm text-content-muted">
          Goes through Microsoft instead of a mail server — no host, port or
          password. Without either, invitations and resets still work: an admin
          copies the link and hands it over.
        </p>

        <div className="mt-4 space-y-4">
          <Field
            label="Send as"
            value={from}
            onChange={setFrom}
            maxLength={320}
            placeholder="noreply@yourcompany.com"
            hint="A real mailbox in your tenant. An application has no mailbox of its own, so there is nothing to fall back to."
          />

          <p className="text-sm text-content-muted">
            {enabled
              ? 'Switched on in the Microsoft 365 box — invitations and resets are sent from the mailbox above.'
              : 'Switched off in the Microsoft 365 box. Save a mailbox here, then switch it on there.'}
          </p>

          <Field
            label="Send a test to"
            type="email"
            value={to}
            onChange={setTo}
            maxLength={320}
            placeholder="you@yourcompany.com"
            hint="Goes through Microsoft only — never the SMTP fallback, so a green result means this setting works. Try an outside address too; that is the delivery path most likely to be filtered."
          />
        </div>

        {result && (
          <p
            role="status"
            className={`mt-4 rounded-md border px-3 py-2 text-sm ${
              result.ok
                ? 'border-success text-success'
                : 'border-danger text-danger'
            }`}
          >
            {result.detail}
          </p>
        )}

        <PanelFooter>
          <button
            type="submit"
            disabled={busy || !dirty || (enabled && !from.trim())}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : dirty ? 'Save' : 'Saved'}
          </button>
          <button
            type="button"
            onClick={() => void sendTest()}
            disabled={testing || !testable || !to.trim()}
            title={
              testable
                ? undefined
                : 'Save a mailbox first — the test sends from the stored address.'
            }
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-50"
          >
            {testing ? 'Sending…' : 'Send test'}
          </button>
        </PanelFooter>

        {/* **Said plainly, because the alternative is a promise we cannot keep.**
            There is no narrower application permission for sending — the narrower
            one is delegated and needs an account, the trade this integration
            deliberately does not make. Exchange is where it gets scoped, so the
            command lives here rather than in a document nobody opens. */}
        {status.mail_enabled && status.mail_from && provider.client_id && (
          <div className="mt-4 rounded-md border border-warning/40 bg-warning/10 p-3">
            <p className="text-sm text-content">Restrict this to one mailbox</p>
            <p className="mt-1 text-sm text-content-muted">
              <code className="text-content">Mail.Send</code> lets this
              application send as <strong>any</strong> mailbox in your tenant
              until Exchange says otherwise. Run this once, as an Exchange
              administrator, to scope it to <strong>{status.mail_from}</strong>{' '}
              alone:
            </p>
            <pre className="mt-2 overflow-x-auto rounded bg-bg p-2 text-xs text-content">
              {accessPolicyCommand(provider.client_id, status.mail_from)}
            </pre>
            <p className="mt-2 text-xs text-content-subtle">
              Takes up to 30 minutes to apply. Microsoft is replacing
              Application Access Policies with RBAC for Applications — either
              scopes it, and this one works today.
            </p>
          </div>
        )}
      </form>
    </SettingsPanel>
  );
}

/**
 * Signing in with this connection.
 *
 * Its Save used to sit in the middle of the dialog, because this section sat in
 * the middle of the dialog and ended in a button row. It is the same button row;
 * what changed is that the section is a panel that collapses, so the row is
 * unambiguously the bottom of *this* and not the bottom of everything.
 */
function SignInSettings({
  provider,
  settings: initial,
  onSaved,
}: {
  provider: Provider;
  settings: SsoSettings;
  onSaved: (settings: SsoSettings) => void;
}) {
  const [settings, setSettings] = useState(initial);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);

  // Whether *this* connection is the one signing people in. A deployment has one
  // sign-in provider, so pointing it at Microsoft unpoints it from anything else.
  // Decided in `ssoSettings.ts`, which is where the bug that made this toggle
  // untickable is written down.
  const isSignIn = signsInWith(settings, provider.provider);

  function set<K extends keyof SsoSettings>(key: K, value: SsoSettings[K]) {
    setSettings((s) => ({ ...s, [key]: value }));
    setStatus(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const saved = await api<SsoSettings>('/api/admin/sso', {
        method: 'PUT',
        body: JSON.stringify({
          ...settings,
          // Enabling here means "sign in with this connection", so the provider
          // is implied by which panel the admin is standing in rather than being
          // a second choice they have to make.
          provider: settings.enabled ? provider.provider : settings.provider,
          // A row nobody filled in is not a rule.
          role_rules: (settings.role_rules ?? []).filter((rule) => rule.group.trim()),
        }),
      });
      setSettings(saved);
      onSaved(saved);
      setStatus('Saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setBusy(true);
    setTest(null);
    try {
      setTest(await api<TestResult>('/api/admin/sso/test', { method: 'POST' }));
    } catch (e) {
      setTest({
        ok: false,
        detail: e instanceof Error ? e.message : 'Test failed.',
        authorization_endpoint: null,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPanel
      title="Single sign-on"
      summary="Lets people sign in with their work account instead of a password here."
      on={isSignIn}
    >
      <form onSubmit={save}>
        {settings.issuer && isSignIn ? (
          <p className="text-sm text-content-muted">
            Signing in against{' '}
            <code className="text-content">{settings.issuer}</code>
          </p>
        ) : (
          <p className="text-sm text-content-muted">
            {provider.client_secret_set
              ? 'Turn this on to let people sign in with their work account instead of a password here.'
              : 'Connect this provider above first — signing in uses the same application.'}
          </p>
        )}

        <div className="mt-4 space-y-3">
          <Toggle
            label="Enable single sign-on"
            hint="Shows the sign-in button on the login page."
            checked={isSignIn}
            // Both fields move together. Setting `enabled` alone is what made this
            // box impossible to tick: the provider is half of what "on" means.
            onChange={(v) => {
              const next = flipSignIn(settings, provider.provider, v);
              setSettings((current) => ({ ...current, ...next }));
              setStatus(null);
            }}
          />
          <Toggle
            // **Not the tenant sync**, which is a different switch in a different
            // panel. This one is a property of signing in: it decides what happens
            // the moment somebody arrives with a work account nobody has invited.
            // Named after that moment, because "create accounts automatically"
            // read like the sync and got mistaken for it.
            label="Create an account on first sign-in"
            hint="Anyone in your tenant who signs in gets an agent account, immediately and with no review. Off by default — otherwise everyone gains access to performance data."
            checked={settings.auto_provision}
            onChange={(v) => set('auto_provision', v)}
          />
          <Toggle
            label="Require single sign-on"
            hint="People synced from your directory, and anybody who has signed in with Microsoft before, must use their company account. Admins keep password sign-in as the way back in if this is misconfigured, and people you set up by hand who have never used Microsoft — contractors, agencies — sign in with a password."
            checked={settings.require_sso}
            onChange={(v) => set('require_sso', v)}
          />
        </div>

        <div className="mt-4">
          <SsoRoleRules
            enabled={settings.role_sync}
            rules={settings.role_rules ?? []}
            onEnabled={(v) => set('role_sync', v)}
            onRules={(rules) => {
              set('role_rules', rules);
              // With nothing to match, it cannot be on.
              if (rules.length === 0) set('role_sync', false);
            }}
          />
        </div>

        <div className="mt-4">
          <Field
            label="Button label"
            value={settings.button_label}
            onChange={(v) => set('button_label', v)}
          />
        </div>

        {error && (
          <p
            role="alert"
            className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}
        {status && <p className="mt-4 text-sm text-success">{status}</p>}
        {test && (
          <p
            role="alert"
            className={`mt-4 rounded-md border px-3 py-2 text-sm ${
              test.ok
                ? 'border-success text-success'
                : 'border-danger text-danger'
            }`}
          >
            {test.detail}
          </p>
        )}

        <PanelFooter>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Working…' : 'Save'}
          </button>
          <button
            type="button"
            onClick={runTest}
            disabled={busy || !settings.connected}
            title={
              settings.connected
                ? undefined
                : 'Nothing to test until sign-in is set up'
            }
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-50"
          >
            Test connection
          </button>
        </PanelFooter>
      </form>
    </SettingsPanel>
  );
}

/**
 * Which account GoalGetter reads spreadsheets as, and which ones it reads.
 *
 * **One sign-in for the deployment, not one per spreadsheet.** Every Excel source
 * used to run its own authorization dance and store its own refresh token, so
 * connecting three workbooks meant signing in three times and produced three
 * credentials that expired independently — and when one died, the error named a
 * source rather than the account, so the fix was three clicks from the message.
 *
 * **The sign-in is not a choice we are making.** `Files.Read.All` sits on the
 * registration as a *delegated* permission, and a delegated permission only ever
 * appears in a token issued for a signed-in user. There is no app-only token that
 * carries it, so there is nothing to fall back to — and nothing to be clever
 * about.
 *
 * Which is also the access boundary, and a good one: GoalGetter can open exactly
 * the files that person can open. Nothing is granted tenant-wide, and revoking it
 * is one *Sign out* rather than an admin unpicking an app role.
 *
 * **The workbook list is here because "what are we pulling from?" is asked here.**
 * It used to be answerable only by going to the data sources list and reading
 * which ones happened to be Excel.
 */
function ExcelSettings({ provider }: { provider: Provider }) {
  const [status, setStatus] = useState<ExcelStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = () =>
    excelApi
      .status()
      .then(setStatus)
      .catch(() => setStatus(null));

  useEffect(() => {
    void reload();
  }, []);

  if (status === null || !status.registered) return null;

  async function signIn() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await excelApi.connect();
      const popup = window.open(url, 'gg_excel_oauth', 'width=520,height=680');
      if (!popup) {
        // Blocked. Navigating away is a worse experience but a working one, and
        // the callback handles both.
        window.location.assign(url);
        return;
      }
      await new Promise<void>((resolve) => {
        function onMessage(event: MessageEvent) {
          // Only our own origin, and only our own message: a popup opener can be
          // sent anything by anybody.
          if (event.origin !== window.location.origin) return;
          if (event.data?.source !== 'goalgetter-oauth') return;
          const problem = event.data.result?.error;
          if (problem) setError(String(problem));
          done();
        }
        // Closing the window is how somebody says no. Without this the button
        // sits on "Waiting…" for ever.
        const watch = window.setInterval(() => {
          if (popup.closed) done();
        }, 500);
        function done() {
          window.clearInterval(watch);
          window.removeEventListener('message', onMessage);
          resolve();
        }
        window.addEventListener('message', onMessage);
      });
      await reload();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Could not start that sign-in.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    if (
      !await ask(
        `Stop reading spreadsheets as ${status?.connected_as || 'this account'}?\n\n` +
          'The workbooks and their column mappings are kept — they stop updating ' +
          'until an account is signed in again.',
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await excelApi.forget();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not sign that out.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPanel
      title="Excel spreadsheets"
      summary="Reads workbooks on OneDrive and SharePoint as data sources."
      on={status.connected}
    >
      <p className="text-sm text-content-muted">
        One account for the whole deployment — sign in once and every workbook
        reads as it. GoalGetter can open exactly the files that person can open,
        and <strong>only ever reads</strong>: the permission it holds cannot
        create, change or delete anything.
      </p>

      {status.connected ? (
        <p className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-success bg-success/5 px-3 py-2 text-sm text-content">
          <span className="min-w-0 flex-1">
            <span aria-hidden>✓ </span>Reading files as{' '}
            <strong>{status.connected_as || 'a signed-in account'}</strong>
          </span>
          <button
            type="button"
            onClick={() => void signOut()}
            disabled={busy}
            className="shrink-0 text-xs text-content-muted underline transition-colors hover:text-danger disabled:opacity-50"
          >
            sign out
          </button>
        </p>
      ) : (
        <div className="mt-4 rounded-md border border-edge p-3">
          <p className="text-sm text-content">Choose whose files to read</p>
          <p className="mt-1 mb-3 text-sm text-content-muted">
            <strong>A service account is the safer choice.</strong> Whoever
            signs in here is what every workbook is read as, so a personal
            account means the spreadsheets stop the day that person leaves — and
            exposes everything else in their OneDrive to being picked.
          </p>
          <button
            type="button"
            onClick={() => void signIn()}
            disabled={busy}
            className="flex items-center gap-3 rounded-md border border-edge bg-surface px-4 py-2.5 text-sm font-medium text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            <ConnectorMark connector={provider.provider} className="size-5" />
            {busy
              ? 'Waiting for the sign-in window…'
              : 'Sign in with Microsoft'}
          </button>
        </div>
      )}

      {/* **A count and a way through, not a second place to manage them.**
          This listed every spreadsheet with its own actions, and so does the
          data sources list — the same things in two places with different
          affordances, which is the thing that feels unfinished however good
          either one is.

          So the split follows what each screen owns: this panel owns the
          *connection* — the account, and whether it works. The data sources list
          owns the *feeds*, because each sheet has its own health, its own
          schedule and its own pause, and that list's whole job is answering
          "what is feeding my leaderboards". */}
      <div className="mt-5 border-t border-edge pt-4">
        <p className="text-sm text-content">
          {status.workbooks.length === 0
            ? 'No spreadsheets connected yet'
            : `${status.workbooks.length} spreadsheet${
                status.workbooks.length === 1 ? '' : 's'
              } connected`}
        </p>
        <p className="mt-1 text-sm text-content-muted">
          Each one is a data source with its own schedule and its own health.
          They are managed together under Data sources.
        </p>

        {error && (
          <ErrorNote message={error} onDismiss={() => setError(null)} />
        )}

        <PanelFooter>
          <Link
            to="/integrations/connect?connector=microsoft_excel"
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              status.connected
                ? 'bg-brand text-white hover:bg-brand-hover'
                : 'pointer-events-none border border-edge text-content-subtle opacity-40'
            }`}
            aria-disabled={!status.connected}
          >
            Add a spreadsheet
          </Link>
          {status.workbooks.length > 0 && (
            <Link
              to="/integrations"
              className="text-sm text-brand hover:underline"
              onClick={() => window.scrollTo({ top: 0 })}
            >
              Manage spreadsheets &rarr;
            </Link>
          )}
          {!status.connected && (
            <span className="text-xs text-content-subtle">
              Sign an account in first — there is nothing to browse until then.
            </span>
          )}
        </PanelFooter>
      </div>
    </SettingsPanel>
  );
}

/**
 * Which Google account GoalGetter reads spreadsheets as, and which ones it reads.
 *
 * The Sheets twin of `ExcelSettings`, and the same shape for the same reasons:
 * one account for the deployment rather than one per spreadsheet, and this panel
 * owns the *connection* while the data sources list owns the *feeds*.
 *
 * **Two honest ways to be a robot, and the choice is worth making explicit.**
 * Signing in is two clicks and right for a Workspace company whose consent screen
 * is Internal — but the access belongs to whoever clicked, and stops when they
 * leave. A service account is a key plus sharing the sheet with its address; the
 * access belongs to the organization, and it sidesteps Google's review process
 * that a plain Gmail account runs into.
 *
 * Neither is a mode to pick from a dropdown: whichever credential is present is
 * the one used, matching what the connector has always done per source.
 */
function SheetsSettings({ provider }: { provider: Provider }) {
  const [status, setStatus] = useState<SheetsStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState('');
  const [pasting, setPasting] = useState(false);

  const reload = () =>
    sheetsApi
      .status()
      .then(setStatus)
      .catch(() => setStatus(null));

  useEffect(() => {
    void reload();
  }, []);

  if (status === null || !status.registered) return null;

  async function signIn() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await sheetsApi.connect();
      const popup = window.open(url, 'gg_sheets_oauth', 'width=520,height=680');
      if (!popup) {
        window.location.assign(url);
        return;
      }
      await new Promise<void>((resolve) => {
        function onMessage(event: MessageEvent) {
          if (event.origin !== window.location.origin) return;
          if (event.data?.source !== 'goalgetter-oauth') return;
          const problem = event.data.result?.error;
          if (problem) setError(String(problem));
          done();
        }
        const watch = window.setInterval(() => {
          if (popup.closed) done();
        }, 500);
        function done() {
          window.clearInterval(watch);
          window.removeEventListener('message', onMessage);
          resolve();
        }
        window.addEventListener('message', onMessage);
      });
      await reload();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Could not start that sign-in.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function saveKey() {
    setBusy(true);
    setError(null);
    try {
      await sheetsApi.useServiceAccount(key.trim());
      setKey('');
      setPasting(false);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read that key.');
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    if (
      !await ask(
        `Stop reading spreadsheets as ${status?.connected_as || 'this account'}?\n\n` +
          'The spreadsheets and their column mappings are kept — they stop ' +
          'updating until an account is connected again.',
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await sheetsApi.forget();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not sign that out.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPanel
      title="Google Sheets"
      summary="Reads spreadsheets on Google Drive as data sources."
      on={status.connected}
    >
      <p className="text-sm text-content-muted">
        One account for the whole deployment — connect once and every
        spreadsheet reads as it. GoalGetter can open exactly the sheets that
        account can open, and <strong>only ever reads</strong>: both permissions
        it holds are read-only and cannot change a cell.
      </p>

      {status.connected ? (
        <>
          <p className="mt-4 flex flex-wrap items-center gap-3 rounded-md border border-success bg-success/5 px-3 py-2 text-sm text-content">
            <span className="min-w-0 flex-1">
              <span aria-hidden>✓ </span>Reading as{' '}
              <strong>{status.connected_as || 'a connected account'}</strong>
              {status.service_account && (
                <span className="ml-2 rounded-full bg-surface-hover px-2 py-0.5 text-xs text-content-muted">
                  service account
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => void signOut()}
              disabled={busy}
              className="shrink-0 text-xs text-content-muted underline transition-colors hover:text-danger disabled:opacity-50"
            >
              disconnect
            </button>
          </p>

          {/* **The half of the setup a key alone does not do.** Google grants a
              service account exactly the files somebody has shared with it, so
              without this line the picker is empty and nothing says why. */}
          {status.service_account && (
            <p className="mt-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-content-muted">
              Share each spreadsheet with{' '}
              <strong className="text-content">{status.connected_as}</strong> —
              the ordinary Share button, exactly as with a colleague. Until you
              do, it can see nothing.
            </p>
          )}
        </>
      ) : (
        <div className="mt-4 space-y-3">
          {!pasting ? (
            <div className="rounded-md border border-edge p-3">
              <p className="text-sm text-content">Connect an account</p>
              <p className="mt-1 mb-3 text-sm text-content-muted">
                <strong>Signing in is the quick way</strong>, and right for a
                Workspace company. The access belongs to whoever clicks, so it
                stops the day they leave — a service account avoids that.
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void signIn()}
                  disabled={busy}
                  className="flex items-center gap-3 rounded-md border border-edge bg-surface px-4 py-2.5 text-sm font-medium text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
                >
                  <ConnectorMark
                    connector={provider.provider}
                    className="size-5"
                  />
                  {busy
                    ? 'Waiting for the sign-in window…'
                    : 'Sign in with Google'}
                </button>
                <button
                  type="button"
                  onClick={() => setPasting(true)}
                  className="text-sm text-content-muted underline transition-colors hover:text-content"
                >
                  Or use a service account
                </button>
              </div>
            </div>
          ) : (
            <div className="rounded-md border border-edge p-3">
              <p className="text-sm text-content">Use a service account</p>
              <p className="mt-1 mb-3 text-sm text-content-muted">
                A robot account with its own address. Paste the JSON key here,
                then share each spreadsheet with the address it gives you back.
                The access belongs to the organization rather than to a person,
                and it skips Google&rsquo;s review process.
              </p>
              <textarea
                value={key}
                onChange={(e) => setKey(e.target.value)}
                rows={4}
                placeholder='{ "type": "service_account", "client_email": "…", … }'
                className="w-full rounded-md border border-edge bg-bg px-3 py-2 font-mono text-xs text-content outline-none placeholder:text-content-subtle focus:border-brand"
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => void saveKey()}
                  disabled={busy || !key.trim()}
                  className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
                >
                  {busy ? 'Checking…' : 'Use this key'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPasting(false);
                    setError(null);
                  }}
                  className="text-sm text-content-muted underline transition-colors hover:text-content"
                >
                  Sign in instead
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="mt-5 border-t border-edge pt-4">
        <p className="text-sm text-content">
          {status.spreadsheets.length === 0
            ? 'No spreadsheets connected yet'
            : `${status.spreadsheets.length} spreadsheet${
                status.spreadsheets.length === 1 ? '' : 's'
              } connected`}
        </p>
        <p className="mt-1 text-sm text-content-muted">
          Each one is a data source with its own schedule and its own health.
          They are managed together under Data sources.
        </p>

        {error && (
          <ErrorNote message={error} onDismiss={() => setError(null)} />
        )}

        <PanelFooter>
          <Link
            to="/integrations/connect?connector=google_sheets"
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              status.connected
                ? 'bg-brand text-white hover:bg-brand-hover'
                : 'pointer-events-none border border-edge text-content-subtle opacity-40'
            }`}
            aria-disabled={!status.connected}
          >
            Add a spreadsheet
          </Link>
          {!status.connected && (
            <span className="text-xs text-content-subtle">
              Connect an account first — there is nothing to browse until then.
            </span>
          )}
        </PanelFooter>
      </div>
    </SettingsPanel>
  );
}

/**
 * The mail server.
 *
 * **The one thing on this page that is not an application registered with a
 * provider** — a host, a port and a password, which is why it keeps its own panel
 * rather than becoming a connection.
 *
 * The wording throughout says the same thing the backend does: mail is an
 * enhancement, never a dependency. Invitations and reset links work without it,
 * and keep working when a relay refuses — the admin gets the link either way.
 */
/**
 * Email: which way invitations and reset links are sent.
 *
 * **Both ways in one card.** Through Microsoft 365 — switched on in the
 * Microsoft 365 box, with the mailbox and its test here — and through your own
 * mail server. Microsoft is tried first when it is on; SMTP is the path for
 * everybody else, and the fallback if a Microsoft send fails.
 */
function EmailPanel({
  onClose,
  microsoft,
}: {
  onClose: () => void;
  microsoft?: Provider;
}) {
  const sendsMail =
    !!microsoft?.client_secret_set &&
    microsoft.capabilities.some((c) => c.key === 'email' && c.built);

  return (
    <Modal
      title="Email"
      description="Where invitations and password reset links are sent from."
      onClose={onClose}
      wide
    >
      <div className="space-y-3">
        {sendsMail && microsoft && <MicrosoftMail provider={microsoft} />}
        <SmtpServer onClose={onClose} />
      </div>
    </Modal>
  );
}

/** The Microsoft 365 half of the Email card: the mailbox, and its test. */
function MicrosoftMail({ provider }: { provider: Provider }) {
  const [status, setStatus] = useState<DirectoryStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    directory
      .status()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  if (status === null) return null;
  return (
    <>
      <MailSettings
        provider={provider}
        status={status}
        busy={busy}
        onSaved={setStatus}
        onBusy={setBusy}
        onError={setError}
      />
      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
    </>
  );
}

function SmtpServer({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<SmtpSettings | null>(null);
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<{ ok: boolean; detail: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<SmtpSettings>('/api/admin/smtp')
      .then(setSettings)
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load.'),
      );
  }, []);

  function set<K extends keyof SmtpSettings>(key: K, value: SmtpSettings[K]) {
    setSettings((s) => (s ? { ...s, [key]: value } : s));
    setStatus(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const saved = await api<SmtpSettings>('/api/admin/smtp', {
        method: 'PUT',
        body: JSON.stringify({
          enabled: settings.enabled,
          host: settings.host,
          port: settings.port,
          security: settings.security,
          username: settings.username,
          from_address: settings.from_address,
          from_name: settings.from_name,
          // Omitted when untouched, so fixing a host does not mean going to find
          // the password again. An empty string is a real value here — it clears
          // it, which is how a relay wanting no authentication is configured.
          ...(password ? { password } : {}),
        }),
      });
      setSettings(saved);
      setPassword('');
      setStatus('Saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setBusy(true);
    setTest(null);
    try {
      setTest(
        await api<{ ok: boolean; detail: string }>('/api/admin/smtp/test', {
          method: 'POST',
        }),
      );
    } catch (e) {
      setTest({
        ok: false,
        detail: e instanceof Error ? e.message : 'Test failed.',
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPanel
      title="Through your own mail server (SMTP)"
      summary={
        settings?.enabled && settings.usable
          ? `Sending from ${settings.from_address}.`
          : 'Used when Microsoft 365 email is off, or if a Microsoft send fails.'
      }
      on={!!(settings?.enabled && settings.usable)}
    >
      {settings === null ? (
        <Loading />
      ) : (
        <form onSubmit={save}>
          <p className="rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content-muted">
            Optional. Without a mail server, invitations and reset links still
            work — an admin copies the link and sends it however they like. This
            only saves that step.
          </p>

          <div className="mt-5 space-y-4">
            <Field
              label="Host"
              value={settings.host}
              onChange={(v) => set('host', v)}
              hint="smtp.office365.com, smtp.gmail.com, or your own relay."
            />
            <Select
              label="Connection"
              value={settings.security}
              onChange={(v) => set('security', v)}
              options={[
                { value: 'starttls', label: 'STARTTLS — usually port 587' },
                { value: 'ssl', label: 'SSL/TLS — usually port 465' },
                { value: 'none', label: 'None — internal relay only' },
              ]}
            />
            <Field
              label="Port"
              value={String(settings.port)}
              onChange={(v) => set('port', Number(v) || 0)}
              numeric={{ decimals: 0, min: 1, max: 65535 }}
            />
            <Field
              label="Username"
              value={settings.username}
              onChange={(v) => set('username', v)}
              hint="Leave empty for a relay that does not ask for one."
            />
            <Field
              label="Password"
              type="password"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
              hint={
                settings.password_set
                  ? 'A password is stored. Leave this empty to keep it.'
                  : 'Stored encrypted and never shown again.'
              }
            />
            <Field
              label="From address"
              type="email"
              value={settings.from_address}
              onChange={(v) => set('from_address', v)}
              hint="What recipients see. It has to be an address your server is allowed to send as — the most common reason a correct-looking setup still refuses."
            />
            <Field
              label="From name"
              value={settings.from_name}
              onChange={(v) => set('from_name', v)}
            />
          </div>

          <div className="mt-5 border-t border-edge pt-5">
            <Toggle
              label="Send email"
              hint="When off, nothing is sent and links are handed over by an admin."
              checked={settings.enabled}
              onChange={(v) => set('enabled', v)}
            />
          </div>

          {error && (
            <p
              role="alert"
              className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
            >
              {error}
            </p>
          )}
          {status && <p className="mt-4 text-sm text-success">{status}</p>}
          {test && (
            <p
              role="alert"
              className={`mt-4 rounded-md border px-3 py-2 text-sm ${
                test.ok
                  ? 'border-success text-success'
                  : 'border-danger text-danger'
              }`}
            >
              {test.detail}
            </p>
          )}

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Working…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={runTest}
              disabled={busy || !settings.usable}
              title={
                settings.usable
                  ? undefined
                  : 'Save a host and a from-address first'
              }
              className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-50"
            >
              Send me a test
            </button>
            <button
              type="button"
              onClick={onClose}
              className="ml-auto rounded-md px-4 py-2 text-sm text-content-muted transition-colors hover:text-content"
            >
              Close
            </button>
          </div>
        </form>
      )}
    </SettingsPanel>
  );
}

/**
 * Email, in the Microsoft 365 box: one switch, like Excel's section. The
 * mailbox and its test are set up in the Email card.
 */
function MailSwitch({
  provider,
  status,
  onSaved,
  onOpen,
}: {
  provider: Provider;
  status: DirectoryStatus;
  onSaved: (status: DirectoryStatus) => void;
  onOpen: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = Boolean(status.mail_from);

  async function flip(on: boolean) {
    setBusy(true);
    setError(null);
    try {
      onSaved(await directory.setMail(provider.provider, on, status.mail_from));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPanel
      title="Email"
      summary="Sends invitations and password resets from a mailbox in your tenant."
      on={status.mail_enabled}
    >
      <Toggle
        label="Send email through Microsoft 365"
        hint={
          ready
            ? `From ${status.mail_from}. Off, email goes through your mail server if one is set up, or links are handed over by an admin.`
            : 'Choose the mailbox it sends from in the Email card first.'
        }
        checked={status.mail_enabled}
        disabled={busy || !ready}
        onChange={(on) => void flip(on)}
      />
      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
      <PanelFooter>
        <button
          type="button"
          onClick={onOpen}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
        >
          Open Email settings &rarr;
        </button>
      </PanelFooter>
    </SettingsPanel>
  );
}

/**
 * Microsoft Teams, in the Microsoft 365 box: one switch. Everything it turns on
 * is set up in the Microsoft Teams card.
 */
function TeamsSwitch({ onOpen, onChanged }: { onOpen: () => void; onChanged: () => void }) {
  const [on, setOn] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ enabled: boolean }>('/api/announcements/destinations')
      .then((listing) => setOn(listing.enabled))
      .catch(() => setOn(null));
  }, []);

  if (on === null) return null;

  async function flip(next: boolean) {
    setBusy(true);
    setError(null);
    try {
      const listing = await api<{ enabled: boolean }>('/api/announcements/enabled', {
        method: 'PUT',
        body: JSON.stringify({ on: next }),
      });
      setOn(listing.enabled);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsPanel
      title="Microsoft Teams"
      summary="Posts wins into channels, and keeps teams and offices in step with Teams."
      on={on}
    >
      <Toggle
        label="Use Microsoft Teams"
        hint="On, the channels and Teams set up in the Microsoft Teams card are live. Off, nothing is posted and Teams is not read on a schedule — the settings are kept for when it is back on."
        checked={on}
        disabled={busy}
        onChange={(next) => void flip(next)}
      />
      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}
      <PanelFooter>
        <button
          type="button"
          onClick={onOpen}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
        >
          Open Microsoft Teams settings &rarr;
        </button>
      </PanelFooter>
    </SettingsPanel>
  );
}
