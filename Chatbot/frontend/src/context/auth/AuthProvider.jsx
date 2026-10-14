import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { authApi } from '@/api';

import { AuthContext } from './AuthContext';
import {
  AUTH_STATUS,
  MAX_TIMEOUT_MS,
  SESSION_STORAGE_KEY,
  SIGN_OUT_NOTICES,
  SIGN_OUT_REASON,
} from './auth.constants';
import {
  clearSession,
  isExpired,
  loadSession,
  parseSession,
  saveSession,
  timeLeft,
  toSession,
} from './session';
import {
  clearCurrentSession,
  getSession,
  onSessionLost,
  setSession,
} from './sessionStore';

/**
 * Owns the session: who is signed in, and for how much longer.
 *
 * Four things end a session, and all four end it the same way — through
 * `endSession`, which is the only function that writes the anonymous state:
 *
 *   the person asks            signOut()
 *   the token runs out here    the expiry timer, and the wake-up check
 *   the API rejects the token  the client's auth bridge
 *   another tab signs out      the `storage` event
 *
 * The token itself is NOT here — it lives in ./sessionStore, outside React
 * entirely. Nothing renders it, so state would only mean re-rendering the app
 * whenever it changed; and a ref would tie its availability to when this
 * component's effects happened to run, which is how a reload came to look like
 * a logout. That file explains the failure in full. This one decides what is
 * on screen.
 */
/**
 * The state to render on the very first frame, read straight from storage.
 *
 * In the initialiser rather than in an effect, and that is the whole trick to
 * a boot with no flicker: an effect runs *after* the first paint, so deciding
 * there would mean painting the login screen for one frame before replacing
 * it with the app. Pure — it reads storage and returns a value, and the
 * writing and confirming happen later, in an effect, where they belong.
 */
function initialState() {
  /* The store has already read storage, at module load. Reading *it* rather
     than storage again means the frame that decides "signed in" and the token
     that will be sent on the first request come from the same value. */
  const live = getSession();
  if (live) {
    /* Trusted optimistically and confirmed with /auth/me in the background.
       Making everyone wait on a round trip to be told they are still signed in
       is a worse trade than signing out the rare stale session a moment late. */
    return { status: AUTH_STATUS.AUTHENTICATED, user: live.user, notice: null };
  }

  /* No live session. Storage may still hold a dead one, which is worth reading
     for the sole purpose of explaining why they are looking at a login form. */
  const stored = loadSession();

  if (!stored) return { status: AUTH_STATUS.ANONYMOUS, user: null, notice: null };

  if (isExpired(stored)) {
    return {
      status: AUTH_STATUS.ANONYMOUS,
      user: null,
      notice: SIGN_OUT_NOTICES[SIGN_OUT_REASON.EXPIRED],
    };
  }

  return { status: AUTH_STATUS.ANONYMOUS, user: null, notice: null };
}

