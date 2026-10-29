/** Whether a request is out. Only one ever is — see ChatProvider. */
export const CHAT_STATUS = {
  IDLE: 'idle',
  SENDING: 'sending',
};

/** A turn's own state, which is not the same thing as the conversation's. */
export const TURN_STATUS = {
  /** Asked; the answer has not come back yet. */
  PENDING: 'pending',
  ANSWERED: 'answered',
  /** The request failed, or the backend saved the turn with no answer. */
  FAILED: 'failed',
};

/** Loading state for the history list and for opening one conversation. */
export const HISTORY_STATUS = {
  IDLE: 'idle',
  LOADING: 'loading',
  READY: 'ready',
  ERROR: 'error',
};

/**
 * How many conversations the history panel asks for.
 *
 * model/api.py caps `/conversations` at 100 and there is no pagination, so
 * this is the whole list as far as the app is concerned. 40 is past what
 * anyone scrolls in a panel and well under the cap.
 */
export const HISTORY_LIMIT = 40;

/** `/search` results. The backend caps at 100; a palette showing 25 is plenty. */
export const SEARCH_LIMIT = 25;

/**
 * The backend's own limit, mirrored so the composer can enforce it before the
 * request rather than after a 422: model/api.py declares
 * `question: str = Field(min_length=1, max_length=2000)`.
 */
export const QUESTION_MAX_LENGTH = 2000;

/** sessionStorage key prefixes. Namespaced, because we share the origin. */
export const CITATION_KEY_PREFIX = 'arihant.citations';
export const DRAFT_KEY_PREFIX = 'arihant.draft';
