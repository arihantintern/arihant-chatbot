/**
 * Public surface of the chat module.
 *
 * Import from '@/context/chat'. The citation cache and the reducer are
 * internals — how a conversation is held is free to change as long as
 * `useChat()` keeps answering the same questions.
 */
export { ChatProvider } from './ChatProvider';
export { useChat } from './useChat';
export {
  CHAT_STATUS,
  HISTORY_STATUS,
  QUESTION_MAX_LENGTH,
  SEARCH_LIMIT,
  TURN_STATUS,
} from './chat.constants';
