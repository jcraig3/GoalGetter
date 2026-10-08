import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { toast } from '../toast';
import { useOrgAppearance } from "../orgAppearance";
import { Can, useAuth } from "../auth";
import AppearanceFields from "../components/AppearanceFields";
import BulkGoals from "../components/BulkGoals";
import EmptyState from "../components/EmptyState";
import Field from "../components/Field";
import GoalPreview from "../components/GoalPreview";
import GoalProgress, { StatusBadge, type GoalLike } from "../components/GoalProgress";
import IconButton from "../components/IconButton";
import {
    ArchiveIcon,
    PencilIcon,
    RepeatIcon,
    RestoreIcon,
    TrashIcon,
} from "../components/icons";
import Modal from "../components/Modal";
import PageHeader from "../components/PageHeader";
import Select from "../components/Select";
import StretchFields, { stretchPayload, type StretchDraft } from "../components/StretchFields";
import { Tab } from "../components/Tabs";
import { ask } from '../confirm';
import Loading from '../components/Loading';
import PeoplePicker from "../components/PeoplePicker";
import type { PickPerson } from "../components/peoplePick";
import FilterFold from "../components/FilterFold";
import EditorPreview from "../components/wall/EditorPreview";
import { pickFormat } from "./Leaderboards";
import { useOpenFromUrl } from '../urlIntent';
import { repeatTag } from './goalWords';
import { archiveQuestion, wallWords } from "../wallUse";

/** Extends the progress component's shape, so the two cannot drift apart when
 *  a field is added to the API. */
/** Who a goal is for. `organization` is the one that names nobody. */
type Subject = "user" | "team" | "organization";

export interface Goal extends GoalLike {
    id: number;
    name: string | null;
    metric_id: number;
    subject_type: string;
    /** Null for an organization goal, which is about everyone. */
    subject_id: number | null;
    subject_name: string;
    period_type: string;
    period_label: string;
    archived: boolean;
    needs_attention: boolean;
    recurring: boolean;
    recurrence_ends_on: string | null;
    spawned_from_goal_id: number | null;
    /** Only what this goal itself chose; absent keys inherit. */
    appearance: Record<string, unknown>;
}

interface Metric {
    id: number;
    name: string;
    direction?: string;
    unit?: string;
    decimal_places?: number;
    unit_label?: string | null;
}

type Person = PickPerson;

interface Team {
    id: number;
    name: string;
}

const PERIODS = [
    { value: "day", label: "Today" },
    { value: "week", label: "This week" },
    { value: "month", label: "This month" },
    { value: "quarter", label: "This quarter" },
    { value: "year", label: "This year" },
] as const;

