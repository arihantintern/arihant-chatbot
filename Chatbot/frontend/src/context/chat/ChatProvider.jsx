import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';

import { chatApi } from '@/api';
import { useAuth } from '@/context/auth';

import { ChatContext } from './ChatContext';
import {
  CHAT_STATUS,
  HISTORY_LIMIT,
  HISTORY_STATUS,
  TURN_STATUS,
} from './chat.constants';
import { forgetCitations, recallCitations, rememberCitations } from './citations';

/**
 * Owns the conversation: what has been asked, what came back, and what else
 * this account has asked before.
 *
 * WHY A REDUCER. Every interesting moment here changes several fields at once
 * — sending appends a turn *and* flips the status; an answer fills the turn,
 * names the conversation *and* clears the error; opening a past conversation
 * replaces the turn list, the id and the loading flag together. Written as
 * separate `useState` calls those would be three renders and three chances to
 * paint a half-updated screen.
 *
 * WHY REFS FOR THE CONVERSATION ID AND THE REQUEST. Both are read by async
 * code that started before the current render, where a value captured from
 * state is a value from whenever the closure was made. The id has to be the
 * one that is true *now* (the second question of a conversation must carry the
 * id the first question created), and the abort controller has to be the one
 * that is in flight *now*.
 *
 * ONE REQUEST AT A TIME, on purpose. `/chat` is a single blocking POST that
 * can run for a minute; two in flight on one conversation would have their
 * turns interleaved by the backend in whichever order the models happened to
 * finish. So the composer is disabled while one is out, with a visible way to
 * stop it rather than a silently swallowed Enter.
 */

/* Turn keys for locally-created turns. A counter rather than a random id: it
   is stable across a re-render, needs no crypto, and reads clearly in the
   React devtools. Turns loaded from the backend key off `conversationId:seq`,
   which is their real identity. */
let counter = 0;
const nextKey = () => `local-${(counter += 1)}`;

const INITIAL = {
  conversationId: null,
  turns: [],
  status: CHAT_STATUS.IDLE,
  conversations: [],
  historyStatus: HISTORY_STATUS.IDLE,
  historyError: null,
  isOpening: false,
  notice: null,
};

function reducer(state, action) {
  switch (action.type) {
    case 'send':
      return {
        ...state,
        status: CHAT_STATUS.SENDING,
        notice: null,
        turns: [
          ...state.turns,
          {
            key: action.key,
            seq: null,
            question: action.question,
            standalone: null,
            answer: null,
            source: null,
            pdfs: [],
            urls: [],
            tookMs: null,
            at: action.at,
            status: TURN_STATUS.PENDING,
            error: null,
            retryable: false,
          },
        ],
      };

    /* A failed turn going back out. The turn keeps its key and its place in
       the list — a retry is the same question, not a new one further down. */
    case 'retry':
      return {
        ...state,
        status: CHAT_STATUS.SENDING,
        notice: null,
        turns: state.turns.map((turn) =>
          turn.key === action.key
            ? { ...turn, status: TURN_STATUS.PENDING, error: null, retryable: false }
            : turn,
        ),
      };

    case 'answered':
      return {
        ...state,
        status: CHAT_STATUS.IDLE,
        conversationId: action.answer.conversationId,
        turns: state.turns.map((turn) =>
          turn.key === action.key
            ? {
                ...turn,
                seq: action.answer.seq,
                standalone: action.answer.standalone,
                answer: action.answer.answer,
                source: action.answer.source,
                pdfs: action.answer.pdfs,
                urls: action.answer.urls,
                tookMs: action.answer.tookMs,
                status: TURN_STATUS.ANSWERED,
                error: null,
                retryable: false,
              }
            : turn,
        ),
      };

    case 'failed':
      return {
        ...state,
        status: CHAT_STATUS.IDLE,
        conversationId: action.resetConversation ? null : state.conversationId,
        notice: action.notice ?? state.notice,
        turns: state.turns.map((turn) =>
          turn.key === action.key
            ? {
                ...turn,
                status: TURN_STATUS.FAILED,
                error: action.error,
                retryable: action.retryable !== false,
              }
            : turn,
        ),
      };

    case 'reset':
      return {
        ...INITIAL,
        /* The history list survives a new conversation — it is about the
           account, not about what is on screen. */
        conversations: state.conversations,
        historyStatus: state.historyStatus,
        historyError: state.historyError,
        notice: action.notice ?? null,
      };

    case 'opening':
      return { ...state, isOpening: true, notice: null };

    case 'opened':
      return {
        ...state,
        isOpening: false,
        status: CHAT_STATUS.IDLE,
        conversationId: action.conversationId,
        turns: action.turns,
      };

    case 'openFailed':
      return { ...state, isOpening: false, notice: action.notice };

    case 'historyLoading':
      return { ...state, historyStatus: HISTORY_STATUS.LOADING, historyError: null };

    case 'historyReady':
      return {
        ...state,
        historyStatus: HISTORY_STATUS.READY,
        historyError: null,
        conversations: action.conversations,
      };

    case 'historyError':
      return {
        ...state,
        historyStatus: HISTORY_STATUS.ERROR,
        historyError: action.error,
      };

    case 'notice':
      return { ...state, notice: action.notice };

    default:
      return state;
  }
}

