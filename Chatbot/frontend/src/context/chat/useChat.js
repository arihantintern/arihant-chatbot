import { useContext } from 'react';

import { ChatContext } from './ChatContext';

/**
 * Read the conversation.
 *
 * @returns {import('./ChatContext').ChatContextValue}
 * @throws  if called outside <ChatProvider>. Loud at the call site beats a
 *          silent `undefined.turns` three renders later.
 */
export function useChat() {
  const context = useContext(ChatContext);

  if (context === null) {
    throw new Error('useChat() must be used inside a <ChatProvider>.');
  }

  return context;
}
