/**
 * One error type for everything the network can do to us.
 *
 * A component should never have to know whether a failure was a 401, a
 * dropped connection or a FastAPI validation body — it asks this object three
 * questions: what do I show the person (`message`), which field is at fault
 * (`fieldErrors`), and is this worth signing them out over (`isAuthFailure`).
 *
 * `message` is always safe to render: it is either the backend's own
 * human-written `detail` — model/auth.py writes those for people, not for
 * logs — or a fallback keyed off the status code.
 */
export class ApiError extends Error {
  /**
   * @param {string} message              what to show the person
   * @param {object} [options]
   * @param {number} [options.status]     http status; 0 means "never arrived"
   * @param {Record<string,string>} [options.fieldErrors]  per-field messages
   * @param {unknown} [options.body]      the parsed response body, for logs
   * @param {unknown} [options.cause]
   */
  constructor(message, { status = 0, fieldErrors = {}, body = null, cause } = {}) {
    super(message, { cause });
    this.name = 'ApiError';
    this.status = status;
    this.fieldErrors = fieldErrors;
    this.body = body;
  }

  /** The request never reached the server: offline, wrong port, CORS, timeout. */
  get isNetworkFailure() {
    return this.status === 0;
  }

  /**
   * The token is missing, expired, tampered with, or names an account that no
   * longer exists — model/api.py answers all of those with 401, and a disabled
   * account with 403. Both mean "this session is over".
   */
  get isAuthFailure() {
    return this.status === 401 || this.status === 403;
  }

  /** The backend is up but a dependency is not — no mongodb, no accounts. */
  get isUnavailable() {
    return this.status === 503;
  }
}

/**
 * What to say when the response carries no usable `detail`.
 *
 * Deliberately plain and non-technical: the person reading this is trying to
 * sign in, not debug a stack. The one place we do get specific is the network
 * failure, because "start the backend" is genuinely the fix during
 * development and "check your connection" is genuinely the fix in production.
 */
export function fallbackMessage(status) {
  if (status === 0) {
    return 'Cannot reach the assistant. Check your connection, and that the API is running.';
  }
  if (status === 401) return 'Wrong email or password.';
  if (status === 403) return 'This account does not have access.';
  if (status === 404) return 'That was not found.';
  if (status === 409) return 'That email already has an account.';
  if (status === 422) return 'Some of those details are not valid.';
  if (status === 429) return 'Too many attempts. Give it a moment and try again.';
  if (status === 503) return 'Accounts are unavailable right now. Try again shortly.';
  if (status >= 500) return 'The assistant ran into a problem. Try again in a moment.';
  return 'Something went wrong. Try again.';
}

/**
 * FastAPI's `detail` is two different shapes, and both arrive here.
 *
 *   HTTPException → a string written for a person
 *                   `{ "detail": "wrong email or password" }`
 *   422 from pydantic → a list of machine-shaped validation failures
 *                   `{ "detail": [{ "loc": ["body","email"], "msg": "..." }] }`
 *
 * The list form is turned into `fieldErrors`, keyed by the field name, so the
 * message lands *under the input that is wrong* instead of in a banner that
 * makes the person hunt for it.
 *
 * @returns {{ message: string, fieldErrors: Record<string,string> }}
 */
export function normaliseDetail(detail, status) {
  if (typeof detail === 'string' && detail.trim()) {
    return { message: sentence(detail), fieldErrors: {} };
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const fieldErrors = {};

    for (const item of detail) {
      // loc is ["body", "email"] — the field is the last string in it, and
      // "body" alone means the whole payload was rejected.
      const location = Array.isArray(item?.loc) ? item.loc : [];
      const field = [...location].reverse().find((part) => typeof part === 'string' && part !== 'body');
      const message = sentence(item?.msg || fallbackMessage(status));

      if (field && !fieldErrors[field]) fieldErrors[field] = message;
    }

    const first = Object.values(fieldErrors)[0];
    return {
      // With a per-field message shown inline, the banner only needs to say
      // that *something* needs fixing — repeating the field message twice on
      // screen reads as two separate problems.
      message: Object.keys(fieldErrors).length > 0 ? fallbackMessage(422) : first || fallbackMessage(status),
      fieldErrors,
    };
  }

  return { message: fallbackMessage(status), fieldErrors: {} };
}

/**
 * The backend writes its messages lowercase and unpunctuated ("wrong email or
 * password"). In a terminal that is house style; under a form field it looks
 * unfinished. This is the one cosmetic liberty we take with its wording.
 */
function sentence(text) {
  const trimmed = String(text).trim().replace(/\s+/g, ' ');
  if (!trimmed) return '';

  const capitalised = trimmed[0].toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capitalised) ? capitalised : `${capitalised}.`;
}
