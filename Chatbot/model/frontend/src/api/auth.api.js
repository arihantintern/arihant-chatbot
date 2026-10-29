/**
 * auth.api.js — the account endpoints of model/api.py, described once.
 *
 * This layer's other job is translation. The backend speaks snake_case
 * (`last_login_at`, `access_token`) because python does; the app speaks
 * camelCase because javascript does. The seam is here, and it is the reason
 * no component ever contains `user.last_login_at`.
 */

import { api } from './client';
import { ENDPOINTS } from './config';

/**
 * @typedef  {object} User
 * @property {string} id
 * @property {string} email
 * @property {string} name
 * @property {'user'|'admin'} role
 * @property {Date|null} createdAt
 * @property {Date|null} lastLoginAt
 */

/**
 * @typedef  {object} Credentials
 * @property {string} token       the raw JWT
 * @property {number} expiresIn   seconds from now until it stops working
 * @property {User}   user
 */

function toDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The `auth.public()` shape from the backend, in this app's vocabulary. */
function toUser(raw) {
  return {
    id: raw?.id ?? '',
    email: raw?.email ?? '',
    // The backend already defaults a blank name to the local part of the
    // email, so this only covers a malformed response.
    name: raw?.name?.trim() || (raw?.email ?? '').split('@')[0],
    role: raw?.role === 'admin' ? 'admin' : 'user',
    createdAt: toDate(raw?.created_at),
    lastLoginAt: toDate(raw?.last_login_at),
  };
}

/** The `Token` response body — a fresh session. */
function toCredentials(raw) {
  return {
    token: raw?.access_token ?? '',
    expiresIn: Number(raw?.expires_in) || 0,
    user: toUser(raw?.user),
  };
}

/**
 * A new account, signed straight in — the backend logs you in as part of
 * registering, so there is no second round trip and no window where the
 * account exists but the person is still looking at a form.
 *
 * The role is always "user": model/api.py refuses to let a signup name its
 * own role, and promotion happens off the network entirely.
 *
 * @param {{ name?: string, email: string, password: string }} details
 * @returns {Promise<Credentials>}
 */
export async function register({ name, email, password }) {
  const payload = { email: email.trim().toLowerCase(), password };

  /* Omitted rather than sent empty: the backend derives a display name from
     the email when `name` is absent, and "" would be a name of no
     characters, which is a different thing to not having said. */
  const trimmedName = name?.trim();
  if (trimmedName) payload.name = trimmedName;

  return toCredentials(
    await api.post(ENDPOINTS.register, payload, { authenticated: false }),
  );
}

/**
 * @param {{ email: string, password: string }} credentials
 * @returns {Promise<Credentials>}
 */
export async function login({ email, password }) {
  return toCredentials(
    await api.post(
      ENDPOINTS.login,
      { email: email.trim().toLowerCase(), password },
      { authenticated: false },
    ),
  );
}

/**
 * Who the stored token says we are — asked on every boot.
 *
 * This is the only way to find out that a token has gone stale for a reason
 * that is not expiry: the account was disabled, or the API restarted without
 * a fixed `JWT_SECRET` and is now signing with a different one. Both come
 * back as a 401 and the client bridge turns them into a clean sign-out.
 *
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<User>}
 */
export async function fetchMe({ signal } = {}) {
  return toUser(await api.get(ENDPOINTS.me, { signal }));
}

/**
 * Is the service actually able to sign anyone in?
 *
 * `ok` says the API is answering; `mongodb` says whether the accounts
 * collection is reachable behind it. Without mongodb, model/auth.py refuses
 * every login with a 503 — so knowing this *before* someone types a password
 * turns a mysterious failure into an explained one.
 *
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<{ ok: boolean, accounts: boolean }>}
 */
export async function checkHealth({ signal } = {}) {
  const raw = await api.get(ENDPOINTS.health, {
    authenticated: false,
    signal,
    // A health check that hangs for twenty seconds is not a health check.
    timeout: 6000,
  });
  return { ok: Boolean(raw?.ok), accounts: Boolean(raw?.mongodb) };
}