export default function Goals() {
    const { can } = useAuth();
    const [goals, setGoals] = useState<Goal[] | null>(null);
    // One value rather than two booleans: "mine" and "archived" are three
    // views, not four states, and a boolean pair would allow the meaningless
    // combination of both.
    const [view, setView] = useState<"all" | "mine" | "archived">("all");
    // Narrowing what is loaded, in the browser: a goal list is tens, not
    // thousands, and a filter that waits on the network is one nobody uses.
    const [search, setSearch] = useState("");
    const [statusFilter, setStatusFilter] = useState("");
    const [metricFilter, setMetricFilter] = useState("");
    const [periodFilter, setPeriodFilter] = useState("");
    const [creating, setCreating] = useState(false);
    const [bulk, setBulk] = useState(false);
    useOpenFromUrl('new', () => setCreating(true));
    const [editing, setEditing] = useState<Goal | null>(null);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async () => {
        const query = new URLSearchParams();
        if (view === "mine") query.set("mine", "true");
        if (view === "archived") query.set("include_archived", "true");

        try {
            const all = await api<Goal[]>(`/api/goals?${query}`);
            // The API has no "archived only" flag, and adding a third
            // overlapping one would muddle its vocabulary. Narrowing an
            // already-authorised list in the browser is presentation, not
            // permission — unlike scope, which must stay in the query.
            setGoals(view === "archived" ? all.filter((g) => g.archived) : all);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Could not load goals.");
        }
    }, [view]);

    useEffect(() => {
        void load();
    }, [load]);

    async function remove(goal: Goal) {
        // Which TVs lose it, said before it goes (8.6).
        const onWalls = await wallWords("goal", goal.id);
        if (
            !await ask(
                `Delete this goal for ${goal.subject_name}? Archive it instead to keep the record of what was asked for.${onWalls}`,
            )
        )
            return;
        setError(null);
        try {
            await api(`/api/goals/${goal.id}`, { method: "DELETE" });
            toast("Goal deleted");
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Could not delete.");
        }
    }

    // Archive and restore differ by one word, so one function takes it. Two
    // near-identical copies would be two places to fix a change to either.
    async function setArchived(goal: Goal, archived: boolean) {
        setError(null);
        // Wall-aware, as delete is (P3-2): asked only when a TV would lose it.
        if (archived) {
            const question = await archiveQuestion("goal", goal.id, goal.name || `${goal.subject_name} — ${goal.metric_name}`);
            if (question && !(await ask(question, { confirmLabel: "Archive" }))) return;
        }
        try {
            await api(`/api/goals/${goal.id}/${archived ? "archive" : "restore"}`, {
                method: "POST",
            });
            toast(
                archived ? "Goal archived" : "Goal restored",
                undefined,
                archived ? { label: "Undo", run: () => void setArchived(goal, false) } : undefined,
            );
            await load();
        } catch (e) {
            setError(
                e instanceof Error
                    ? e.message
                    : `Could not ${archived ? "archive" : "restore"}.`,
            );
        }
    }

    const words = search.trim().toLowerCase();
    const shown = (goals ?? []).filter(
        (g) =>
            (!statusFilter || g.status === statusFilter) &&
            (!metricFilter || g.metric_name === metricFilter) &&
            (!periodFilter || g.period_label === periodFilter) &&
            (!words ||
                `${g.name ?? ""} ${g.subject_name} ${g.metric_name}`
                    .toLowerCase()
                    .includes(words)),
    );

    return (
        <>
            <PageHeader
                title="Goals"
                description="Targets for people and teams. Progress is measured against the same numbers the leaderboards use."
                actions={
                    <Can do="goals.manage">
                        <div className="flex flex-wrap gap-2">
                            {/* A whole team or office at once (6.12): one
                                target, anybody's own where it differs. */}
                            <button
                                onClick={() => setBulk(true)}
                                className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
                            >
                                Set for a group
                            </button>
                            <button
                                onClick={() => setCreating(true)}
                                className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
                            >
                                New goal
                            </button>
                        </div>
                    </Can>
                }
            />

            {error && (
                <p
                    role="alert"
                    className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
                >
                    {error}
                </p>
            )}

            <div className="mb-4 flex gap-2">
                <Tab active={view === "all"} onClick={() => setView("all")}>
                    All
                </Tab>
                <Tab active={view === "mine"} onClick={() => setView("mine")}>
                    Mine
                </Tab>
                <Tab
                    active={view === "archived"}
                    onClick={() => setView("archived")}
                >
                    Archived
                </Tab>
            </div>

            {goals && goals.length > 3 && (
                <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <Field
                        label="Search"
                        value={search}
                        onChange={setSearch}
                        required={false}
                        placeholder="A name, a person or a team"
                    />
                    <FilterFold
                        active={[metricFilter, periodFilter, statusFilter].filter(Boolean).length}
                    >
                    <Select
                        label="Metric"
                        value={metricFilter}
                        onChange={setMetricFilter}
                        options={[
                            { value: "", label: "Any metric" },
                            ...[...new Set(goals.map((g) => g.metric_name))]
                                .sort()
                                .map((m) => ({ value: m, label: m })),
                        ]}
                    />
                    {/* By the label each card already shows, newest first:
                        "October 2026", not a period type nobody thinks in. */}
                    <Select
                        label="Period"
                        value={periodFilter}
                        onChange={setPeriodFilter}
                        options={[
                            { value: "", label: "Any period" },
                            ...[...new Map(
                                [...goals]
                                    .sort((a, b) =>
                                        (b.period_end ?? "").localeCompare(a.period_end ?? ""),
                                    )
                                    .map((g) => [g.period_label, g.period_label]),
                            ).keys()].map((label) => ({ value: label, label })),
                        ]}
                    />
                    <Select
                        label="Status"
                        value={statusFilter}
                        onChange={setStatusFilter}
                        options={[
                            { value: "", label: "Any status" },
                            { value: "behind", label: "Behind" },
                            { value: "on_track", label: "On track" },
                            { value: "ahead", label: "Ahead" },
                            { value: "hit", label: "Hit" },
                            { value: "missed", label: "Missed" },
                            { value: "not_started", label: "Not started" },
                        ]}
                    />
                    </FilterFold>
                </div>
            )}

            {goals === null ? (
                <Loading />
            ) : goals.length > 0 && shown.length === 0 ? (
                <p className="text-sm text-content-muted">No goal matches those filters.</p>
            ) : goals.length === 0 ? (
                <EmptyState
                    title={
                        view === "archived"
                            ? "Nothing archived"
                            : view === "mine"
                              ? "No goals for you yet"
                              : "No goals yet"
                    }
                    description={
                        view === "archived"
                            ? "Archived goals are kept as the record of what was asked for. They stop counting and stop repeating."
                            : can("goals.manage")
                              ? "Set a target for a person or a team, and progress is measured automatically from recorded data."
                              : "Your manager has not set any targets yet."
                    }
                />
            ) : (
                <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(20rem,1fr))]">
                    {shown.map((goal) => (
                        <article
                            key={goal.id}
                            // Dimmed and outlined, so an archived goal is not mistaken
                            // for a live one at a glance.
                            className={`flex flex-col rounded-lg border border-edge bg-surface p-5 ${
                                goal.archived ? "border-dashed opacity-60" : ""
                            }`}
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                    <Link
                                        to={`/goals/${goal.id}`}
                                        className="block truncate font-medium text-content hover:text-brand"
                                    >
                                        {/* Who, then what — the same order the wall
                                            uses (review §7). A named goal keeps its name. */}
                                        {goal.name || `${goal.subject_name} — ${goal.metric_name}`}
                                    </Link>
                                    <p className="truncate text-xs text-content-subtle">
                                        {goal.name && `${goal.subject_name} · `}
                                        {goal.period_label}
                                        {goal.name && ` · ${goal.metric_name}`}
                                        {(goal.recurring || goal.spawned_from_goal_id !== null) && (
                                            <span className="ml-1 inline-flex items-center gap-1 align-middle" title={repeatTag(goal).title}>
                                                <RepeatIcon className="size-3" />
                                                {repeatTag(goal).label}
                                            </span>
                                        )}
                                    </p>
                                </div>
                                {/* The full status, not just "Hit" — behind and missed are the ones
                                    worth seeing at a glance. */}
                                <span className="shrink-0">
                                    <StatusBadge status={goal.status} />
                                </span>
                            </div>

                            <div className="mt-4 flex-1">
                                <GoalProgress goal={goal} showStatus={false} />
                            </div>

                            <Can do="goals.manage">
                                <div className="mt-4 flex justify-end gap-1 border-t border-edge pt-3">
                                    {goal.archived ? (
                                        // An archived goal is history. Restoring it is the way back;
                                        // editing one that no longer counts would be confusing, and
                                        // delete stays available for the ones archived by mistake.
                                        <>
                                            <IconButton
                                                label="Restore"
                                                icon={<RestoreIcon className="size-4" />}
                                                onClick={() => void setArchived(goal, false)}
                                            />
                                            <IconButton
                                                label="Delete"
                                                icon={<TrashIcon className="size-4" />}
                                                danger
                                                onClick={() => void remove(goal)}
                                            />
                                        </>
                                    ) : (
                                        <>
                                            {/* Edit first: changing a target is the common case,
                                                and the destructive pair should not be the only
                                                thing on offer. */}
                                            <IconButton
                                                label="Edit"
                                                icon={<PencilIcon className="size-4" />}
                                                onClick={() => {
                                                    setCreating(false);
                                                    setEditing(goal);
                                                }}
                                            />
                                            <IconButton
                                                label="Archive"
                                                icon={<ArchiveIcon className="size-4" />}
                                                onClick={() => void setArchived(goal, true)}
                                            />
                                            <IconButton
                                                label="Delete"
                                                icon={<TrashIcon className="size-4" />}
                                                danger
                                                onClick={() => void remove(goal)}
                                            />
                                        </>
                                    )}
                                </div>
                            </Can>
                        </article>
                    ))}
                </div>
            )}

            {bulk && (
                <BulkGoals
                    onClose={() => setBulk(false)}
                    onSaved={async (said) => {
                        toast(said);
                        setBulk(false);
                        await load();
                    }}
                />
            )}

            {(creating || editing) && (
                <GoalForm
                    goal={editing}
                    onClose={() => {
                        setCreating(false);
                        setEditing(null);
                    }}
                    onSaved={async () => {
                        toast(editing ? 'Goal saved' : 'Goal created');
                        setCreating(false);
                        setEditing(null);
                        await load();
                    }}
                />
            )}
        </>
    );
}

