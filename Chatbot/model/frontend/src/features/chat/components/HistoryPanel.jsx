import './HistoryPanel.css';

import { useCallback, useEffect, useRef } from 'react';

import { Icon } from '@/components/ui';
import { HISTORY_STATUS, useChat } from '@/context/chat';
import { useClickOutside } from '@/hooks/useClickOutside';

/**
 * Everything this account has asked before.
 *
 * A panel that is summoned rather than parked. The chat's whole layout
 * argument is that a permanent 320px list of things you are *not* reading is
 * the wrong thing to give a third of a research screen to — so this slides
 * over, does its job, and closes.
 *
 * IT IS READ-ONLY, AND IT SAYS SO. There is no `DELETE /conversations/{id}`
 * and no rename on model/api.py; conversations are titled `question[:120]` at
 * creation and never change. So there are no rename affordances and no delete
 * buttons here — a control that cannot work is a worse lie than an absent one.
 * The footer says where the transcripts actually live, so "can I get rid of
 * this?" has an answer rather than a missing button.
 *
 * @param {object} props
 * @param {boolean} props.open
 * @param {() => void} props.onClose
 */
export function HistoryPanel({ open, onClose }) {
  const {
    conversations,
    historyStatus,
    historyError,
    conversationId,
    refreshHistory,
    openConversation,
  } = useChat();

  const panelRef = useRef(null);

  useClickOutside(panelRef, onClose, open);

  /* Focus moves into the panel on open — onto the panel itself rather than the
     first conversation, so Enter from someone who was still deciding does not
     load one. Same reasoning as the account menu. */
  useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);

  const onKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
    }
  };

  const pick = useCallback(
    (id) => {
      openConversation(id);
      onClose();
    },
    [openConversation, onClose],
  );

  const groups = groupByDay(conversations);

  return (
    <>
      {/* The scrim is a click target, not a dimmer with a click handler bolted
          on — so it is a button, and it announces itself as the way out. */}
      <button
        type="button"
        className="history__scrim"
        data-open={open || undefined}
        onClick={onClose}
        tabIndex={-1}
        aria-label="Close history"
      />

      <aside
        ref={panelRef}
        className="history"
        data-open={open || undefined}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        aria-label="Your conversations"
        /* Hidden from the accessibility tree and from Tab while closed —
           `visibility: hidden` in the CSS does the second part, and this makes
           the first explicit rather than incidental. */
        aria-hidden={!open || undefined}
      >
        <header className="history__head">
          <h2 className="history__title">
            <Icon name="clock" size="sm" />
            History
          </h2>

          <button
            type="button"
            className="history__icon-btn"
            onClick={refreshHistory}
            disabled={historyStatus === HISTORY_STATUS.LOADING}
            title="Refresh"
          >
            <Icon
              name="refresh"
              size="sm"
              title="Refresh the list"
              className={historyStatus === HISTORY_STATUS.LOADING ? 'history__spin' : ''}
            />
          </button>

          <button type="button" className="history__icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size="sm" title="Close history" />
          </button>
        </header>

        <div className="history__body">
          {historyStatus === HISTORY_STATUS.LOADING && conversations.length === 0 ? (
            <Skeleton />
          ) : null}

          {historyStatus === HISTORY_STATUS.ERROR && conversations.length === 0 ? (
            <div className="history__state" role="alert">
              <Icon name="alertCircle" size="md" className="history__state-icon" />
              <p className="history__state-title">Could not load your history</p>
              <p className="history__state-text">{historyError}</p>
              <button type="button" className="history__retry" onClick={refreshHistory}>
                <Icon name="refresh" size="xs" />
                Try again
              </button>
            </div>
          ) : null}

          {historyStatus === HISTORY_STATUS.READY && conversations.length === 0 ? (
            <div className="history__state">
              <Icon name="message" size="md" className="history__state-icon" />
              <p className="history__state-title">Nothing here yet</p>
              <p className="history__state-text">
                Ask your first question and it will be saved here — titled by
                what you asked.
              </p>
            </div>
          ) : null}

          {groups.map((group) => (
            <section className="history__group" key={group.label}>
              <h3 className="history__group-label">{group.label}</h3>

              <ul className="history__list">
                {group.items.map((conversation) => (
                  <li key={conversation.id}>
                    <button
                      type="button"
                      className="history__item"
                      data-current={conversation.id === conversationId || undefined}
                      onClick={() => pick(conversation.id)}
                      aria-current={conversation.id === conversationId ? 'true' : undefined}
                    >
                      <span className="history__item-title">{conversation.title}</span>

                      <span className="history__item-meta">
                        <span>
                          {conversation.turns} {conversation.turns === 1 ? 'question' : 'questions'}
                        </span>
                        {conversation.lastAt ? (
                          <>
                            <span aria-hidden="true">·</span>
                            <span>{clock(conversation.lastAt)}</span>
                          </>
                        ) : null}
                        {/* Only when it is *not* this app. A badge on every row
                            saying "api" would explain nothing to anybody. */}
                        {conversation.origin === 'cli' ? (
                          <span className="history__badge" title="Started from the command line">
                            terminal
                          </span>
                        ) : null}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>

        <footer className="history__foot">
          <Icon name="info" size="xs" />
          <p>
            Every question you ask is saved to your account. Removing one is not
            something this app can do — ask whoever runs the backend.
          </p>
        </footer>
      </aside>
    </>
  );
}

/**
 * Today / Yesterday / a date — by `lastAt`, which is when the conversation was
 * last *used* rather than when it was started. That is the order the list
 * arrives in from model/history.py, so grouping on it keeps the groups
 * contiguous and needs no sort.
 */
function groupByDay(conversations) {
  const groups = [];

  for (const conversation of conversations) {
    const label = dayLabel(conversation.lastAt ?? conversation.startedAt);
    const last = groups[groups.length - 1];

    if (last && last.label === label) {
      last.items.push(conversation);
    } else {
      groups.push({ label, items: [conversation] });
    }
  }

  return groups;
}

function dayLabel(date) {
  if (!date) return 'Undated';

  const startOfDay = (value) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate());
  const days = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86_400_000);

  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return 'Earlier this week';

  return date.toLocaleDateString(undefined, {
    month: 'long',
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
  });
}

function clock(date) {
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function Skeleton() {
  return (
    <div className="history__group" role="status" aria-label="Loading your conversations">
      <div className="u-skeleton history__skeleton-label" />
      <div className="history__list">
        {[0, 1, 2, 3].map((index) => (
          <div className="history__skeleton-item" key={index}>
            <div className="u-skeleton history__skeleton-line" />
            <div
              className="u-skeleton history__skeleton-line"
              style={{ inlineSize: '45%', blockSize: '0.5rem' }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
