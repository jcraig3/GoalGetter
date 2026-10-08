import { describe, expect, it } from 'vitest';

import type { DirectoryRule, DirectoryRun, DirectoryStatus } from '../directory';
import {
  badge,
  describe as describeRule,
  everyHours,
  needsAttention,
  placement,
  shadowed,
  stage,
  summarise,
} from './directorySync';

function run(extra: Partial<DirectoryRun> = {}): DirectoryRun {
  return {
    status: 'ok',
    trigger: 'schedule',
    started_at: '2026-08-26T12:00:00Z',
    finished_at: '2026-08-26T12:00:04Z',
    people_seen: 0,
    created: 0,
    archived: 0,
    needs_review: 0,
    pending: 0,
    applied: 0,
    error: null,
    ...extra,
  };
}

function status(extra: Partial<DirectoryStatus> = {}): DirectoryStatus {
  return {
    available: ['microsoft'],
    provider: 'microsoft',
    enabled: true,
    connected: true,
    last_run: null,
    pending: 0,
    sync_hours: 24,
    ignore_unlicensed: false,
    auth_mode: 'application',
    connected_as: '',
    account_connected: false,
    account_required: false,
    mail_enabled: false,
    mail_from: '',
    ...extra,
  };
}

function rule(extra: Partial<DirectoryRule> = {}): DirectoryRule {
  return {
    id: 1,
    department: '',
    job_title: '',
    office: '',
    group: '',
    role: 'agent',
    team_id: null,
    ...extra,
  };
}

const TEAMS = [
  { id: 1, name: 'Phoenix Sales' },
  { id: 2, name: 'Support' },
];

describe('summarise', () => {
  it('says so plainly when it has never run', () => {
    expect(summarise(null)).toBe('Never run.');
  });

  it('leads with how many people it saw', () => {
    expect(summarise(run({ people_seen: 240 }))).toContain('240 people');
  });

  it('says person rather than people for one', () => {
    // A small thing, and the kind that makes a screen read as written by nobody.
    expect(summarise(run({ people_seen: 1 }))).toContain('1 person');
  });

  it('mentions only what actually happened', () => {
    // A settled company syncs every day and nothing changes. "240 people · 0 new ·
    // 0 left · 0 changed" is four numbers to read to learn nothing.
    expect(summarise(run({ people_seen: 240 }))).toBe('240 people');
  });

  it('counts new arrivals, accounts made, leavers and changes', () => {
    const line = summarise(
      run({ people_seen: 240, created: 3, applied: 2, archived: 1, needs_review: 4 }),
    );

    expect(line).toContain('3 new');
    expect(line).toContain('2 added');
    expect(line).toContain('1 left');
    expect(line).toContain('4 changed');
  });

  it('says the provider’s own words when the run failed', () => {
    const line = summarise(
      run({ status: 'failed', error: 'Microsoft refused the connection (401).' }),
    );

    expect(line).toBe('Microsoft refused the connection (401).');
  });

  it('never reports a count on a failed run', () => {
    // **The most alarming wrong conclusion available here.** A failed run has
    // counts of zero, and "0 people" beside an error reads as *the directory is
    // empty* rather than *we could not read it*.
    const line = summarise(run({ status: 'failed', error: 'Nope.', people_seen: 0 }));

    expect(line).not.toContain('0 people');
  });

  it('still says something when a failure carries no message', () => {
    expect(summarise(run({ status: 'failed', error: null }))).toBe(
      'The last sync failed.',
    );
  });
});

describe('needsAttention', () => {
  it('flags a failure', () => {
    expect(needsAttention(run({ status: 'failed' }))).toBe(true);
  });

  it('flags a partial run', () => {
    // People read *and* something held back — usually one person with no email.
    // A run that quietly does nine-tenths of its job is how somebody spends a
    // week wondering where one person went.
    expect(needsAttention(run({ status: 'partial' }))).toBe(true);
  });

  it('leaves a clean run alone', () => {
    expect(needsAttention(run())).toBe(false);
  });

  it('does not flag never having run', () => {
    // Which is every deployment before somebody switches it on.
    expect(needsAttention(null)).toBe(false);
  });
});

describe('badge', () => {
  it('shows how many people are waiting', () => {
    expect(badge(status({ pending: 12 }))).toBe(12);
  });

  it('shows nothing rather than a zero', () => {
    // A badge reading `0` is a permanent alarm meaning "everything is fine",
    // which teaches somebody to stop seeing badges.
    expect(badge(status({ pending: 0 }))).toBeNull();
  });

  it('shows nothing before anything has loaded', () => {
    expect(badge(null)).toBeNull();
  });
});

describe('stage', () => {
  it('is unavailable when this build reads no directory at all', () => {
    expect(stage(status({ available: [] }))).toBe('unavailable');
  });

  it('is unconnected when there is nothing to switch on', () => {
    // The screen then points at Integrations rather than showing a switch that
    // cannot be flipped.
    expect(stage(status({ connected: false }))).toBe('unconnected');
  });

  it('is off when a connection exists and nobody has turned it on', () => {
    expect(stage(status({ enabled: false }))).toBe('off');
  });

  it('is on once it is running', () => {
    expect(stage(status())).toBe('on');
  });

  it('is unavailable before anything has loaded', () => {
    expect(stage(null)).toBe('unavailable');
  });
});

