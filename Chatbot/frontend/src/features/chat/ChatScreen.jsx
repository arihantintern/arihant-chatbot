import './ChatScreen.css';

import { useCallback, useRef, useState } from 'react';

import { Alert } from '@/components/ui';
import { useChat } from '@/context/chat';

import { ChatRail } from './components/ChatRail';
import { Composer } from './components/Composer';
import { ConversationView } from './components/ConversationView';
import { HistoryPanel } from './components/HistoryPanel';
import { SearchPalette } from './components/SearchPalette';
import { useChatShortcuts } from './hooks/useChatShortcuts';
import { useDraft } from './hooks/useDraft';

/**
 * The product: a rail, a conversation, and a place to type.
 *
 * WHAT THIS COMPONENT OWNS, and it is deliberately only two things: which
 * overlay is open, and the text in the composer. Everything about the
 * conversation itself — the turns, the request in flight, the history list —
 * lives in `@/context/chat`, so none of it has to be handed down through here
 * and none of it is lost when this component re-renders.
 *
 * The draft is here rather than inside the composer because three other things
 * write to it: a starter question on the empty state, "ask this again" from the
 * search palette, and the draft store swapping when the conversation changes.
 * A value with several authors belongs above all of them.
 */
export function ChatScreen() {
  const { conversationId, send, startNew, notice, dismissNotice } = useChat();

  const [draft, setDraft, clearDraft] = useDraft(conversationId);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  const composerRef = useRef(null);
  const focusComposer = useCallback(() => composerRef.current?.focus(), []);

  /* Stable identities, because these go into the shortcut hook's effect —
     new function objects on every render would tear the listener down and
     rebuild it on every keystroke. */
  const openSearch = useCallback(() => setSearchOpen(true), []);

  const newConversation = useCallback(() => {
    startNew();
    setHistoryOpen(false);
    focusComposer();
  }, [startNew, focusComposer]);

  useChatShortcuts({
    onSearch: openSearch,
    onNew: newConversation,
    onFocusComposer: focusComposer,
  });

  /* Fill the box and put the cursor in it, rather than sending straight away.
     A suggested question is a starting point — somebody who wants to change
     "Bandhan Bank" to "HDFC Bank" before asking should be able to, and a click
     that fires a sixty-second request they did not mean is expensive. */
  const prefill = useCallback(
    (question) => {
      setDraft(question);
      focusComposer();
    },
    [setDraft, focusComposer],
  );

  const submit = useCallback(() => {
    send(draft);
    /* Cleared optimistically: the provider has already put the question on
       screen as a turn, and leaving it in the box as well would read as
       "that did not go". A failure restores nothing here — the turn keeps the
       question and offers a retry, which is where it belongs. */
    clearDraft();
  }, [send, draft, clearDraft]);

  return (
    <div className="chat">
      <ChatRail
        historyOpen={historyOpen}
        onToggleHistory={() => setHistoryOpen((open) => !open)}
        onSearch={openSearch}
      />

      <div className="chat__main">
        <HistoryPanel open={historyOpen} onClose={() => setHistoryOpen(false)} />

        {notice ? (
          <div className="chat__notice">
            <Alert tone="warning" onDismiss={dismissNotice} compact>
              {notice}
            </Alert>
          </div>
        ) : null}

        <ConversationView onPickStarter={prefill} />

        {/* Outside the scroll region, so it stays put without `position:
            fixed` — which on mobile browsers means fighting a viewport that
            changes height when the keyboard opens. */}
        <div className="chat__composer">
          <Composer ref={composerRef} value={draft} onChange={setDraft} onSubmit={submit} />
        </div>
      </div>

      {/* Mounted only while open, so opening it is genuinely a fresh start
          rather than an effect that has to remember to clear six fields. */}
      {searchOpen ? (
        <SearchPalette onClose={() => setSearchOpen(false)} onAskAgain={prefill} />
      ) : null}
    </div>
  );
}
