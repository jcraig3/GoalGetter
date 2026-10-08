import { useEffect, useState } from 'react';

import { api } from '../api';
import Toggle from './Toggle';

export interface RoleRule {
  group: string;
  role: string;
}

const ROLES = [
  { value: 'agent', label: 'Agent' },
  { value: 'manager', label: 'Manager' },
  { value: 'admin', label: 'Admin' },
];

/**
 * Roles from groups: signing in sets a person's role from their groups.
 *
 * **The highest role any group gives wins**, and somebody in no listed group
 * keeps the role they have — so a forgotten group never quietly demotes
 * anybody. The last admin is never demoted either. Group names are suggested
 * from what directory sync has read, and can be typed.
 */
export default function SsoRoleRules({
  enabled,
  rules,
  onEnabled,
  onRules,
}: {
  enabled: boolean;
  rules: RoleRule[];
  onEnabled: (on: boolean) => void;
  onRules: (rules: RoleRule[]) => void;
}) {
  const [known, setKnown] = useState<string[]>([]);

  useEffect(() => {
    api<{ group: { value: string }[] }>('/api/admin/directory/values')
      .then((values) => setKnown(values.group.map((g) => g.value)))
      .catch(() => setKnown([]));
  }, []);

  function set(index: number, patch: Partial<RoleRule>) {
    onRules(rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  }

  return (
    <div className="rounded-md border border-edge p-3">
      <Toggle
        label="Set roles from groups"
        hint="On each sign-in, a person gets the highest role any of their groups below gives. Somebody in none of them keeps the role they have, and the last admin is never demoted."
        checked={enabled}
        disabled={rules.length === 0 && !enabled}
        onChange={onEnabled}
      />

      {rules.length > 0 && (
        <ul className="mt-3 space-y-2">
          {rules.map((rule, index) => (
            <li key={index} className="grid grid-cols-[1fr_9rem_auto] items-center gap-2">
              <input
                value={rule.group}
                onChange={(e) => set(index, { group: e.target.value })}
                list="sso-known-groups"
                placeholder="Group name"
                aria-label={`Group ${index + 1}`}
                maxLength={200}
                className="rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content"
              />
              <select
                value={rule.role}
                onChange={(e) => set(index, { role: e.target.value })}
                aria-label={`Role for group ${index + 1}`}
                className="rounded-md border border-edge bg-bg px-2 py-2 text-sm text-content"
              >
                {ROLES.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => onRules(rules.filter((_, i) => i !== index))}
                aria-label={`Remove group ${index + 1}`}
                className="px-2 text-sm text-content-muted hover:text-danger"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <datalist id="sso-known-groups">
        {known.map((group) => (
          <option key={group} value={group} />
        ))}
      </datalist>

      <button
        type="button"
        onClick={() => onRules([...rules, { group: '', role: 'agent' }])}
        className="mt-3 text-sm text-brand hover:underline"
      >
        Add a group
      </button>
      <p className="mt-1 text-xs text-content-subtle">
        Groups come from the sign-in itself when your identity provider sends them, and otherwise
        from what directory sync has read for that person.
      </p>
    </div>
  );
}
