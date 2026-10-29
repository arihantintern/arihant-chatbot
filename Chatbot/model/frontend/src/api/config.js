/**
 * Where the backend is, and how long we are willing to wait for it.
 *
 * The default matches `uvicorn api:app --reload`, which is how model/api.py
 * documents running itself. Override it per environment with a Vite env var
 * (see .env.example) — never by editing this file, which is checked in.
 */

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';

/** No trailing slash, so `${API_BASE_URL}/auth/login` is always well formed. */
export const API_BASE_URL = String(
  import.meta.env.VITE_API_BASE_URL || DEFAULT_BASE_URL,
).replace(/\/+$/, '');

/**
 * Auth and health calls are quick — anything slower than this is a backend
 * that is down rather than one that is thinking.
 */
export const REQUEST_TIMEOUT_MS = 20_000;

/**
 * `/chat`'s own budget, and it is deliberately enormous.
 *
 * Three costs stack up on one blocking request. `chain.ask` is several model
 * calls and a web search — seconds, normally. The *first* question after the
 * backend starts also waits on `import chain`: faiss off disk, the ollama
 * embedder, langchain's module tree, about 80 seconds of it. model/api.py
 * warms that on a thread at startup, but a question that arrives mid-warm
 * still waits for the same import to finish.
 *
 * So the timeout has to be long enough that a *working* backend never trips
 * it, because a timeout here is indistinguishable from a broken server to the
 * person waiting. Three minutes is past the worst honest case; the composer
 * explains the wait rather than leaving it unaccounted for.
 */
export const CHAT_TIMEOUT_MS = 180_000;

export const ENDPOINTS = {
  health: '/health',
  register: '/auth/register',
  login: '/auth/login',
  me: '/auth/me',
  password: '/auth/password',
  chat: '/chat',
  conversations: '/conversations',
  /* Path segment, so an id is encoded rather than concatenated — a mongodb
     _id is url-safe, but the route that reads it should not be the thing
     assuming so. */
  conversation: (id) => `/conversations/${encodeURIComponent(id)}`,
  search: '/search',
};