export function ChatProvider({ children }) {
  const { user } = useAuth();
  const [state, dispatch] = useReducer(reducer, INITIAL);

  /* The id the *next* request must carry. Kept alongside state rather than
     read out of it, because a send fired from an event handler needs the value
     as of now, not as of the render that created the handler. */
  const conversationIdRef = useRef(null);
  const askRef = useRef(null); // the in-flight /chat, or null
  const historyRef = useRef(null); // the in-flight /conversations
  const transcriptRef = useRef(null); // the in-flight /conversations/{id}

  /* ------------------------------------------------------------- history */

  const loadHistory = useCallback(async () => {
    historyRef.current?.abort();

    const controller = new AbortController();
    historyRef.current = controller;

    dispatch({ type: 'historyLoading' });

    try {
      const conversations = await chatApi.listConversations({
        limit: HISTORY_LIMIT,
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        dispatch({ type: 'historyReady', conversations });
      }
    } catch (error) {
      if (controller.signal.aborted || error.name === 'AbortError') return;
      dispatch({ type: 'historyError', error: error.message });
    } finally {
      if (historyRef.current === controller) historyRef.current = null;
    }
  }, []);

  /* ---------------------------------------------------------------- asking */

  /**
   * One `/chat` round trip, for a turn that is already on screen.
   *
   * `key` identifies which turn the answer belongs to, so a retry lands back
   * in the turn it came from and an answer cannot be attached to the wrong
   * question if the list changed underneath it.
   */
  const run = useCallback(
    async (key, question) => {
      const controller = new AbortController();
      askRef.current = controller;

      /* Captured before the request: whether this question is the one that
         creates the conversation. That decides whether the history list gains
         a row and needs re-reading. */
      const isFirst = !conversationIdRef.current;

      try {
        const answer = await chatApi.ask({
          question,
          conversationId: conversationIdRef.current,
          signal: controller.signal,
        });

        if (controller.signal.aborted) return;

        conversationIdRef.current = answer.conversationId;
        rememberCitations(answer.conversationId, answer.seq, answer);
        dispatch({ type: 'answered', key, answer });

        /* Only on the first answer. The title is `question[:120]` fixed at
           creation (model/history.py), so a later turn changes nothing in the
           list except `last_at` — not worth a request per question. */
        if (isFirst) loadHistory();
      } catch (error) {
        /* A deliberate cancellation. `stop()` has already said what happened;
           dressing an intentional abort up as a failure would be a lie. */
        if (controller.signal.aborted || error.name === 'AbortError') return;

        /* 401/403 are already handled: the api client's auth bridge ends the
           session, this provider unmounts with the gate, and a message about
           a failed question would flash on the way out. */
        if (error.status === 401 || error.status === 403) return;

        dispatch({ type: 'failed', key, ...describe(error) });

        /* A 404 means the id we were sending is not ours or no longer exists.
           Whatever the list says about it is wrong too. */
        if (error.status === 404) {
          forgetCitations(conversationIdRef.current);
          conversationIdRef.current = null;
          loadHistory();
        }
      } finally {
        if (askRef.current === controller) askRef.current = null;
      }
    },
    [loadHistory],
  );

  const send = useCallback(
    (raw) => {
      const question = String(raw ?? '').trim();
      /* The ref, not `state.status` — this guard has to hold within a single
         tick, before any render has happened. */
      if (!question || askRef.current) return;

      const key = nextKey();
      dispatch({ type: 'send', key, question, at: new Date() });
      run(key, question);
    },
    [run],
  );

  const retry = useCallback(() => {
    if (askRef.current) return;

    /* The last failed turn, which is the only one that can be retried: an
       earlier failure is behind questions that have since been answered, and
       re-asking it would put its answer at the bottom of the conversation
       under the wrong question. */
    const turn = [...state.turns].reverse().find((item) => item.status === TURN_STATUS.FAILED);
    if (!turn?.retryable) return;

    dispatch({ type: 'retry', key: turn.key });
    run(turn.key, turn.question);
  }, [run, state.turns]);

  /**
   * Stop waiting.
   *
   * Worth being straight about what this does and does not do: it abandons the
   * *response*, not the work. `chain.ask` is running in fastapi's threadpool
   * and there is no way to reach it; it will finish, and model/history.py will
   * save the turn. So the turn is left on screen as stopped rather than
   * deleted, and the history list is re-read — a first question that was
   * stopped created a conversation on the server, and it should appear in the
   * list rather than vanish.
   */
  const stop = useCallback(() => {
    const controller = askRef.current;
    if (!controller) return;

    const pending = state.turns.find((turn) => turn.status === TURN_STATUS.PENDING);
    controller.abort();
    askRef.current = null;

    if (pending) {
      dispatch({
        type: 'failed',
        key: pending.key,
        error: 'You stopped waiting for this one. The assistant may still have finished it — it will be in your history if it did.',
        retryable: true,
      });
    }

    loadHistory();
  }, [loadHistory, state.turns]);

  /* ------------------------------------------------------- moving around */

  const startNew = useCallback(() => {
    askRef.current?.abort();
    askRef.current = null;
    transcriptRef.current?.abort();

    conversationIdRef.current = null;
    dispatch({ type: 'reset' });
  }, []);

  const openConversation = useCallback(
    async (id) => {
      if (!id) return;

      /* Leaving mid-question abandons the response, not the work — same story
         as stop(). The turn list is about to be replaced wholesale, so there
         is nothing on screen left to mark. */
      askRef.current?.abort();
      askRef.current = null;

      transcriptRef.current?.abort();
      const controller = new AbortController();
      transcriptRef.current = controller;

      dispatch({ type: 'opening' });

      try {
        const rows = await chatApi.fetchTranscript(id, { signal: controller.signal });
        if (controller.signal.aborted) return;

        const cached = recallCitations(id);
        conversationIdRef.current = id;

        dispatch({
          type: 'opened',
          conversationId: id,
          turns: rows.map((row) => toTurn(id, row, cached[row.seq])),
        });
      } catch (error) {
        if (controller.signal.aborted || error.name === 'AbortError') return;
        if (error.status === 401 || error.status === 403) return;

        if (error.status === 404) {
          forgetCitations(id);
          loadHistory();
        }

        dispatch({
          type: 'openFailed',
          notice:
            error.status === 404
              ? 'That conversation is no longer available.'
              : error.message,
        });
      } finally {
        if (transcriptRef.current === controller) transcriptRef.current = null;
      }
    },
    [loadHistory],
  );

  const dismissNotice = useCallback(() => dispatch({ type: 'notice', notice: null }), []);

  /* ----------------------------------------------------------- lifecycle */

  /* The history list is the first thing the rail can show, so it is asked for
     on mount rather than when the panel first opens — by the time anyone
     clicks, it is already there. */
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  /**
   * A different account in the same mounted provider.
   *
   * Normally impossible — signing out unmounts this whole subtree with the
   * gate. But AuthProvider adopts a session that *another tab* signed in with,
   * and if that is a different person, the conversation on screen is theirs
   * and this is the one place that can notice.
   */
  const accountRef = useRef(user.id);
  useEffect(() => {
    if (accountRef.current === user.id) return;
    accountRef.current = user.id;

    askRef.current?.abort();
    transcriptRef.current?.abort();
    conversationIdRef.current = null;
    dispatch({ type: 'reset', notice: 'Signed in as a different account — starting fresh.' });
    loadHistory();
  }, [user.id, loadHistory]);

  /* Nothing should outlive the provider still waiting on a response. */
  useEffect(
    () => () => {
      askRef.current?.abort();
      historyRef.current?.abort();
      transcriptRef.current?.abort();
    },
    [],
  );

  const value = useMemo(
    () => ({
      conversationId: state.conversationId,
      turns: state.turns,
      status: state.status,
      isSending: state.status === CHAT_STATUS.SENDING,
      conversations: state.conversations,
      historyStatus: state.historyStatus,
      historyError: state.historyError,
      isOpening: state.isOpening,
      notice: state.notice,
      send,
      retry,
      stop,
      startNew,
      openConversation,
      refreshHistory: loadHistory,
      dismissNotice,
    }),
    [state, send, retry, stop, startNew, openConversation, loadHistory, dismissNotice],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

/**
 * A stored turn, in the shape the live ones use.
 *
 * `pdfs`/`urls` come from the client-side cache and are empty when this turn
 * was answered in a previous session — the transcript route does not carry
 * them (see context/chat/citations.js). Empty is the honest answer there.
 */
function toTurn(conversationId, row, citations) {
  const failed = row.answer === null || row.answer === '';

  return {
    key: `${conversationId}:${row.seq}`,
    seq: row.seq,
    question: row.question,
    /* Not in the transcript route's `Turn` model, so a reopened turn cannot
       say how its question was read. Null, not the question — "we do not
       know" and "it was unchanged" are different facts. */
    standalone: null,
    answer: row.answer,
    source: row.source,
    pdfs: citations?.pdfs ?? [],
    urls: citations?.urls ?? [],
    /* Never stored per turn, so it is only known for a turn answered in this
       session — and showing a made-up duration would be worse than none. */
    tookMs: null,
    at: row.at ?? null,
    status: failed ? TURN_STATUS.FAILED : TURN_STATUS.ANSWERED,
    error: failed ? 'The assistant did not finish this answer.' : null,
    /* A historical failure is not retryable in place: re-asking it would put
       the answer at the bottom of the conversation, under a different
       question. The question can be copied and asked again. */
    retryable: false,
  };
}

/**
 * An ApiError, as something to show on the failed turn.
 *
 * `ApiError.message` is already written for a person — either the backend's own
 * `detail` or a fallback keyed off the status. The three cases below are the
 * ones where this app knows something the api client cannot: what a 404 on
 * `/chat` means for the conversation, what a 502 from the chain means for the
 * question, and that a slow answer is worth waiting for again.
 */
function describe(error) {
  if (error.status === 404) {
    return {
      error:
        'That conversation is no longer available, so this question was not saved to it. Asking again will start a new one.',
      retryable: true,
      resetConversation: true,
      notice: 'The conversation you were in is no longer available.',
    };
  }

  if (error.status === 502) {
    return {
      /* model/api.py sends `the chain failed: KeyError` — true, and useless to
         the person reading it. The type name is in the network panel for
         whoever is debugging. */
      error:
        'The assistant broke while working on that question. Asking it a different way usually gets past it.',
      retryable: true,
    };
  }

  if (error.isNetworkFailure) {
    return { error: error.message, retryable: true };
  }

  return { error: error.message, retryable: true };
}
