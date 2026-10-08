import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import {
  directory,
  type DirectoryPerson,
  type DirectoryRule,
  type DirectoryStatus,
  type DirectoryValues,
  type RuleDraft,
} from '../directory';
import Combobox from '../components/Combobox';
import ErrorNote from '../components/ErrorNote';
import Select from '../components/Select';
import ConnectorMark from '../components/connectorMark';
import {
  describe,
  everyHours,
  needsAttention,
  placement,
  shadowed,
  stage,
  summarise,
} from './directorySync';

/**
 * Syncing people from the company's own directory.
 *
 * A tab under Users rather than a page of its own, because *"who is in here?"* is
 * the question somebody is already asking when they need this — and the answer to
 * it is one list away.
 *
 * **The screen has three states and each asks for something different.** Nothing
 * connected: point at Integrations. Connected but off: one switch, and say what
 * turning it on will do. On: the rules, and the people waiting. Showing all three
 * at once is how a settings screen becomes something people avoid.
 *
 * All the wording lives in `directorySync.ts`, which has no React in it, so what a
 * run summary says and how a rule reads back are tested rather than eyeballed.
 *
 * **Named `DirectoryPanel` rather than `DirectorySync`** so it cannot collide with
 * that module on a case-insensitive filesystem — which is most of them, and which
 * TypeScript refuses outright. Same split as `ConnectSource.tsx` beside
 * `sourceWizard.ts`: the component is named for the screen, the logic for the
 * subject.
 */
export default function DirectoryPanel({
  teams,
  onPeopleChanged,
}: {
  teams: { id: number; name: string }[];
  /** So the Users list above can refresh once accounts start appearing. */
  onPeopleChanged: () => void;
}) {
  const [status, setStatus] = useState<DirectoryStatus | null>(null);
  const [people, setPeople] = useState<DirectoryPerson[]>([]);
  const [declined, setDeclined] = useState<DirectoryPerson[]>([]);
  const [rules, setRules] = useState<DirectoryRule[]>([]);
  const [clashes, setClashes] = useState<number[][]>([]);
  //: What the directory actually holds, for the rule form's dropdowns. Empty
  //: before a first sync, which `Combobox` handles by staying typeable.
  const [values, setValues] = useState<DirectoryValues>({
    department: [],
    job_title: [],
    office: [],
    group: [],
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const next = await directory.status();
      setStatus(next);
      if (next.connected) {
        const [waiting, refused, ruleset, held] = await Promise.all([
          directory.people(),
          // **The undo half.** Declining is a decision the sync deliberately
          // never overturns, which is right — and it made a mis-click permanent,
          // because nothing listed the people it had been applied to.
          directory.people('declined'),
          directory.rules(),
          directory.values(),
        ]);
        setPeople(waiting);
        setDeclined(refused);
        setRules(ruleset.rules);
        setClashes(ruleset.clashes);
        setValues(held);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // **Poll while a run is in flight, and only then.** A sync finishes on the
  // server whether or not anybody is watching, so without this the screen sits on
  // "Syncing…" until somebody reloads — which looks exactly like a stuck sync.
  // Stops the moment the run does, so an idle page makes no requests at all.
  const running = status?.last_run?.status === 'running';
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void load(), 4000);
    return () => clearInterval(timer);
  }, [running, load]);

  const where = stage(status);

  async function act<T>(work: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-6">
      {error && <ErrorNote message={error} onDismiss={() => setError(null)} />}

      {where === 'unavailable' && (
        <p className="rounded-lg border border-dashed border-edge px-4 py-6 text-sm text-content-muted">
          This build cannot read a directory yet.
        </p>
      )}

      {where === 'unconnected' && <NotConnected />}

      {(where === 'off' || where === 'on') && status && (
        <>
          <SyncStatus
            status={status}
            busy={busy}
            onSyncNow={() => act(() => directory.syncNow())}
          />

          {where === 'on' && (
            <>
              <Waiting
                people={people}
                declined={declined}
                teams={teams}
                busy={busy}
                onDecide={(ids, decision) =>
                  act(async () => {
                    await directory.decide(ids, decision);
                    onPeopleChanged();
                  })
                }
              />
              <Rules
                rules={rules}
                clashes={clashes}
                teams={teams}
                values={values}
                busy={busy}
                onAdd={(draft) => act(() => directory.addRule(draft))}
                onRemove={(id) => act(() => directory.removeRule(id))}
              />
            </>
          )}
        </>
      )}
    </section>
  );
}

