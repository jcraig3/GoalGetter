/** Activity-log rows as sentences (review §9). */
import { describe, expect, test } from 'vitest';

import { extras, targetWord, what } from './activityWords';

describe('a row', () => {
  test('says what changed, not the stored key', () => {
    const details = {
      name: 'QA2 sprint',
      what: 'The end moved from Fri 2 Oct, 11 pm to Fri 2 Oct, 11:30 pm.',
      note: 'QA2 test earlier end',
      competition_id: 12,
    };
    expect(what('competition.changed_while_running', details)).toBe(
      'changed the running contest “QA2 sprint”',
    );
    // No id, and the sentence written at the time comes through as it was.
    expect(extras(details)).toEqual([
      'The end moved from Fri 2 Oct, 11 pm to Fri 2 Oct, 11:30 pm.',
      'QA2 test earlier end',
    ]);
  });

  test('is built from the action when nobody spelled it out', () => {
    expect(what('leaderboard.created', { name: 'QA2 Team board', visibility: 'org' })).toBe(
      'created the board “QA2 Team board”',
    );
    expect(what('achievement_rule.deleted', { name: 'Big deal' })).toBe(
      'deleted the celebration rule “Big deal”',
    );
    expect(what('wheel.prize_created', { label: 'Lunch' })).toBe(
      'added a prize to the prize wheel “Lunch”',
    );
    expect(what('something_new.happened', null)).toBe('happened the something new');
  });

  test('names who it was for, and the fields it changed', () => {
    expect(what('recognition.sent', { message: 'Sale', recipient: 'Tony Stark' })).toBe(
      'sent a shout-out to “Tony Stark”',
    );
    expect(extras({ name: 'QA2 Badge', recipient: 'Test User' })).toEqual(['to: Test User']);
    expect(extras({ name: 'Sales Feed', fields: ['enabled', 'interval_minutes'] })).toEqual([
      'changed enabled, interval minutes',
    ]);
    expect(extras({ team_id: { from: 17, to: null } })).toEqual(['team: 17 → none']);
    expect(extras({ enabled: 'True', url: 'asset:abc' })).toEqual(['enabled: on']);
  });

  test('says a goal or a number is for somebody, and its values as values', () => {
    expect(targetWord('goal.deleted')).toBe('for ');
    expect(targetWord('user.suspended')).toBe('');
    expect(what('goal.deleted', { subject: 'Test User', target_value: '400.0000' })).toBe('deleted the goal');
    expect(extras({ subject: 'Test User', target_value: '400.0000' }, true)).toEqual(['target: 400']);
    expect(extras({ occurred_at: '2026-10-02T19:00:00' })).toEqual(['when: Fri 2 Oct, 7 pm']);
  });
});

describe('the last internal words (P3-19)', () => {
  test('a metric by its name, and stored values as words', async () => {
    const { knowMetricNames, kindLabel } = await import('./activityWords');
    knowMetricNames([{ key: 'sales_feed_amount_today', name: 'Sales Feed Amount Today' }]);
    expect(extras({ metric: 'sales_feed_amount_today', entity_type: 'user' })).toEqual([
      'metric: Sales Feed Amount Today',
      'entity type: people',
    ]);
    expect(kindLabel('user_identity')).toBe('Imported names');
    expect(kindLabel('walkup')).toBe('Walk-up media');
  });
});

describe('amounts (P4-13)', () => {
  test('a target is grouped like the rest of the app, whichever way it was stored', () => {
    expect(extras({ target: 1000 })).toEqual(['target: 1,000']);
    expect(extras({ target: { from: '1000', to: '2500.5' } })).toEqual(['target: 1,000 → 2,500.5']);
  });

  test('a year is not an amount', () => {
    expect(extras({ year: 2026 })).toEqual(['year: 2026']);
  });
});