describe('describe', () => {
  it('reads a rule back as a sentence', () => {
    const line = describeRule(
      rule({ department: 'Sales', role: 'manager', team_id: 1 }),
      TEAMS,
    );

    expect(line).toBe('Anyone in Sales becomes a manager on Phoenix Sales.');
  });

  it('joins several conditions, because a rule is an and', () => {
    // **A row of four mostly-empty boxes does not say what it does**, and "Any"
    // repeated across three columns is exactly the shape that gets misread as an
    // *or*.
    const line = describeRule(
      rule({ department: 'Sales', office: 'Phoenix', team_id: 1 }),
      TEAMS,
    );

    expect(line).toContain('in Sales');
    expect(line).toContain('at Phoenix');
  });

  it('names a job title condition', () => {
    expect(describeRule(rule({ job_title: 'Account Executive' }), TEAMS)).toContain(
      'whose title is Account Executive',
    );
  });

  it('names a group condition', () => {
    expect(describeRule(rule({ group: 'Phoenix Sales' }), TEAMS)).toContain(
      'in the Phoenix Sales group',
    );
  });

  it('calls a rule with no conditions what it is', () => {
    // The catch-all, and the rule most likely to surprise somebody later — so it
    // says "Everyone else" rather than leaving an empty subject.
    expect(describeRule(rule(), TEAMS)).toBe('Everyone else becomes an agent, with no team.');
  });

  it('says plainly when a rule places nobody on a team', () => {
    // Because that leaves them for an admin to assign, which is a real outcome
    // rather than an omission.
    expect(describeRule(rule({ department: 'Sales' }), TEAMS)).toContain('with no team');
  });

  it('survives a team that has since been deleted', () => {
    // `team_id` is SET NULL on delete in the database, but a page holding a stale
    // list must not render "on undefined".
    const line = describeRule(rule({ department: 'Sales', team_id: 99 }), TEAMS);

    expect(line).toContain('with no team');
    expect(line).not.toContain('undefined');
  });

  it('survives a role it has no wording for', () => {
    expect(describeRule(rule({ role: 'wizard' }), TEAMS)).toContain('a wizard');
  });
});

describe('shadowed', () => {
  it('warns on the rule that does nothing, not the one that works', () => {
    // The warning belongs on the row somebody has to change. A message at the top
    // saying "rules 2 and 5" makes them count.
    const found = shadowed([[0, 2]]);

    expect(found.get(2)).toBe(0);
    expect(found.has(0)).toBe(false);
  });

  it('handles a rule shadowed by two earlier ones', () => {
    const found = shadowed([
      [0, 2],
      [1, 2],
    ]);

    // The first one wins, so that is the one worth naming.
    expect(found.get(2)).toBe(0);
  });

  it('reports every shadowed rule, not just the first', () => {
    const found = shadowed([
      [0, 1],
      [0, 2],
    ]);

    expect([...found.keys()].sort()).toEqual([1, 2]);
  });

  it('is empty when nothing clashes', () => {
    expect(shadowed([]).size).toBe(0);
  });
});

describe('placement', () => {
  it('says where somebody would land', () => {
    expect(
      placement({ would_be_role: 'manager', would_be_team_id: 1 }, TEAMS),
    ).toBe('a manager on Phoenix Sales');
  });

  it('says unassigned when no rule places them', () => {
    // Which is a real and common outcome, not a failure — an admin puts them
    // somewhere afterwards.
    expect(placement({ would_be_role: 'agent', would_be_team_id: null }, TEAMS)).toBe(
      'an agent, unassigned',
    );
  });

  it('survives a team that has since been deleted', () => {
    expect(
      placement({ would_be_role: 'agent', would_be_team_id: 99 }, TEAMS),
    ).toContain('unassigned');
  });
});

describe('everyHours', () => {
  it('names the intervals the panel offers', () => {
    expect(everyHours(1)).toBe('every hour');
    expect(everyHours(24)).toBe('daily');
    expect(everyHours(168)).toBe('weekly');
  });

  it('still reads as something for a value set by hand', () => {
    // The column takes any number of hours, so a value edited outside the four
    // the dropdown offers must not come out as "every 72 hours" when "every 3
    // days" is what somebody meant.
    expect(everyHours(6)).toBe('every 6 hours');
    expect(everyHours(72)).toBe('every 3 days');
  });
});

describe('summarise, while a sync is running', () => {
  it('says so rather than falling through to the counts', () => {
    // **A running row has zeroes in every count**, so without this it reported
    // "0 people" — which reads as a sync that ran and found nobody.
    expect(summarise(run({ status: 'running', people_seen: 0 }))).toBe(
      'A sync is running…',
    );
  });

  it('is what somebody sees coming back to the tab mid-run', () => {
    // The request that starts a sync runs the whole read server-side, so leaving
    // the tab does not stop it. Returning to "Never run." made a working sync
    // look like a button that had done nothing.
    expect(summarise(run({ status: 'running' }))).not.toBe('Never run.');
  });
});
