import { createContext } from 'react';

/**
 * The chat context object.
 *
 * Split from the provider for the same reason AuthContext is: Fast Refresh can
 * hot-reload a module exporting components *or* values, not both, and a save
 * in ChatProvider.jsx should not throw away the conversation on screen.
 *
 * @typedef  {object} Turn
 * @property {string} key            stable across the pending → answered swap
 * @property {number|null} seq       the backend's turn number; null until answered
 * @property {string} question
 * @property {string|null} standalone
 *   The question as the chain actually searched it — spellchecked, and with a
 *   follow-up's context folded in. Null for a turn read back from the
 *   transcript route, which does not carry it.
 * @property {string|null} answer
 * @property {string|null} source    which lane answered — see features/chat/sources.js
 * @property {string[]} pdfs
 * @property {string[]} urls
 * @property {number|null} tookMs
 * @property {Date} at
 * @property {'pending'|'answered'|'failed'} status
 * @property {string|null} error     what to show on a failed turn
 * @property {boolean} retryable
 *
 * @typedef  {object} ChatContextValue
 * @property {string|null} conversationId
 * @property {Turn[]} turns
 * @property {'idle'|'sending'} status
 * @property {boolean} isSending
 * @property {import('@/api/chat.api').Conversation[]} conversations
 * @property {'idle'|'loading'|'ready'|'error'} historyStatus
 * @property {string|null} historyError
 * @property {boolean} isOpening     a past conversation is being fetched
 * @property {string|null} notice    something happened that needs explaining
 * @property {(question: string) => void} send
 * @property {() => void} retry
 * @property {() => void} stop
 * @property {() => void} startNew
 * @property {(id: string) => void} openConversation
 * @property {() => void} refreshHistory
 * @property {() => void} dismissNotice
 */

/** @type {import('react').Context<ChatContextValue | null>} */
export const ChatContext = createContext(null);
