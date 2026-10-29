/**
 * client.js — the single place this app talks to the network.
 *
 * Everything above it (`auth.api.js`, later `chat.api.js`) is a thin, typed
 * description of one endpoint. Everything below it — headers, the bearer
 * token, timeouts, JSON parsing, error shapes — is settled here once.
 *
 * THE AUTH BRIDGE
 * ---------------
 * Requests need the token, and a 401 needs to sign the person out. Neither
 * belongs in a component, and passing a token down as an argument to every
 * call is the prop-drilling problem wearing a different hat.
 *
 * So the auth provider *registers* two functions here at mount: one that
 * hands over the current token, one to call when the server says the session
 * is over. The dependency points inward — the client knows nothing about
 * React, and the provider owns the state. See context/auth/AuthProvider.jsx.
 */

import { ApiError, fallbackMessage, normaliseDetail } from './ApiError';
import { API_BASE_URL, REQUEST_TIMEOUT_MS } from './config';

let readToken = () => null;
let handleAuthFailure = () => {};

/**
 * Wire the client to the session. Called once, by the auth provider.
 *
 * @param {object} bridge
 * @param {() => string|null} bridge.getToken
 * @param {(error: ApiError) => void} bridge.onAuthFailure
 */
export function configureAuthBridge({ getToken, onAuthFailure }) {
  if (typeof getToken === 'function') readToken = getToken;
  if (typeof onAuthFailure === 'function') handleAuthFailure = onAuthFailure;
}

/**
 * One HTTP request, resolved to parsed JSON or rejected with an `ApiError`.
 *
 * @param {string} path                       e.g. '/auth/login'
 * @param {object} [options]
 * @param {'GET'|'POST'|'PATCH'|'DELETE'} [options.method='GET']
 * @param {unknown} [options.body]            serialised as JSON when present
 * @param {boolean} [options.authenticated=true]
 *   Send the bearer token, and treat a 401/403 as "this session is over".
 *   Login and register pass `false`: there is no session yet, and a 401 there
 *   means *this password* was wrong — signing out over it would be a loop.
 * @param {AbortSignal} [options.signal]      the caller's own cancellation
 * @param {number} [options.timeout]
 * @returns {Promise<any>} the parsed body, or `null` for 204 No Content
 */
export async function request(
  path,
  {
    method = 'GET',
    body,
    authenticated = true,
    signal,
    timeout = REQUEST_TIMEOUT_MS,
  } = {},
) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  /* Whether a token actually went out, which is not the same question as
     whether one was meant to. See the sign-out guard further down. */
  let credentialed = false;

  if (authenticated) {
    const token = readToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
      credentialed = true;
    }
  }

  /* Two things can cancel this request: our own timeout, and the caller
     (a component unmounting, a newer request superseding this one). They
     have to be told apart afterwards — a timeout is an error worth showing,
     a caller's cancellation is not — so the timeout sets a flag. */
  const controller = new AbortController();
  let timedOut = false;

  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeout);

  const forwardAbort = () => controller.abort();
  signal?.addEventListener('abort', forwardAbort, { once: true });

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut) {
      throw new ApiError(
        'The assistant took too long to answer. Try again.',
        { status: 0, cause: error },
      );
    }
    /* The caller cancelled deliberately. Let the AbortError through so a
       `useEffect` cleanup can ignore it, rather than dressing an intentional
       cancellation up as a failure the person needs to read about. */
    if (signal?.aborted) throw error;

    /* fetch() rejects with a bare TypeError for every genuine network
       problem — offline, connection refused, a CORS preflight the browser
       would not let us see. They are indistinguishable from here, so they
       share one honest message. */
    throw new ApiError(fallbackMessage(0), { status: 0, cause: error });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', forwardAbort);
  }

  const payload = await readBody(response);

  if (!response.ok) {
    const { message, fieldErrors } = normaliseDetail(payload?.detail, response.status);
    const error = new ApiError(message, {
      status: response.status,
      fieldErrors,
      body: payload,
    });

    /* Only a request that actually CARRIED a token can lose a session, and
       that distinction is load-bearing.

       model/api.py answers a missing Authorization header with the same 401 it
       uses for a rejected one — `{"detail": "log in first"}`. So if this
       branch keyed off `authenticated` alone, any caller that fired before the
       token was reachable would be reporting "the server rejected our session"
       when the truth is "we forgot to send one", and the person would be
       signed out of an app they were correctly signed in to.

       Keying off `credentialed` makes that impossible: no token sent, no
       session to lose. A genuine expiry or revocation always carries the
       token that was refused, so nothing real is missed. */
    if (credentialed && error.isAuthFailure) handleAuthFailure(error);

    throw error;
  }

  return payload;
}

/**
 * The body, whatever shape it turns up in.
 *
 * 204 (which `/auth/password` returns) has no body at all, and an error from
 * something in front of the API — a dev proxy, a tunnel — is usually HTML.
 * Neither should throw a parse error on top of the real failure.
 */
async function readBody(response) {
  if (response.status === 204) return null;

  const text = await response.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch {
    /* Not JSON. Keep it as a `detail` string so the error path can still say
       something specific, but cap it — nobody needs a page of HTML in a
       banner. */
    return { detail: text.slice(0, 200) };
  }
}

export const api = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
};
