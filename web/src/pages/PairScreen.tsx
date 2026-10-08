import { useNavigate } from 'react-router-dom';

import PairingCode from '../components/PairingCode';

/**
 * What a new television shows while it waits to be told what it plays.
 *
 * Somebody opens one short address on the TV — the only thing they will ever
 * key in with a remote — and everything after that happens on a laptop. See
 * `PairingCode`, which a disconnected screen shows too.
 */
export default function PairScreen() {
  const navigate = useNavigate();
  return <PairingCode onPaired={(url) => navigate(url, { replace: true })} />;
}
