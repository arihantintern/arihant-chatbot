/**
 * sessionStore.js — where the live session actually lives.
 *
 * OUTSIDE REACT, AND THAT IS THE POINT.
 *
 * Nothing renders the token. Keeping it in state would re-render the whole app
 * every time it changed, and keeping it in a ref inside the provider makes its
 * availability depend on *when React got round to running that provider's
 * effects* — which is the bug this module exists to eliminate.
 *
 * React flushes effects child-first. So a provider mounted inside the auth
 * provider that fetches on mount (ChatProvider does, for the conversation
 * history) runs its request BEFORE the auth provider's own effects. With the
 * token published from an effect, that first request went out with no
 * Authorization header; model/api.py answers a missing header with the same
 * 401 it uses for a rejected one — `{"detail": "log in first"}` — and the app
 * signed the person out one frame after restoring them. A reload looked like a
 * logout.
 *
 * A module has no such ordering problem. This file is evaluated once, when the
 * module graph is built, which is strictly before any component renders and
 * long before any effect runs. By the time anything can call `fetch`, the token
 * is already here.
 *
 * So the provider's job narrows to what only a component can do: deciding what
 * is on screen, arming timers, and reacting to other tabs. The token itself is
 * this module's, from the first line of the first frame.
 */

import { configureAuthBridge } from '@/api';

import { isExpired, loadSession } from './session';

const NOOP = () => {};

/**
 * Read straight from storage at module load.
 *
 * An expired stored session is treated as no session: the provider still reads
 * storage itself to put the "your session expired" notice on screen, but a
 * token that is already dead must never be *sent*.
 */
function restore() {
  const stored = loadSession();
  return stored && !isExpired(stored) ? stored : null;
}

let current = restore();
let onLost = NOOP;

/** A loss reported before anyone was listening. See `onSessionLost`. */
let pending = null;

/** @returns {import('./session').Session|null} */
export function getSession() {
  return current;
}

export function setSession(session) {
  current = session;
}

export function clearCurrentSession() {
  current = null;
}

/**
 * Register what to do when the API rejects the token.
 *
 * A loss that arrives before this is called is held and replayed, rather than
 * dropped. That window is small but real — a request can be in flight before
 * the provider's effects run — and losing a genuine revocation there would
 * leave a signed-in shell over a dead token, which is the exact failure the
 * whole sign-out path exists to prevent.
 *
 * @param {(error: import('@/api').ApiError) => void} handler
 */
export function onSessionLost(handler) {
  onLost = handler;

  if (pending) {
    const error = pending;
    pending = null;
    handler(error);
  }
}

/* The wiring, done once at module load. `getToken` reads `current` at call
   time, so it always reports the session that is true now rather than the one
   that existed when this ran. */
configureAuthBridge({
  getToken: () => current?.token ?? null,

  onAuthFailure: (error) => {
    if (!current) return; // already signed out; there is nothing to end

    if (onLost === NOOP) {
      pending = error;
      return;
    }

    onLost(error);
  },
});
