import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import {
  dataSources,
  type ConnectorOption,
  type Provider,
} from '../dataSources';
import ConnectorMark from '../components/connectorMark';
import PageHeader from '../components/PageHeader';
import { formFields } from './connectorForm';
import { grouped } from './connectorPicker';

/**
 * How to connect each thing, written once and generated from the connectors.
 *
 * **Nothing on this page is typed by hand, and that is the whole design.** The
 * steps come from each connector's `setup_steps`, the fields and their
 * explanations from the same JSON schema the wizard's form is built from, and the
 * permissions from `app/providers.py`. A hand-written manual describing a wizard is
 * a manual that is wrong within a month — and wrong documentation is worse than
 * none, because somebody trusts it.
 *
 * **Deliberately the last thing built in Phase 3.** Written earlier it would have
 * described a flow that then changed four times: five wizard steps became three,
 * two credential forms became one connection, and Salesforce stopped taking a
 * pasted token. Every one of those would have left a paragraph quietly lying.
 *
 * What is *not* here is screenshots. They need real accounts on fourteen products,
 * they go stale the moment a vendor reskins a settings page, and the numbered route
 * through somebody else's menus is the part that actually gets somebody unstuck.
 */
export default function IntegrationsHelp() {
  const [connectors, setConnectors] = useState<ConnectorOption[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([dataSources.connectors(), dataSources.providers()])
      .then(([available, registrations]) => {
        setConnectors(available);
        setProviders(registrations);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  const groups = grouped(connectors);
  const signIns = providers.filter((p) =>
    p.capabilities.some((c) => c.key === 'data' && c.built),
  );

  return (
    <>
      <PageHeader
        title="Connecting your data"
        description="What each integration needs, and where to find it."
        actions={
          <Link
            to="/integrations"
            className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Back to Integrations
          </Link>
        }
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <HowItWorks />

      {signIns.length > 0 && <Registering providers={signIns} />}

      <section className="mb-10">
        <h2 className="text-h2 text-content">Each integration</h2>
        <p className="mt-1 mb-4 text-sm text-content-muted">
          Everything below is what the setup screen will ask you for, in the order
          it asks.
        </p>

        {groups.map((entry) => (
          <div key={entry.group} className="mb-8">
            <h3 className="mb-3 text-caption uppercase tracking-wide text-content-subtle">
              {entry.group}
            </h3>
            <div className="space-y-4">
              {entry.connectors.map((pick) => {
                const connector = connectors.find((c) => c.key === pick.key);
                return connector ? (
                  <Connector key={connector.key} connector={connector} />
                ) : null;
              })}
            </div>
          </div>
        ))}
      </section>

      <WhenItGoesWrong />
    </>
  );
}

/**
 * The three ideas somebody needs before any of the rest makes sense.
 *
 * Not a glossary. These are the three things that, unexplained, make the wizard
 * feel arbitrary: why it asks what a column *means*, why nothing appears
 * instantly, and what happens to a name it does not recognise.
 */
function HowItWorks() {
  return (
    <section className="mb-10">
      <h2 className="text-h2 text-content">How this works</h2>
      <div className="mt-4 grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(18rem,1fr))]">
        <Idea title="A source is one thing you connect">
          One spreadsheet, one database query, one CRM. You can connect several, and
          two sources can feed the same metric — GoalGetter will say so if they do,
          because that is usually a mistake and always worth knowing.
        </Idea>
        <Idea title="You say what the columns mean">
          GoalGetter reads your rows and shows them to you. You point at the column
          holding the person, the one holding the date, and the one holding the
          number. It guesses first, from your real data, and you correct it.
        </Idea>
        <Idea title="Nothing is imported until you turn it on">
          Right up to the last step you are only looking. The final button is what
          starts it, and it imports your chosen history at that moment and then
          checks on a schedule.
        </Idea>
        <Idea title="Names it does not recognise wait for you">
          If a row names somebody with no account here, that row is held rather than
          guessed at or thrown away. You say who they are once, and everything held
          for them is imported.
        </Idea>
      </div>
    </section>
  );
}

function Idea({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-edge bg-surface p-4">
      <p className="font-medium text-content">{title}</p>
      <p className="mt-1 text-sm text-content-muted">{children}</p>
    </div>
  );
}

/**
 * The one step that is genuinely per-deployment, and the one people get stuck on.
 *
 * Generated from the catalogue, so the permissions listed here are the permissions
 * actually requested — the two cannot drift, because they are the same list.
 */
function Registering({ providers }: { providers: Provider[] }) {
  return (
    <section className="mb-10">
      <h2 className="text-h2 text-content">Before you start: signing in</h2>
      <p className="mt-1 mb-4 max-w-3xl text-sm text-content-muted">
        Some integrations sign in rather than taking a key. That needs your company
        registered as an application with the provider — <strong className="text-content">once,
        ever</strong>, not once per source. GoalGetter runs on your own server, so
        there is no middleman holding that registration for you.
      </p>

      <div className="space-y-4">
        {providers.map((provider) => (
          <div key={provider.provider} className="rounded-lg border border-edge bg-surface p-5">
            <div className="mb-3 flex items-center gap-3">
              <ConnectorMark connector={provider.provider} className="size-7" />
              <p className="font-medium text-content">{provider.provider_name}</p>
              {provider.client_secret_set && (
                <span className="rounded-full bg-success/15 px-2 py-0.5 text-xs text-success">
                  Already connected
                </span>
              )}
            </div>

            {provider.setup_steps.length > 0 && (
              <ol className="list-decimal space-y-1 pl-5 text-sm text-content-muted">
                {provider.setup_steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            )}

            {provider.permissions.length > 0 && (
              <div className="mt-4">
                <p className="text-sm text-content">Permissions to grant</p>
                <ul className="mt-1 space-y-0.5 text-sm text-content-muted">
                  {provider.permissions.map((permission) => (
                    <li key={`${permission.kind}:${permission.name}`}>
                      <code className="text-content">{permission.name}</code>
                      {permission.kind && ` · ${permission.kind}`}
                      {permission.admin_consent && ' · needs admin consent'}
                      {' — '}
                      {permission.needed_for}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * One connector, described from its own schema.
 *
 * The field list is built with the same `formFields` the wizard uses, so what this
 * page says it will ask for is exactly what it asks for — including the hint under
 * each box, which is where the genuinely useful detail lives.
 *
 * Advanced fields are left out. They are hidden in the form too, and a help page
 * that listed fourteen questions for a connector that asks three would put somebody
 * off before they started.
 */
function Connector({ connector }: { connector: ConnectorOption }) {
  const settings = formFields(connector.config_schema).filter((f) => !f.advanced);
  const secrets = formFields(connector.credential_schema).filter((f) => !f.advanced);

  return (
    <div className="rounded-lg border border-edge bg-surface p-5">
      <div className="mb-3 flex items-center gap-3">
        <ConnectorMark connector={connector.key} className="size-7" />
        <p className="flex-1 font-medium text-content">{connector.display_name}</p>
        {connector.oauth && (
          <span className="rounded-full bg-surface-hover px-2 py-0.5 text-xs text-content-muted">
            Signs in with {connector.oauth.provider_name}
          </span>
        )}
        {connector.receives && (
          <span className="rounded-full bg-surface-hover px-2 py-0.5 text-xs text-content-muted">
            Your system sends to us
          </span>
        )}
      </div>

      {connector.setup_steps.length > 0 ? (
        <ol className="list-decimal space-y-1 pl-5 text-sm text-content-muted">
          {connector.setup_steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-content-muted">
          Nothing to fetch in advance — GoalGetter generates an address for you, and
          you paste it into whatever is sending the data.
        </p>
      )}

      {(settings.length > 0 || secrets.length > 0) && (
        <div className="mt-4 border-t border-edge pt-4">
          <p className="mb-2 text-sm text-content">What it will ask you for</p>
          <ul className="space-y-1 text-sm text-content-muted">
            {[...settings, ...secrets].map((field) => (
              <li key={field.name}>
                <span className="text-content">{field.label}</span>
                {field.hint && <> — {field.hint}</>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * The four things that actually go wrong, and what each looks like.
 *
 * Written from the failures this project has hit rather than invented: a wrong
 * redirect URI, a missing permission, a query with no `:since`, and a source that
 * imported once and then stopped.
 */
function WhenItGoesWrong() {
  return (
    <section className="mb-10">
      <h2 className="text-h2 text-content">If something does not work</h2>
      <dl className="mt-4 space-y-4">
        <Problem symptom="The sign-in window says the redirect URI does not match">
          The address in the provider's console has to match ours exactly — every
          character, including <code className="text-content">http</code> versus{' '}
          <code className="text-content">https</code> and any trailing slash. Copy it
          from the connection screen rather than typing it. This is the most common
          setup failure by a wide margin, and the error the provider shows never says
          what it expected.
        </Problem>
        <Problem symptom="It signed in, then everything returns “not permitted”">
          A permission was added but not consented to, or the wrong kind was added —
          several providers list the same permission twice, once for acting as the
          person signing in and once for acting as the application. The connection
          screen says which kind each one needs.
        </Problem>
        <Problem symptom="It worked for an hour, then stopped">
          Almost always a missing offline-access permission. Without it the provider
          issues no renewable token, so access expires and is never renewed. Add it
          and sign in again.
        </Problem>
        <Problem symptom="A database source will not save">
          The query has to filter on <code className="text-content">:since</code>.
          That is refused rather than allowed because a query without it re-reads
          your whole table every few minutes — and filtering on the wrong column is
          worse: filter on when a row was last <em>modified</em>, not when the thing
          happened, or edits to older rows never arrive.
        </Problem>
        <Problem symptom="It says the last sync was incomplete">
          More rows changed than one sync will read at once. Nothing is lost — it
          reads the same window again next time rather than skipping ahead — but it
          will stay stuck until there is less to read. Narrow the query, or shorten
          how much history the source starts with.
        </Problem>
      </dl>
    </section>
  );
}

function Problem({
  symptom,
  children,
}: {
  symptom: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-edge bg-surface p-4">
      <dt className="font-medium text-content">{symptom}</dt>
      <dd className="mt-1 max-w-3xl text-sm text-content-muted">{children}</dd>
    </div>
  );
}