/**
 * Nothing to switch on yet.
 *
 * Points at the page where the fix is rather than showing a disabled control. A
 * switch that cannot be flipped invites somebody to try, fail, and conclude the
 * feature is broken rather than unconfigured.
 */
function NotConnected() {
  return (
    <div className="rounded-lg border border-dashed border-edge px-4 py-6">
      <p className="text-sm text-content">
        Connect Microsoft 365 to sync your people.
      </p>
      <p className="mt-1 text-sm text-content-muted">
        It uses the same application registration as signing in and reading Excel —
        one connection covers all of it.
      </p>
      <Link
        to="/integrations"
        className="mt-3 inline-block rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
      >
        Go to Integrations
      </Link>
    </div>
  );
}

/**
 * What the sync is doing, and where it is turned on and off.
 *
 * **It used to be a switch, and there were two of them.** This screen had one and
 * the connection panel on Integrations gained another, both writing the same
 * column — so whichever you had not looked at most recently was lying to you.
 *
 * The one that stayed is the one on the connection, because that is what the
 * setting belongs to: it is a column on `oauth_client`, alongside the credential
 * it needs. What is left here is the half this screen is actually for — is it
 * running, how often, how did the last run go, and run it again now — with a
 * pointer to where the answer gets changed.
 *
 * **Stating the schedule matters more now than it did.** With the switch gone,
 * somebody looking at an empty approval queue has no way to tell "off" from "not
 * due yet" unless the screen says which.
 */
