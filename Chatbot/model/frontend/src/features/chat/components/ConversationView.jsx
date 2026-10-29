import './ConversationView.css';

import { Icon } from '@/components/ui';
import { useChat } from '@/context/chat';

import { useAutoScroll } from '../hooks/useAutoScroll';
import { DaySeparator } from './DaySeparator';
import { EmptyState } from './EmptyState';
import { Turn } from './Turn';

/**
 * The scrolling body of the chat: every turn, in order.
 *
 * It owns the scroll container — which is why the pinning hook lives here and
 * not in the screen above. Two things want to move this element and they must
 * not fight: following a new answer, which happens only while the view is
 * already at the bottom, and the person's own scrolling, which always wins.
 *
 * @param {object} props
 * @param {(question: string) => void} props.onPickStarter
 */
export function ConversationView({ onPickStarter }) {
  const { turns, isOpening, stop, retry } = useChat();
  const { viewportRef, contentRef, pinned, scrollToEnd } = useAutoScroll();

  if (isOpening) {
    return (
      <div className="convo" ref={viewportRef}>
        <div className="convo__inner" ref={contentRef}>
          <Skeleton />
        </div>
      </div>
    );
  }

  if (turns.length === 0) {
    return (
      <div className="convo" ref={viewportRef}>
        <div className="convo__inner" ref={contentRef}>
          <EmptyState onPick={onPickStarter} />
        </div>
      </div>
    );
  }

  return (
    <div className="convo" ref={viewportRef}>
      <div className="convo__inner" ref={contentRef}>
        {turns.map((turn, index) => (
          <div className="convo__slot" key={turn.key}>
            {/* A separator only where the date actually changes, which for a
                conversation started and finished in one sitting means none at
                all. */}
            {showDayFor(turns, index) ? <DaySeparator date={turn.at} /> : null}

            <Turn turn={turn} onStop={stop} onRetry={retry} />
          </div>
        ))}
      </div>

      {/* The way back down, offered only when it is needed. */}
      <button
        type="button"
        className="convo__to-end"
        data-visible={!pinned || undefined}
        onClick={() => scrollToEnd()}
        tabIndex={pinned ? -1 : 0}
        aria-hidden={pinned || undefined}
      >
        <Icon name="arrowDown" size="sm" />
        Latest
      </button>
    </div>
  );
}

/**
 * Does this turn start a new day?
 *
 * True for the first turn that has a date at all, and then only when the date
 * differs from the previous dated turn. A turn with no `ts` — possible for a
 * row written before model/history.py stamped them — is skipped rather than
 * treated as a new day, which would put a separator in the middle of an
 * afternoon.
 */
function showDayFor(turns, index) {
  const at = turns[index].at;
  if (!at) return false;

  for (let before = index - 1; before >= 0; before -= 1) {
    const previous = turns[before].at;
    if (previous) return !sameDay(previous, at);
  }

  return true;
}

function sameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/**
 * While a past conversation loads.
 *
 * Shaped like two turns — a short question, a tall answer — rather than a
 * spinner, because it is telling you what is about to be there. The heights
 * are close enough to real that the content arriving does not shift the page.
 */
function Skeleton() {
  return (
    <div className="convo__skeleton" role="status" aria-label="Loading the conversation">
      {[0, 1].map((index) => (
        <div className="convo__skeleton-turn" key={index}>
          <div className="u-skeleton convo__skeleton-ask" />
          <div className="convo__skeleton-reply">
            <div className="u-skeleton convo__skeleton-line" style={{ inlineSize: '38%' }} />
            <div className="u-skeleton convo__skeleton-line" />
            <div className="u-skeleton convo__skeleton-line" />
            <div className="u-skeleton convo__skeleton-line" style={{ inlineSize: '72%' }} />
          </div>
        </div>
      ))}
    </div>
  );
}
