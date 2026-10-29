/**
 * citations.js — remembering which sources an answer came from.
 *
 * THE PROBLEM THIS SOLVES, which is a gap in the backend and not a preference:
 *
 *   `POST /chat` answers with `pdfs` and `urls`. `GET /conversations/{id}`
 *   returns `{seq, ts, question, answer, source}` and stops there — not
 *   because the data is gone, but because that is the shape of the route's
 *   response model. model/history.py does write `pdfs` and `urls` onto every
 *   turn; api.py's `Turn` simply does not select them.
 *
 *   Which means the sources of an answer are reachable by this app for exactly
 *   as long as the response that carried them, and reopening the conversation
 *   tomorrow cannot get them back over HTTP.
 *
 * So they are cached here, per turn, in sessionStorage. Three consequences
 * worth being deliberate about:
 *
 *   The cache is not the truth, it is a memory. A turn with nothing cached
 *   renders with *no* citations — never a guess, never a stale set from a
 *   different turn. An answer whose provenance we cannot prove says nothing
 *   about its provenance.
 *
 *   sessionStorage, not localStorage. These are the specific documents behind
 *   somebody's questions, and they should not outlive the tab on a shared desk.
 *
 *   Keyed by conversation *and* seq, so continuing a conversation adds to it
 *   rather than overwriting, and two tabs on the same conversation agree.
 */

import { readJson, remove, STORAGE, writeJson } from '@/lib/storage';

import { CITATION_KEY_PREFIX } from './chat.constants';

function keyFor(conversationId) {
  return `${CITATION_KEY_PREFIX}.${conversationId}`;
}

/**
 * Remember one turn's sources.
 *
 * A turn with neither pdfs nor urls is not written: an empty record is
 * indistinguishable from "we have not seen this turn", and both correctly
 * render nothing.
 *
 * @param {string} conversationId
 * @param {number} seq
 * @param {{pdfs?: string[], urls?: string[]}} sources
 */
export function rememberCitations(conversationId, seq, { pdfs = [], urls = [] }) {
  if (!conversationId || (pdfs.length === 0 && urls.length === 0)) return;

  const key = keyFor(conversationId);
  const stored = readJson(key, STORAGE.SESSION) ?? {};

  writeJson(key, { ...stored, [seq]: { pdfs, urls } }, STORAGE.SESSION);
}

/**
 * What we know about one conversation's sources, by `seq`.
 *
 * @param {string} conversationId
 * @returns {Record<string, {pdfs: string[], urls: string[]}>}
 */
export function recallCitations(conversationId) {
  if (!conversationId) return {};
  return readJson(keyFor(conversationId), STORAGE.SESSION) ?? {};
}

/** Drop one conversation's cache. Used when the backend says it is gone. */
export function forgetCitations(conversationId) {
  if (conversationId) remove(keyFor(conversationId), STORAGE.SESSION);
}