export function AuthProvider({ children }) {
  const [state, setState] = useState(initialState);

  const expiryTimer = useRef(null);

  /* ------------------------------------------------------------ ending it */

  const endSession = useCallback((reason) => {
    clearTimeout(expiryTimer.current);
    expiryTimer.current = null;
    clearCurrentSession();
    clearSession();

    setState({
      status: AUTH_STATUS.ANONYMOUS,
      user: null,
      notice: SIGN_OUT_NOTICES[reason] ?? null,
    });
  }, []);

  /* The API rejecting the token is one of the four ways a session ends, and
     the store is what hears about it first. Registering here rather than
     owning the whole bridge keeps the ordering guarantee in the module while
     the *consequence* stays with the component that can act on it. Any loss
     reported before this ran is replayed — see sessionStore.onSessionLost. */
  useEffect(() => {
    onSessionLost((error) => {
      /* model/auth.py words its own 401 for an expired token ("this session
         has expired -- log in again"). Reading it back is what lets the login
         screen say "your session expired" instead of the vaguer "no longer
         valid" — which is what a disabled account or a restarted backend
         gets. */
      endSession(
        /expired/i.test(error.message)
          ? SIGN_OUT_REASON.EXPIRED
          : SIGN_OUT_REASON.REVOKED,
      );
    });
  }, [endSession]);

  /**
   * Arm the sign-out timer.
   *
   * Re-arms in chunks rather than trusting one long delay: setTimeout's delay
   * is a signed 32-bit int, and an overflow fires immediately — which here
   * would sign the person out the moment they signed in. A 12-hour token
   * never gets near the limit, but this timer is the one place where being
   * wrong is indistinguishable from a bug in the login.
   */
  const scheduleExpiry = useCallback(
    (session) => {
      /* A local, self-re-arming function rather than a recursive call back
         into this callback — which would be a reference to a `const` from
         inside its own initialiser. */
      function arm() {
        clearTimeout(expiryTimer.current);

        if (getSession() !== session) return; // superseded by a newer one

        if (isExpired(session)) {
          endSession(SIGN_OUT_REASON.EXPIRED);
          return;
        }

        expiryTimer.current = setTimeout(arm, Math.min(timeLeft(session), MAX_TIMEOUT_MS));
      }

      arm();
    },
    [endSession],
  );

  /* ---------------------------------------------------------- starting it */

  const applySession = useCallback(
    (session, { persist = true } = {}) => {
      setSession(session);
      if (persist) saveSession(session);
      scheduleExpiry(session);

      setState({
        status: AUTH_STATUS.AUTHENTICATED,
        user: session.user,
        notice: null,
      });
    },
    [scheduleExpiry],
  );

  /* -------------------------------------------------------------- the boot

     By the time this runs, two things have already happened: ./sessionStore
     read storage at module load and published the token, and `initialState()`
     used that to decide what is on screen. What is left is everything neither
     a module nor a render may do — writing to storage, arming a timer, and
     asking the API whether the token it found is still good. */
  useEffect(() => {
    const live = getSession();

    if (!live) {
      /* Nothing usable is live. Storage may still hold an expired session,
         whose notice `initialState` has already put on screen — taking the
         dead key out is the part that had to wait for an effect. */
      if (loadSession()) clearSession();
      return undefined;
    }

    scheduleExpiry(live);

    const controller = new AbortController();

    authApi
      .fetchMe({ signal: controller.signal })
      .then((user) => {
        if (controller.signal.aborted) return;
        /* The name or the role may have changed since this token was issued —
           `python auth.py role <email> admin` happens outside this app
           entirely. Take the API's copy as the truth. */
        applySession({ ...live, user });
      })
      .catch(() => {
        /* Nothing to do, and that is deliberate. A *rejected* token has
           already been dealt with by the auth bridge; anything else — offline,
           the API restarting, a timeout — is not a reason to throw away a
           session that still has hours left on it. */
      });

    return () => controller.abort();
  }, [applySession, scheduleExpiry]);

  /* --------------------------------------------------- clocks and other tabs */

  /**
   * A laptop that slept through the expiry.
   *
   * Background timers get throttled and can fire late, so the moment the tab
   * becomes visible again the expiry is re-checked against the real clock
   * rather than against whenever the timer got round to it.
   */
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== 'visible') return;

      const session = getSession();
      if (session && isExpired(session)) endSession(SIGN_OUT_REASON.EXPIRED);
    };

    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [endSession]);

  /**
   * Signing out in one tab signs out the others.
   *
   * `storage` events only fire for *other* documents, which is exactly the
   * case worth handling: two tabs open, one of them signs out, and the second
   * would otherwise keep showing a signed-in shell over a dead token.
   */
  useEffect(() => {
    const onStorage = (event) => {
      if (event.key !== null && event.key !== SESSION_STORAGE_KEY) return;

      // The whole store was cleared (key === null), or our key was removed.
      if (event.key === null || event.newValue === null) {
        if (getSession()) endSession(SIGN_OUT_REASON.MANUAL);
        return;
      }

      let incoming;
      try {
        incoming = parseSession(JSON.parse(event.newValue));
      } catch {
        return; // not something we wrote
      }

      // Another tab signed in — adopt it rather than sitting on a stale view.
      if (incoming && !isExpired(incoming) && incoming.token !== getSession()?.token) {
        applySession(incoming, { persist: false });
      }
    };

    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [applySession, endSession]);

  /* Nothing should outlive the provider holding a timer. */
  useEffect(() => () => clearTimeout(expiryTimer.current), []);

  /* ------------------------------------------------------------- the actions
     signIn and signUp deliberately let `ApiError` through. The form is the
     only thing that knows where a message about a wrong password should
     appear, so swallowing the error here and setting a global "auth error"
     would take that decision away from it. */

  const signIn = useCallback(
    async ({ email, password, remember = true }) => {
      const credentials = await authApi.login({ email, password });
      applySession(toSession(credentials, remember));
      return credentials.user;
    },
    [applySession],
  );

  const signUp = useCallback(
    async ({ name, email, password, remember = true }) => {
      const credentials = await authApi.register({ name, email, password });
      applySession(toSession(credentials, remember));
      return credentials.user;
    },
    [applySession],
  );

  /**
   * Sign out — locally, and that is the whole story.
   *
   * There is no /auth/logout to call: the token is a signed JWT and the
   * backend keeps no session table (model/auth.py: "stateless on purpose"),
   * so nothing on the server needs telling. Forgetting the token *is* the
   * sign-out. The consequence worth knowing: a copy of the token stolen
   * before this point stays valid until it expires.
   */
  const signOut = useCallback(() => {
    endSession(SIGN_OUT_REASON.MANUAL);
  }, [endSession]);

  const dismissNotice = useCallback(() => {
    setState((current) => (current.notice ? { ...current, notice: null } : current));
  }, []);

  const value = useMemo(
    () => ({
      status: state.status,
      user: state.user,
      isAuthenticated: state.status === AUTH_STATUS.AUTHENTICATED,
      isAdmin: state.user?.role === 'admin',
      notice: state.notice,
      signIn,
      signUp,
      signOut,
      dismissNotice,
    }),
    [state, signIn, signUp, signOut, dismissNotice],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