export function GoalForm({
    goal,
    onClose,
    onSaved,
}: {
    /** The goal being edited, or null to create a new one. */
    goal: Goal | null;
    onClose: () => void;
    onSaved: () => Promise<void>;
}) {
    const { can } = useAuth();
    const isAdmin = can("org.settings.edit");
    const isEdit = goal !== null;
    // A spawned copy cannot be made to recur — only its original can.
    const isSpawnedCopy = goal?.spawned_from_goal_id != null;

    const [metrics, setMetrics] = useState<Metric[]>([]);
    const [people, setPeople] = useState<Person[]>([]);
    const [teams, setTeams] = useState<Team[]>([]);

    const [metricId, setMetricId] = useState(String(goal?.metric_id ?? ""));
    const [subjectType, setSubjectType] = useState<Subject>(
        (goal?.subject_type as Subject) ?? "user",
    );
    const [subjectId, setSubjectId] = useState(String(goal?.subject_id ?? ""));
    // Trailing zeros stripped: the API returns NUMERIC(18,4) as "200.0000",
    // and editing a field pre-filled with that is unpleasant.
    const [target, setTarget] = useState(
        goal ? String(Number(goal.target_value)) : "",
    );
    const [periodType, setPeriodType] = useState(goal?.period_type ?? "month");
    const [name, setName] = useState(goal?.name ?? "");
    const [recurring, setRecurring] = useState(goal?.recurring ?? false);
    const [stretch, setStretch] = useState<StretchDraft[]>(
        (goal?.stretch ?? []).map((level) => ({
            value: String(Number(level.value)),
            label: level.label,
        })),
    );
    const [appearance, setAppearance] = useState<Record<string, unknown>>(
        goal?.appearance ?? {},
    );
    const inherited = useOrgAppearance();
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        Promise.all([
            api<Metric[]>("/api/metrics"),
            api<Person[]>("/api/users"),
            api<Team[]>("/api/teams"),
        ])
            .then(([m, p, t]) => {
                setMetrics(m);
                setPeople(p);
                setTeams(t);
                setMetricId((v) => v || String(m[0]?.id ?? ""));
                // No person assumed — see `switchSubject`.
            })
            .catch((e) =>
                setError(
                    e instanceof Error ? e.message : "Could not load options.",
                ),
            );
    }, []);

    // Reset the subject when switching between people and teams, or the id from
    // one list would be submitted against the other.
    function switchSubject(type: Subject) {
        setSubjectType(type);
        // An organization goal names nobody, so there is no id to keep in
        // step — and leaving a stale one would submit a person's id against a
        // goal that is about everyone.
        // A person is chosen, never assumed: defaulting to whoever sorted
        // first made it easy to set somebody else's target by accident.
        setSubjectId(
            type === "team" ? String(teams[0]?.id ?? "") : "",
        );
    }

    async function submit(event: FormEvent) {
        event.preventDefault();
        setBusy(true);
        setError(null);
        try {
            if (isEdit) {
                // metric_id and subject are absent on purpose: the API refuses
                // them with a 422, because changing either makes it a different
                // goal whose history of "you were at 60%" would then refer to
                // something else.
                await api(`/api/goals/${goal.id}`, {
                    method: "PATCH",
                    body: JSON.stringify({
                        target_value: target,
                        period_type: periodType,
                        name: name || null,
                        recurring,
                        stretch: stretchPayload(stretch),
                        appearance,
                    }),
                });
            } else {
                await api("/api/goals", {
                    method: "POST",
                    body: JSON.stringify({
                        metric_id: Number(metricId),
                        subject_type: subjectType,
                        subject_id:
                            subjectType === "organization"
                                ? null
                                : Number(subjectId),
                        target_value: target,
                        period_type: periodType,
                        name: name || null,
                        recurring,
                        stretch: stretchPayload(stretch),
                        appearance,
                    }),
                });
            }
            await onSaved();
        } catch (e) {
            setError(
                e instanceof Error
                    ? e.message
                    : `Could not ${isEdit ? "save" : "create"} the goal.`,
            );
        } finally {
            setBusy(false);
        }
    }


    //: An organization goal names nobody, so "choose somebody" cannot be a
    //: condition on saving it.
    const subjectChosen = subjectType === "organization" || Boolean(subjectId);
    // **Said, not just greyed out.** A disabled "Create goal" with no reason
    // left somebody hunting for what was missing (review §6). The first thing
    // missing, in the order the form asks for them.
    const missing = !metricId
        ? "Choose a metric to continue."
        : !subjectChosen
          ? "Choose who the goal is for."
          : Number(target) <= 0
            ? "Enter a target to continue."
            : null;

    return (
        <Modal
            title={isEdit ? "Edit goal" : "New goal"}
            description={
                isEdit
                    ? "Adjust the target, the period, or how it repeats."
                    : "A target for one metric over one period."
            }
            onClose={onClose}
            side={
                <EditorPreview
                    kind="goal"
                    title={
                        name ||
                        goal?.metric_name ||
                        metrics.find((m) => String(m.id) === metricId)?.name
                    }
                    chosen={appearance}
                    inherited={inherited}
                    // Who it is for, its unit, target and period (7.4, Q2-3).
                    sample={{
                        ...pickFormat(
                            metrics.find((m) => String(m.id) === (metricId || String(goal?.metric_id ?? ''))),
                        ),
                        subject_name:
                            goal?.subject_name ??
                            (subjectType === "user"
                                ? (people.find((p) => String(p.id) === subjectId)?.full_name ?? "")
                                : subjectType === "team"
                                  ? (teams.find((t) => String(t.id) === subjectId)?.name ?? "")
                                  : "Everyone"),
                        target: target || undefined,
                        period_label: PERIODS.find((p) => p.value === periodType)?.label,
                    }}
                    // The form as it would be saved, drawn with real progress
                    // (8.7). Asked only once it names a metric, somebody and a
                    // target.
                    real={
                        metricId && target && (subjectType === "organization" || subjectId)
                            ? {
                                  path: "/api/goals/draft-slide",
                                  body: {
                                      metric_id: Number(metricId),
                                      subject_type: subjectType,
                                      subject_id: subjectType === "organization" ? null : Number(subjectId),
                                      target_value: target,
                                      period_type: periodType,
                                      name: name || null,
                                      recurring: false,
                                      stretch: stretchPayload(stretch),
                                      appearance,
                                  },
                              }
                            : null
                    }
                />
            }
        >
            <form onSubmit={submit} className="space-y-4">
                {/* Metric and subject are fixed once a goal exists. Shown as
                    read-only rather than hidden, so the form still says what it
                    is about — and explained below, because a control that does
                    nothing with no reason given reads as a bug. */}
                {isEdit ? (
                    <Fixed label="Metric" value={goal.metric_name} />
                ) : (
                    <Select
                        label="Metric"
                        value={metricId}
                        onChange={setMetricId}
                        options={metrics.map((m) => ({
                            value: String(m.id),
                            label: m.name,
                        }))}
                    />
                )}

                {isEdit ? (
                    <Fixed
                        label={goal.subject_type === "team" ? "Team" : "Person"}
                        value={goal.subject_name}
                    />
                ) : (
                    <>
                        <div>
                            <span className="block text-sm text-content-muted">
                                For
                            </span>
                            <div className="mt-1 flex gap-2">
                                <Tab
                                    active={subjectType === "user"}
                                    onClick={() => switchSubject("user")}
                                >
                                    A person
                                </Tab>
                                <Tab
                                    active={subjectType === "team"}
                                    onClick={() => switchSubject("team")}
                                >
                                    A team
                                </Tab>
                                {/* **The big epic goal.** A target the whole
                                    floor pulls toward together — one number
                                    everyone is adding to, on every wall in the
                                    building. Admins only, because that is what
                                    it means. */}
                                {isAdmin && (
                                    <Tab
                                        active={subjectType === "organization"}
                                        onClick={() =>
                                            switchSubject("organization")
                                        }
                                    >
                                        Everyone
                                    </Tab>
                                )}
                            </div>
                        </div>

                        {subjectType === "organization" ? (
                            <p className="rounded-md border border-edge px-3 py-2 text-xs text-content-muted">
                                Everybody's numbers add up to one figure.
                                It appears on every wall and everyone in the
                                organization can read it.
                            </p>
                        ) : subjectType === "user" ? (
                            <PeoplePicker
                                label="Person"
                                people={people}
                                value={subjectId ? Number(subjectId) : null}
                                onChange={(id) =>
                                    setSubjectId(id === null ? "" : String(id))
                                }
                            />
                        ) : (
                            <Select
                                label="Team"
                                value={subjectId}
                                onChange={setSubjectId}
                                options={teams.map((t) => ({
                                    value: String(t.id),
                                    label: t.name,
                                }))}
                            />
                        )}
                    </>
                )}

                {/* Period before Target, and the history between them: the
                    period decides which history is relevant, and the history is
                    what the target should be argued from. Asking for the number
                    first would make the panel below it a post-hoc verdict
                    rather than something to reason with. */}
                <Select
                    label="Period"
                    value={periodType}
                    onChange={setPeriodType}
                    options={PERIODS.map((p) => ({
                        value: p.value,
                        label: p.label,
                    }))}
                />

                <GoalPreview
                    metricId={metricId}
                    subjectType={subjectType}
                    subjectId={subjectId}
                    periodType={periodType}
                    target={target}
                    onUseSuggestion={setTarget}
                />

                {/* The server stores NUMERIC(18,4) and rejects a target of zero or
            less, so the field allows exactly what the column and the CHECK
            constraint allow — no more, and nothing the form would have to
            reject after the fact. */}
                <Field
                    label="Target"
                    value={target}
                    onChange={setTarget}
                    numeric={{ decimals: 4, min: 0 }}
                    hint="The number to reach. For metrics where lower is better, the number to stay under."
                />

                <StretchFields
                    levels={stretch}
                    onChange={setStretch}
                    lowerIsBetter={
                        (goal?.direction ??
                            metrics.find((m) => String(m.id) === metricId)?.direction) ===
                        "lower_is_better"
                    }
                />

                {/* Under Period, because what repeats is the period. A custom
                    range has no next one, so the server refuses that pairing and
                    the option is simply not offered here. */}
                {isSpawnedCopy ? (
                    // A copy exists *because* something else repeats. Offering
                    // the control here would only ever produce a 400, and a
                    // control that cannot succeed is worse than no control.
                    <p className="text-xs text-content-muted">
                        This goal was created automatically by a repeating goal.
                        Change the original to alter how it repeats.
                    </p>
                ) : (
                    <label className="flex items-start gap-2 text-sm text-content-muted">
                        <input
                            type="checkbox"
                            checked={recurring}
                            onChange={(e) => setRecurring(e.target.checked)}
                            className="mt-0.5 accent-brand"
                        />
                        <span>
                            Repeat every period
                            <span className="block text-xs text-content-subtle">
                                A fresh copy with the same target appears when the next{" "}
                                {periodType} begins. Archive the original to stop it.
                            </span>
                        </span>
                    </label>
                )}

                <Field
                    label="Name"
                    value={name}
                    onChange={setName}
                    required={false}
                    hint="Optional. For the goals people talk about by name."
                />

                {isEdit && (
                    <p className="text-xs text-content-muted">
                        The metric and who this is for cannot be changed. Moving
                        a goal to someone else is a delete and a new goal, not
                        an edit — recording it as one would leave a trail saying
                        something that did not happen.
                    </p>
                )}

                <div className="border-t border-edge pt-4">
                    <AppearanceFields
                        kind="goal"
                        chosen={appearance}
                        inherited={inherited}
                        onChange={setAppearance}
                        previewBeside
                    />
                </div>

                {error && (
                    <p
                        role="alert"
                        className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
                    >
                        {error}
                    </p>
                )}

                <div className="flex items-center gap-3 pt-2">
                    <button
                        type="submit"
                        disabled={busy || missing !== null}
                        className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
                    >
                        {busy
                            ? "Saving…"
                            : isEdit
                              ? "Save changes"
                              : "Create goal"}
                    </button>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
                    >
                        Cancel
                    </button>
                    {missing && !busy && (
                        <span className="text-xs text-content-muted">{missing}</span>
                    )}
                </div>
            </form>
        </Modal>
    );
}


/**
 * A value the form shows but cannot change.
 *
 * Rendered rather than omitted: a goal edit form with no metric on it does not
 * read as a goal edit form. Styled like an input so the layout holds, but it is
 * a paragraph — a disabled input would still be a control, and this is not one.
 */
function Fixed({ label, value }: { label: string; value: string }) {
    return (
        <div>
            <span className="block text-sm text-content-muted">{label}</span>
            <p className="mt-1 rounded-md border border-edge bg-bg px-3 py-2 text-content">
                {value}
            </p>
        </div>
    );
}
