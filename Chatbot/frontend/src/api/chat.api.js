/**
 * chat.api.js — asking the bot, and reading back what was asked.
 *
 * The same two jobs as auth.api.js: one function per endpoint, and the
 * snake_case → camelCase seam, so nothing above this file ever contains
 * `took_ms` or `conversation_id`.
 *
 * WHAT THIS LAYER CANNOT GIVE YOU, and it matters upstream:
 *
 *   `/chat` answers with `pdfs` and `urls` — which documents were read, which
 *   pages were fetched. `/conversations/{id}` does not: model/api.py's `Turn`
 *   response model is `{seq, ts, question, answer, source}` and nothing more.
 *
 *   Worth being precise about where the loss happens, because it is not where
 *   you would guess: the turn documents in mongodb *do* carry `pdfs`, `urls`,
 *   `standalone` and `timing_ms` — model/history.py writes all of them. It is
 *   the *route* that narrows them on the way out. So the data exists and this
 *   app cannot reach it; widening that one pydantic model would hand it over.
 *
 *   Until then a *live* answer can show its citations and a *reopened* one
 *   cannot reconstruct them. The provider keeps a client-side cache for the
 *   turns it has seen, and a turn with nothing cached shows no citations at
 *   all rather than a plausible guess.
 */

import { api } from './client';
import { CHAT_TIMEOUT_MS, ENDPOINTS } from './config';

/**
 * @typedef  {object} Answer
 * @property {string} answer          the reply, as markdown-ish prose
 * @property {string|null} source     which lane answered — see features/chat/sources.js
 * @property {string} conversationId  new or continued; always send it back
 * @property {number} seq             this turn's number within the conversation
 * @property {string|null} standalone the rewritten, self-contained question
 * @property {string[]} pdfs          filenames of the documents that were read
 * @property {string[]} urls          pages the web lane fetched
 * @property {number|null} tookMs
 */

/**
 * @typedef  {object} Conversation
 * @property {string} id
 * @property {string} title
 * @property {number} turns
 * @property {Date|null} startedAt
 * @property {Date|null} lastAt
 * @property {string|null} origin   which client started it: 'api', 'cli', …
 */

/**
 * @typedef  {object} Turn
 * @property {number} seq
 * @property {Date|null} at
 * @property {string} question
 * @property {string|null} answer   null when the chain failed on this turn
 * @property {string|null} source
 */

function toDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Defensive: the field is `list[str]` server-side, but a null is one bad
    response away from a `.map` on undefined in a component. */
function toStrings(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item) : [];
}

function toAnswer(raw) {
  return {
    answer: raw?.answer ?? '',
    source: raw?.source ?? null,
    conversationId: raw?.conversation_id ?? '',
    seq: Number(raw?.seq) || 0,
    standalone: raw?.standalone ?? null,
    pdfs: toStrings(raw?.pdfs),
    urls: toStrings(raw?.urls),
    tookMs: Number.isFinite(raw?.took_ms) ? raw.took_ms : null,
  };
}

function toConversation(raw) {
  return {
    id: raw?.id ?? '',
    /* The title is `question[:120]`, set when the conversation is created and
       never updated (model/history.py). An empty one is possible for a row
       written before that existed. */
    title: raw?.title?.trim() || 'Untitled conversation',
    turns: Number(raw?.turns) || 0,
    startedAt: toDate(raw?.started_at),
    lastAt: toDate(raw?.last_at),
    /* Renamed: `interface` is a reserved word in enough languages, and a
       future TypeScript pass would not thank us for the field. */
    origin: raw?.interface ?? null,
  };
}

function toTurn(raw) {
  return {
    seq: Number(raw?.seq) || 0,
    at: toDate(raw?.ts),
    question: raw?.question ?? '',
    /* Kept as null rather than defaulted to '': model/history.py saves the
       turn even when the chain throws, and "the answer failed" has to stay
       distinguishable from "the answer was empty". */
    answer: typeof raw?.answer === 'string' ? raw.answer : null,
    source: raw?.source ?? null,
  };
}

/**
 * Ask a question — on a new conversation, or on an existing one of yours.
 *
 * Omitting `conversationId` starts a conversation; sending one continues it,
 * and model/api.py answers a 404 if that id is not yours (the same 404 as "no
 * such conversation", deliberately, so the api cannot be used to discover
 * which ids exist).
 *
 * @param {{ question: string, conversationId?: string|null, signal?: AbortSignal }} input
 * @returns {Promise<Answer>}
 */
export async function ask({ question, conversationId, signal }) {
  const payload = { question };
  if (conversationId) payload.conversation_id = conversationId;

  return toAnswer(
    await api.post(ENDPOINTS.chat, payload, { signal, timeout: CHAT_TIMEOUT_MS }),
  );
}

/**
 * Your conversations, most recently used first.
 *
 * @param {{ limit?: number, signal?: AbortSignal }} [options]
 * @returns {Promise<Conversation[]>}
 */
export async function listConversations({ limit = 30, signal } = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  const rows = await api.get(`${ENDPOINTS.conversations}?${query}`, { signal });

  return Array.isArray(rows) ? rows.map(toConversation) : [];
}

/**
 * One conversation's turns, oldest first.
 *
 * @param {string} id
 * @param {{ signal?: AbortSignal }} [options]
 * @returns {Promise<Turn[]>}
 */
export async function fetchTranscript(id, { signal } = {}) {
  const rows = await api.get(ENDPOINTS.conversation(id), { signal });
  return Array.isArray(rows) ? rows.map(toTurn) : [];
}

/**
 * Your own turns, by text. Whole words only — `history.find` runs a mongodb
 * `$text` query and a text index matches whole terms, so "bandh" finds nothing
 * and "bandhan" finds the lot.
 *
 * @param {string} query
 * @param {{ limit?: number, signal?: AbortSignal }} [options]
 * @returns {Promise<Turn[]>}
 */
export async function searchTurns(query, { limit = 20, signal } = {}) {
  const trimmed = query.trim();
  if (!trimmed) return [];

  /* URLSearchParams rather than a template string: a question typed into the
     palette is arbitrary text, and a `&` or a `#` in it would otherwise
     silently truncate the search. */
  const params = new URLSearchParams({ q: trimmed, limit: String(limit) });
  const rows = await api.get(`${ENDPOINTS.search}?${params}`, { signal });

  return Array.isArray(rows) ? rows.map(toTurn) : [];
}
