// @vitest-environment jsdom
/** Turning sound on for TVs nobody clicks (Phase 24). */
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import TvSoundHelp, { policyCommand } from './TvSoundHelp';

const CHROME = 'Google\\Chrome';

test('nothing to say while every TV plays with sound', () => {
  const { container } = render(<TvSoundHelp tvs={[]} />);
  expect(container.textContent).toBe('');
});

test('names the TVs, with the one-time setting for each browser and their address', () => {
  render(
    <TvSoundHelp
      tvs={[
        { name: 'Sales floor', url: 'http://192.168.1.5:8080/display/abc' },
        { name: 'Break room', url: 'http://192.168.1.5:8080/display/def' },
      ]}
    />,
  );
  expect(screen.getByText('Sound is off on Sales floor, Break room')).toBeTruthy();
  expect(screen.getByText('http://192.168.1.5:8080')).toBeTruthy();
  expect(screen.getByText(/Media autoplay → Allow/)).toBeTruthy();
  expect(screen.getByText(/Autoplay → Allow Audio and Video/)).toBeTruthy();
  expect(screen.getByText(policyCommand(CHROME, 'http://192.168.1.5:8080'))).toBeTruthy();
  // No app to install, and nothing to click on the TV.
  expect(screen.queryByText(/Install/)).toBeNull();
  expect(screen.queryByText(/[Cc]lick/)).toBeNull();
});

test('the policy adds to what IT already allowed, rather than over it', () => {
  const command = policyCommand(CHROME, 'https://goals.internal');
  expect(command).toContain('HKLM:\\SOFTWARE\\Policies\\Google\\Chrome\\AutoplayAllowlist');
  expect(command).toContain('(Get-Item $k).ValueCount + 1');
  expect(command).toContain("-Value 'https://goals.internal'");
});
