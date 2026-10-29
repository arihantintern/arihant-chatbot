/**
 * validation.js — the same rules the backend enforces, applied a round trip
 * earlier.
 *
 * This is a *mirror*, not a second opinion. Every constant here has a
 * counterpart in model/config.py or model/auth.py, and they are named in the
 * comments so that a change on that side has a findable consequence on this
 * one. The backend stays the authority — nothing here is a security control,
 * because anything in the browser can be edited by the person using it. What
 * it buys is the difference between "that is not an email address" appearing
 * as you leave the field and appearing two seconds after you press the button.
 *
 * Mirrored from the backend:
 *   PASSWORD_MIN_LENGTH   config.PASSWORD_MIN_LEN = 8
 *   PASSWORD_MAX_BYTES    auth._MAX_PASSWORD_BYTES = 72 (bcrypt's real limit)
 *   NAME_MAX_LENGTH       api.Register.name max_length = 80
 *   EMAIL_PATTERN         auth._EMAIL
 */

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_BYTES = 72;
export const NAME_MAX_LENGTH = 80;

/**
 * Deliberately the backend's regex, character for character.
 *
 * It rejects the shapes that are obviously not an address and does not try to
 * be RFC 5322 — the address being *deliverable* is a different question, and
 * not one a regex gets to answer. Using a stricter pattern here than the
 * backend uses would mean refusing addresses the API would happily accept.
 */
export const EMAIL_PATTERN = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/;

/**
 * The length bcrypt actually measures.
 *
 * bcrypt hashes the first 72 *bytes* and silently ignores the rest, so two
 * different long passwords can be the same password. The backend rejects
 * rather than truncates, and counts bytes — one emoji is four of them, and a
 * name in Devanagari is three per character. `password.length` would let a
 * 40-character password through to a 400 from the API.
 */
export function byteLength(text) {
  return new TextEncoder().encode(text).length;
}

/** @returns {string|null} the message to show, or null when valid */
export function validateEmail(value) {
  const email = value.trim();

  if (!email) return 'Enter your email address.';
  if (!EMAIL_PATTERN.test(email)) return 'That does not look like an email address.';

  return null;
}

/**
 * @param {string} value
 * @param {{ isNew?: boolean }} [options]
 *   `isNew` applies the minimum length. Signing in does not: the password is
 *   either the right one or it is not, and telling someone their existing
 *   password is too short to try is both wrong and confusing. model/api.py
 *   makes exactly this distinction — `Login.password` has no min_length.
 */
export function validatePassword(value, { isNew = false } = {}) {
  if (!value) return 'Enter your password.';

  if (isNew && value.length < PASSWORD_MIN_LENGTH) {
    return `Use at least ${PASSWORD_MIN_LENGTH} characters.`;
  }

  if (byteLength(value) > PASSWORD_MAX_BYTES) {
    return `That is too long — ${PASSWORD_MAX_BYTES} bytes is the limit.`;
  }

  return null;
}

export function validateConfirmation(password, confirmation) {
  if (!confirmation) return 'Type your password again.';
  if (password !== confirmation) return 'Those two passwords are different.';

  return null;
}

/** The name is optional — the backend falls back to the local part of the email. */
export function validateName(value) {
  const name = value.trim();

  if (name.length > NAME_MAX_LENGTH) {
    return `Keep it under ${NAME_MAX_LENGTH} characters.`;
  }

  return null;
}

/* ------------------------------------------------------------------ strength */

/**
 * Patterns that make a password guessable regardless of how long it is.
 * A short list on purpose: this is a nudge, not a dictionary attack.
 */
const WEAK_PATTERNS = [
  /^(.)\1+$/, //                     aaaaaaaa
  /(?:012|123|234|345|456|567|678|789|890)/, // a run of digits
  /(?:abc|qwe|asd|zxc|password|letmein|welcome|admin|arihant)/i,
];

export const STRENGTH_LABELS = ['Too short', 'Weak', 'Fair', 'Strong', 'Excellent'];

/**
 * How good is this password, on a 0–4 scale?
 *
 * Advisory, and only that. The backend's one rule is eight characters, so a
 * "Weak" password still registers — a meter that silently blocks submission
 * is a rule pretending to be a hint. This exists to make a better password
 * the obvious choice, not the only one.
 *
 * @returns {{ score: number, label: string, suggestion: string|null }}
 */
export function passwordStrength(password) {
  if (!password) return { score: 0, label: '', suggestion: null };

  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((pattern) =>
    pattern.test(password),
  ).length;

  let score = 0;
  if (password.length >= PASSWORD_MIN_LENGTH) score += 1;
  if (password.length >= 12) score += 1;
  if (classes >= 2) score += 1;
  if (classes >= 3 && password.length >= 10) score += 1;

  /* Length cannot buy its way out of being a pattern: "12345678901234" is
     long, varied by nothing, and guessed instantly. */
  if (WEAK_PATTERNS.some((pattern) => pattern.test(password))) score = Math.min(score, 1);

  // Below the backend's minimum, nothing else about it matters yet.
  if (password.length < PASSWORD_MIN_LENGTH) score = 0;

  return {
    score,
    label: STRENGTH_LABELS[score],
    suggestion: suggest(password, classes),
  };
}

/** The single most useful next step — one, so it reads as help, not a lecture. */
function suggest(password, classes) {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return `${PASSWORD_MIN_LENGTH - password.length} more character${
      PASSWORD_MIN_LENGTH - password.length === 1 ? '' : 's'
    } to go.`;
  }
  if (WEAK_PATTERNS.some((pattern) => pattern.test(password))) {
    return 'Avoid common words and runs of keys.';
  }
  if (classes < 2) return 'Mix in capitals, numbers or symbols.';
  if (password.length < 12) return 'Longer is stronger — aim for 12 or more.';

  return null;
}