function SyncStatus({
  status,
  busy,
  onSyncNow,
}: {
  status: DirectoryStatus;
  busy: boolean;
  onSyncNow: () => void;
}) {
  const attention = needsAttention(status.last_run);
  //: **Server state, not local.** `busy` lives in this component and dies with
  //: it, so a sync started here and then navigated away from came back looking
  //: like it had never run. The row says what is happening; the button reads it.
  const running = status.last_run?.status === 'running';
  const said = summarise(status.last_run);
  const long = said.length > 140;
  const [showAll, setShowAll] = useState(false);

  return (
    <div className="rounded-lg border border-edge bg-surface p-5">
      <div className="flex flex-wrap items-start gap-4">
        <ConnectorMark connector={status.provider ?? 'microsoft'} className="size-8" />
        <div className="min-w-60 flex-1">
          {status.enabled ? (
            <>
              <p className="text-sm text-content">
                <span aria-hidden>✓ </span>
                Syncing from your directory,{' '}
                <strong>{everyHours(status.sync_hours)}</strong>
              </p>
              <p className="mt-1 text-xs text-content-muted">
                Nobody gets an account until you approve them below.
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-content">Directory sync is off</p>
              <p className="mt-1 text-xs text-content-muted">
                Reads your directory on a schedule and stages the people it finds
                for approval. Nobody gets an account without a decision.
              </p>
            </>
          )}
          {/* The one place it is changed, named rather than duplicated. A second
              switch here is what this replaced. */}
          <Link
            to="/integrations"
            className="mt-2 inline-block text-sm text-brand hover:underline"
          >
            {status.enabled ? 'Change in Integrations' : 'Turn it on in Integrations'}{' '}
            &rarr;
          </Link>
        </div>
      </div>

      {status.enabled && (
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-edge pt-4">
          {/* **A failed run puts its whole error here**, and those errors are
              paragraphs — deliberately, since the short version of one of them
              cost an afternoon. Clamped rather than shortened: the detail is what
              makes them worth having, it just should not push the button it tells
              you to press off the screen. */}
          <div className="min-w-60 flex-1">
            <p
              className={`text-sm ${
                attention ? 'text-warning' : 'text-content-muted'
              } ${!showAll && long ? 'line-clamp-2' : ''}`}
            >
              {said}
            </p>
            {long && (
              <button
                type="button"
                onClick={() => setShowAll((open) => !open)}
                className="mt-1 text-xs text-content-subtle underline hover:text-content"
              >
                {showAll ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={onSyncNow}
            disabled={busy || running}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            {running ? 'Syncing…' : busy ? 'Reading…' : 'Sync now'}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * The people waiting on a decision.
 *
 * **Selection defaults to everybody**, because the first use of this screen is a
 * company of two hundred arriving at once and the overwhelmingly common answer is
 * "yes, all of them". Approving one row at a time is the chore that makes somebody
 * give up and keep typing names in by hand.
 *
 * Each row says where the rules *would* put them, before the button is pressed.
 * Finding out afterwards means undoing it by hand.
 */
function Waiting({
  people,
  declined,
  teams,
  busy,
  onDecide,
}: {
  people: DirectoryPerson[];
  /** People an admin said not to add, so the decision can be taken back. */
  declined: DirectoryPerson[];
  teams: { id: number; name: string }[];
  busy: boolean;
  onDecide: (ids: number[], decision: string) => void;
}) {
  const [chosen, setChosen] = useState<Set<number>>(new Set());

  // Anybody new is selected: the list only changes when a sync brings people in,
  // and those are exactly the ones somebody is here to decide about.
  useEffect(() => {
    setChosen(new Set(people.map((p) => p.id)));
  }, [people]);

  const ids = [...chosen];

  if (people.length === 0) {
    return (
      <>
        <p className="mt-6 rounded-lg border border-dashed border-edge px-4 py-6 text-sm text-content-muted">
          Nobody is waiting. New people appear here after each sync.
        </p>
        <NotAdded people={declined} busy={busy} onDecide={onDecide} />
      </>
    );
  }

  return (
    <div className="mt-6">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h3 className="flex-1 font-medium text-content">
          {people.length} waiting on a decision
        </h3>
        {/* **Two ways to add somebody, and one to refuse.** Most of a
            directory is neither of the old two answers: a company of four
            hundred has contractors, service accounts and departments that do
            not sell, and they belong in the roster without being on a
            leaderboard. Declining them was the only tool for that, and it
            creates nothing at all. */}
        <button
          type="button"
          onClick={() => onDecide(ids, 'approved')}
          disabled={busy || ids.length === 0}
          className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          Add {ids.length}
        </button>
        <button
          type="button"
          onClick={() => onDecide(ids, 'hidden')}
          disabled={busy || ids.length === 0}
          title="An account is created, hidden from every board until somebody unhides them."
          className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-40"
        >
          Add {ids.length} hidden
        </button>
        {/* Quieter than the two above, because it is the rarer answer and the
            only one that leaves nothing behind. It keeps its own name: what it
            does is decline them, and "not these" said nothing about what
            happens. */}
        <button
          type="button"
          onClick={() => onDecide(ids, 'declined')}
          disabled={busy || ids.length === 0}
          title="No account is created, and the next sync will not ask again."
          className="text-sm text-content-muted underline transition-colors hover:text-content disabled:opacity-40"
        >
          Don't add
        </button>
      </div>

      <p className="mb-3 text-sm text-content-muted">
        <strong>Add</strong> creates an account and places them by your rules.{' '}
        <strong>Add hidden</strong> creates the same account but keeps them off
        every leaderboard — they appear under Hidden in People, ready to be
        unhidden later. <strong>Don't add</strong> creates nothing and stops the
        sync asking again; you can undo it below.
      </p>

      <ul className="divide-y divide-edge rounded-lg border border-edge bg-surface">
        {people.map((person) => (
          <li key={person.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
            <input
              type="checkbox"
              checked={chosen.has(person.id)}
              onChange={(event) =>
                setChosen((was) => {
                  const next = new Set(was);
                  if (event.target.checked) next.add(person.id);
                  else next.delete(person.id);
                  return next;
                })
              }
              aria-label={`Include ${person.display_name || person.email}`}
              className="size-4 shrink-0"
            />
            <div className="min-w-52 flex-1">
              <p className="font-medium text-content">
                {person.display_name || person.email}
              </p>
              <p className="text-xs text-content-subtle">
                {[person.job_title, person.department, person.office_location]
                  .filter(Boolean)
                  .join(' · ') || person.email}
              </p>
            </div>
            <p className="text-sm text-content-muted">{placement(person, teams)}</p>
            {person.pending_reason && (
              <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">
                {person.pending_reason}
              </span>
            )}
          </li>
        ))}
      </ul>

      <NotAdded people={declined} busy={busy} onDecide={onDecide} />
    </div>
  );
}

const BLANK: RuleDraft = {
  department: '',
  job_title: '',
  office: '',
  group: '',
  role: 'agent',
  team_id: null,
};

/**
 * The rules, each read back as a sentence.
 *
 * **A row of four mostly-empty boxes does not say what it does**, and "Any"
 * repeated across three columns is exactly the shape that gets misread as an *or*.
 * So the sentence is the row, and the boxes are only for writing a new one.
 *
 * Order is not shown because order does not matter: the most specific matching rule
 * wins. That is the property that lets somebody add a broad rule without silently
 * disabling every specific one below it.
 */
/**
 * People an admin said not to add, and the way to take that back.
 *
 * **Declining is deliberately permanent, which is exactly why this exists.** The
 * sync never overturns a decision — `DECIDED` in `models/directory.py` says so,
 * and it is the right rule: without it, declining somebody would last until the
 * next pass. But nothing listed who it had been applied to, so a mis-click on a
 * bulk decline was unrecoverable through the interface.
 *
 * Collapsed, because it is a repair rather than a step, and most deployments
 * never open it.
 *
 * **Not the same as the Hidden tab in People**, and worth being clear about: a
 * declined person never became an account at all. There is nothing of theirs to
 * hide, and they appear nowhere in People.
 */
function NotAdded({
  people,
  busy,
  onDecide,
}: {
  people: DirectoryPerson[];
  busy: boolean;
  onDecide: (ids: number[], decision: string) => void;
}) {
  if (people.length === 0) return null;

  return (
    <details className="mt-4 rounded-lg border border-edge bg-surface">
      <summary className="cursor-pointer px-4 py-3 text-sm text-content-muted transition-colors hover:text-content">
        {people.length} not added
        <span className="ml-2 text-xs text-content-subtle">
          — no account, and the sync stopped asking
        </span>
      </summary>

      <div className="border-t border-edge px-4 py-3">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-content-muted">
            Putting somebody back means the next decision is yours again — it
            creates no account by itself.
          </p>
          <button
            type="button"
            onClick={() => onDecide(people.map((p) => p.id), 'pending')}
            disabled={busy}
            className="shrink-0 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-40"
          >
            Move all back to waiting
          </button>
        </div>

        <ul className="divide-y divide-edge rounded-md border border-edge">
          {people.map((person) => (
            <li
              key={person.id}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-content">
                  {person.display_name || person.email}
                </span>
                <span className="block truncate text-xs text-content-subtle">
                  {[person.email, person.job_title, person.department]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </span>
              <button
                type="button"
                onClick={() => onDecide([person.id], 'pending')}
                disabled={busy}
                className="shrink-0 text-xs text-brand hover:underline disabled:opacity-40"
              >
                Move back
              </button>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

function Rules({
  rules,
  clashes,
  teams,
  values,
  busy,
  onAdd,
  onRemove,
}: {
  rules: DirectoryRule[];
  clashes: number[][];
  teams: { id: number; name: string }[];
  /** What the directory holds, for the condition dropdowns. */
  values: DirectoryValues;
  busy: boolean;
  onAdd: (draft: RuleDraft) => void;
  onRemove: (id: number) => void;
}) {
  const [draft, setDraft] = useState<RuleDraft>(BLANK);
  const [adding, setAdding] = useState(false);
  const overshadowed = shadowed(clashes);

  function set<K extends keyof RuleDraft>(key: K, value: RuleDraft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  return (
    <div className="mt-8">
      <div className="mb-2 flex flex-wrap items-center gap-3">
        <h3 className="flex-1 font-medium text-content">Who becomes what</h3>
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
        >
          {adding ? 'Cancel' : 'Add a rule'}
        </button>
      </div>
      <p className="mb-3 text-sm text-content-muted">
        The most specific matching rule wins, so the order you write them in does
        not matter. Anyone no rule matches — including everyone, when there are no
        rules at all — is added as an <strong className="text-content">agent</strong>{' '}
        with no team, for you to place. Agent is the lowest level of access there
        is, so a missing rule can never hand somebody more than the least.
      </p>

      {rules.length > 0 && (
        <ul className="divide-y divide-edge rounded-lg border border-edge bg-surface">
          {rules.map((rule, index) => (
            <li key={rule.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
              <div className="min-w-60 flex-1">
                <p className="text-sm text-content">{describe(rule, teams)}</p>
                {overshadowed.has(index) && (
                  <p className="mt-1 text-xs text-warning">
                    Never applies — an earlier rule matches exactly the same people.
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => onRemove(rule.id)}
                disabled={busy}
                className="text-sm text-content-muted underline transition-colors hover:text-danger disabled:opacity-50"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <form
          className="mt-4 rounded-lg border border-edge bg-surface p-5"
          onSubmit={(event) => {
            event.preventDefault();
            onAdd(draft);
            setDraft(BLANK);
            setAdding(false);
          }}
        >
          <p className="mb-4 text-sm text-content-muted">
            Leave a box empty to mean <strong className="text-content">any</strong>.
            All the boxes you fill in have to match.
          </p>
          <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(12rem,1fr))]">
            {/* Dropdowns of what the directory actually reported, not free text.
                A rule is a string comparison against what the provider sent, so
                `Sales` against a tenant that says `Sales Team` saved cleanly and
                matched nobody — with nothing on screen saying so until an admin
                wondered why no accounts appeared. Still typeable: before a first
                sync there is no list, and a rule for a department that is about
                to exist is a fair thing to want. */}
            <Combobox
              label="Department"
              value={draft.department}
              onChange={(v) => set('department', v)}
              options={values.department}
              placeholder="Any"
            />
            <Combobox
              label="Job title"
              value={draft.job_title}
              onChange={(v) => set('job_title', v)}
              options={values.job_title}
              placeholder="Any"
            />
            <Combobox
              label="Office"
              value={draft.office}
              onChange={(v) => set('office', v)}
              options={values.office}
              placeholder="Any"
            />
            <Combobox
              label="Group"
              value={draft.group}
              onChange={(v) => set('group', v)}
              options={values.group}
              placeholder="Any"
            />
          </div>
          <div className="mt-4 grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(12rem,1fr))]">
            <Select
              label="Becomes"
              value={draft.role}
              onChange={(v) => set('role', v)}
              options={[
                { value: 'agent', label: 'An agent' },
                { value: 'manager', label: 'A manager' },
                { value: 'admin', label: 'An admin' },
              ]}
            />
            <Select
              label="On team"
              value={draft.team_id === null ? '' : String(draft.team_id)}
              onChange={(v) => set('team_id', v === '' ? null : Number(v))}
              options={[
                { value: '', label: 'No team — assign by hand' },
                ...teams.map((t) => ({ value: String(t.id), label: t.name })),
              ]}
            />
          </div>
          <button
            type="submit"
            disabled={busy}
            className="mt-5 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            Add it
          </button>
        </form>
      )}
    </div>
  );
}
