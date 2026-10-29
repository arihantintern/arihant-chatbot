/**
 * session.js — turning a login response into something that survives a reload.
 *
 * WHY LOCALSTORAGE, GIVEN THAT IT IS READABLE BY SCRIPT
 * ----------------------------------------------------
 * The backend authenticates with a bearer token in a header, not a cookie
 * (model/api.py uses HTTPBearer), so an httpOnly cookie is not on the table —
 * a header has to be set by javascript, which means the token has to be
 * reachable by javascript. Given that, Web Storage is the honest choice, and
 * the mitigation that matters is not storing it somewhere cleverer but
 * keeping the app free of injection: no `dangerouslySetInnerHTML`, no
 * third-party script tags, model answers rendered as text.
 *
 * Two backends, one decision by the person signing in:
 *   "keep me signed in" → localStorage, survives closing the browser
 *   left unchecked      → sessionStorage, gone when the tab closes
 */

import { STORAGE, readJson, removeEverywhere, writeJson } from '@/lib/storage';

import { EXPIRY_SKEW_MS, SESSION_STORAGE_KEY } from './auth.constants';

/**
 * @typedef  {object} Session
 * @property {string}  token      the raw JWT
 * @property {number}  expiresAt  epoch ms — absolute, so a reload can judge it
 * @property {boolean} remember   which storage backend it belongs in
 * @property {import('@/api/auth.api').User} user
 */

/**
 * A login/register response, as something storable.
 *
 * `expiresIn` (seconds from now) becomes `expiresAt` (a moment): a duration
 * is meaningless after a reload, because "now" has moved.
 */
export function toSession(credentials, remember) {
  return {
    token: credentials.token,
    expiresAt: Date.now() + credentials.expiresIn * 1000,
    remember: Boolean(remember),
    user: credentials.user,
  };
}

/** Has this token run out — or is it about to? */
export function isExpired(session, skew = EXPIRY_SKEW_MS) {
  return !session || session.expiresAt - skew <= Date.now();
}

/** Milliseconds of useful life left, floored at zero. */
export function timeLeft(session, skew = EXPIRY_SKEW_MS) {
  return Math.max(0, session.expiresAt - skew - Date.now());
}

/**
 * The stored session, or null.
 *
 * Every field is checked rather than trusted. This value comes from a place
 * the person can edit, and a half-valid object — a user with no token — would
 * render a signed-in app that 401s on its first request.
 */
export function loadSession() {
  const stored =
    readJson(SESSION_STORAGE_KEY, STORAGE.LOCAL) ??
    readJson(SESSION_STORAGE_KEY, STORAGE.SESSION);

  return parseSession(stored);
}

/**
 * Validate and revive a stored session. Exported because the cross-tab
 * listener gets its copy from a `storage` event, not from storage.
 *
 * @param {unknown} stored  the parsed JSON, from wherever
 * @returns {Session|null}
 */
export function parseSession(stored) {
  if (!stored || typeof stored !== 'object') return null;

  const { token, expiresAt, user } = stored;
  if (typeof token !== 'string' || !token) return null;
  if (typeof expiresAt !== 'number' || !Number.isFinite(expiresAt)) return null;
  if (!user || typeof user !== 'object' || typeof user.id !== 'string' || !user.id) {
    return null;
  }

  return {
    token,
    expiresAt,
    remember: stored.remember !== false,
    user: {
      ...user,
      // JSON has no date type, so both of these came back as ISO strings.
      createdAt: reviveDate(user.createdAt),
      lastLoginAt: reviveDate(user.lastLoginAt),
    },
  };
}

/**
 * Persist a session, in the backend its `remember` flag chose.
 *
 * The other backend is cleared first: without that, unchecking "keep me
 * signed in" would leave the previous long-lived copy behind, and
 * `loadSession` — which prefers localStorage — would keep finding it.
 */
export function saveSession(session) {
  removeEverywhere(SESSION_STORAGE_KEY);

  return writeJson(
    SESSION_STORAGE_KEY,
    session,
    session.remember ? STORAGE.LOCAL : STORAGE.SESSION,
  );
}

export function clearSession() {
  removeEverywhere(SESSION_STORAGE_KEY);
}

function reviveDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
