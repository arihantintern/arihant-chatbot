import './ChatRail.css';

import { Icon, Tooltip } from '@/components/ui';
import { useChat } from '@/context/chat';

/**
 * The rail: new conversation, history, search.
 *
 * WHY A RAIL AND NOT A SIDEBAR. Every chat product gives a third of the screen
 * to a permanent list of the conversations you are *not* reading. For a
 * research tool whose answers contain tables, that is a third of the width
 * that a table could have had. So the rail keeps the three actions permanently
 * visible at 76px, and the list itself is summoned over the column and
 * dismissed — present when wanted, absent when not.
 *
 * Icon-only, which puts two obligations on every button here: an accessible
 * name it carries itself (`<Icon title>`), and a tooltip for the sighted
 * person who has not learned the glyphs yet. The tooltip is the *reminder*;
 * the title is the label.
 *
 * @param {object} props
 * @param {boolean} props.historyOpen
 * @param {() => void} props.onToggleHistory
 * @param {() => void} props.onSearch
 */
export function ChatRail({ historyOpen, onToggleHistory, onSearch }) {
  const { startNew, turns, isSending } = useChat();

  /* Nothing to start when the conversation is already empty — and an enabled
     button that visibly does nothing teaches people to distrust the others. */
  const canStartNew = turns.length > 0 && !isSending;

  return (
    <nav className="rail" aria-label="Conversation">
      <Tooltip label="New conversation" shortcut="⌘⇧O" side="end">
        <button
          type="button"
          className="rail__btn rail__btn--primary"
          onClick={startNew}
          disabled={!canStartNew}
        >
          <Icon name="plus" size="lg" title="Start a new conversation" />
        </button>
      </Tooltip>

      <span className="rail__rule" role="presentation" />

      <Tooltip label="History" side="end">
        <button
          type="button"
          className="rail__btn"
          onClick={onToggleHistory}
          aria-expanded={historyOpen}
          data-active={historyOpen || undefined}
        >
          <Icon name="clock" size="lg" title="Your past conversations" />
        </button>
      </Tooltip>

      <Tooltip label="Search your questions" shortcut="⌘K" side="end">
        <button type="button" className="rail__btn" onClick={onSearch}>
          <Icon name="search" size="lg" title="Search everything you have asked" />
        </button>
      </Tooltip>
    </nav>
  );
}
