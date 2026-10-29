/**
 * Shared vocabulary for the auth module.
 *
 * The strings live here rather than inline so that a state machine with three
 * states cannot quietly grow a fourth spelled 'anonymous ' with a space in it.
 */

/** Where the app is in the "do we know who this is?" question. */
export const AUTH_STATUS = {
  /** Reading the stored session and confirming it with the API. */
  LOADING: 'loading',
  /** No session. The auth screens are what to show. */
  ANONYMOUS: 'anonymous',
  AUTHENTICATED: 'authenticated',
};

/**
 * Why a session ended. This is the difference between "you signed out" and
 * "you were signed out", which the person absolutely needs told apart — the
 * second one is alarming if it happens without explanation.
 */
export const SIGN_OUT_REASON = {
  /** They asked. */
  MANUAL: 'manual',
  /** The 12-hour token ran out, in this tab or between visits. */
  EXPIRED: 'expired',
  /**
   * The API rejected a token we thought was fine: the account was disabled,
   * or the backend restarted without a fixed JWT_SECRET and is now signing
   * with a different one (config.py calls that JWT_EPHEMERAL — it is the
   * normal case in development).
   */
  REVOKED: 'revoked',
};

/**
 * What the login screen says about it, keyed by reason.
 *
 * `tone` matches the Alert component's tones. A deliberate sign-out gets a
 * quiet confirmation; being signed out gets an explanation.
 */
export const SIGN_OUT_NOTICES = {
  [SIGN_OUT_REASON.MANUAL]: {
    tone: 'success',
    message: 'You have been signed out.',
  },
  [SIGN_OUT_REASON.EXPIRED]: {
    tone: 'info',
    message: 'Your session has expired. Sign in again to pick up where you left off.',
  },
  [SIGN_OUT_REASON.REVOKED]: {
    tone: 'warning',
    message: 'Your session is no longer valid. Please sign in again.',
  },
};

/** Where the session is kept. See lib/storage.js for the local/session split. */
export const SESSION_STORAGE_KEY = 'arihant.session';

/**
 * Treat a token as dead this long before it actually is.
 *
 * Clocks disagree, and a request that leaves with four seconds of validity
 * left arrives with none. Better to ask for a fresh sign-in a moment early
 * than to let someone lose a half-typed question to a 401.
 */
export const EXPIRY_SKEW_MS = 30_000;

/**
 * setTimeout stores its delay in a signed 32-bit int; anything larger
 * overflows and fires *immediately*, which for this timer would mean signing
 * the person out the instant they logged in. A 12-hour token never comes
 * close, but the sign-out timer re-arms in chunks rather than trusting that.
 */
export const MAX_TIMEOUT_MS = 2_147_483_647;
