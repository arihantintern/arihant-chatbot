import { useCallback, useEffect, useState } from 'react';

import { authApi } from '@/api';

export const SERVICE_STATE = {
  CHECKING: 'checking',
  /** API up, accounts reachable — a sign-in can succeed. */
  READY: 'ready',
  /** API up, no mongodb behind it. Every login will come back a 503. */
  DEGRADED: 'degraded',
  /** Nothing answered. Wrong port, backend not started, no network. */
  OFFLINE: 'offline',
};

/** A `/health` body, as one of the four states above. */
function classify(health) {
  if (!health.ok) return SERVICE_STATE.OFFLINE;
  return health.accounts ? SERVICE_STATE.READY : SERVICE_STATE.DEGRADED;
}

/**
 * Whether signing in can work at all, asked before anyone types a password.
 *
 * This exists because of one specific failure that is otherwise baffling:
 * model/auth.py refuses every login with a 503 when there is no mongodb to
 * read accounts from — "no accounts" must not read as "no password needed".
 * Correct, and from the login form indistinguishable from a server that hates
 * you. `GET /health` reports both facts (`ok`, `mongodb`), so the screen can
 * say which one is wrong before it wastes the person's time.
 *
 * Re-checking is a state bump rather than a second code path: `attempt` is in
 * the effect's dependencies, so raising it re-runs exactly the same request,
 * cancellation and all. One fetch, described once.
 */
export function useServiceHealth() {
  const [status, setStatus] = useState(SERVICE_STATE.CHECKING);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    authApi
      .checkHealth({ signal: controller.signal })
      .then((health) => {
        if (!controller.signal.aborted) setStatus(classify(health));
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus(SERVICE_STATE.OFFLINE);
      });

    return () => controller.abort();
  }, [attempt]);

  const recheck = useCallback(() => {
    setStatus(SERVICE_STATE.CHECKING);
    setAttempt((current) => current + 1);
  }, []);

  /* Someone whose backend was not running will start it and come back to the
     tab. Re-checking on focus means the status is already green when they do —
     but only while something is wrong, so a healthy page is not quietly
     pinging /health every time it is looked at. */
  useEffect(() => {
    if (status === SERVICE_STATE.READY) return undefined;

    const onFocus = () => {
      if (document.visibilityState === 'visible') recheck();
    };

    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [status, recheck]);

  return { status, recheck };
}
