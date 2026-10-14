import './Turn.css';

import { useCallback, useRef, useState } from 'react';

import { Icon } from '@/components/ui';
import { TURN_STATUS } from '@/context/chat';

import { sourceMeta, sourceSentence } from '../sources';
import { ActivityTrace } from './ActivityTrace';
import { Citations } from './Citations';
import { Markdown } from './Markdown';

/**
 * One exchange: what was asked, and what came back.
 *
 * THE ORDER ON SCREEN IS AN ARGUMENT. The provenance strip sits *above* the
 * answer, not under it. For a grounded answer that is merely tidy; for the
 * `general` lane — model/chain.py's TIER 4, where no document, page or feed
 * was involved — it is the difference between reading a hedged sentence and
 * reading it having already been told not to trust it. A research tool that
 * puts its caveat in the footer has put it where nobody looks.
 *
 * @param {object} props
 * @param {import('@/context/chat/ChatContext').Turn} props.turn
 * @param {() => void} props.onStop
 * @param {() => void} props.onRetry
 */
export function Turn({ turn, onStop, onRetry }) {
  const citationsRef = useRef(null);
  const [flash, setFlash] = useState(false);

  const meta = sourceMeta(turn.source);
  const hasSources = turn.pdfs.length > 0 || turn.urls.length > 0;

  /* Compared loosely: `fix` normalises case and punctuation as a side effect of
     spellchecking, and flagging "bandhan bank?" versus "Bandhan Bank" as a
     rewrite would cry wolf on almost every turn. Only a real change in words
     is worth showing. */
  const rewritten = turn.standalone && !sameQuestion(turn.standalone, turn.question);

  /* A `[3]` in the prose brings the sources into view and marks them. It
     cannot point at *one* source — the markers count retrieved chunks and the
     list is a deduplicated set of files — so it does the honest version of
     what the reader wanted: shows them what this answer read. */
  const revealSources = useCallback(() => {
    citationsRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    setFlash(true);
    setTimeout(() => setFlash(false), 1500);
  }, []);

  return (
    <article className="turn" data-status={turn.status}>
      {/* --- the question ------------------------------------------------- */}
      <div className="turn__ask">
        <p className="turn__bubble">{turn.question}</p>
        {turn.at ? (
          <time className="turn__time" dateTime={turn.at.toISOString()}>
            {clock(turn.at)}
          </time>
        ) : null}
      </div>

      {/* --- what it was read as -------------------------------------------
          `standalone` is the question the chain actually searched: spellchecked
          by `fix`, and with the conversation folded in by `resolve` when the
          question was a follow-up. It is usually identical to what was typed,
          and then this says nothing.

          When it is *not* identical, it is the single most useful thing on the
          screen. An answer that seems to be about the wrong thing is very often
          a rewrite that went wrong — "and its rating?" resolved against the
          wrong company — and without this the reader has no way to tell that
          from the assistant simply not knowing. */}
      {rewritten ? (
        <p className="turn__reading">
          <Icon name="refresh" size="xs" />
          <span>
            Read as: <em>{turn.standalone}</em>
          </span>
        </p>
      ) : null}

      {/* --- waiting ------------------------------------------------------ */}
      {turn.status === TURN_STATUS.PENDING ? <ActivityTrace onStop={onStop} /> : null}

      {/* --- the answer --------------------------------------------------- */}
      {turn.status === TURN_STATUS.ANSWERED ? (
        <div className="turn__reply">
          {meta.quiet ? null : (
            <header className="turn__source" data-tone={meta.tone}>
              <Icon name={meta.icon} size="sm" className="turn__source-icon" />
              <span className="turn__source-text">
                {sourceSentence(turn.source, turn) || meta.label}
              </span>
              {turn.tookMs ? (
                <span className="turn__took" title="How long the backend took">
                  {duration(turn.tookMs)}
                </span>
              ) : null}
            </header>
          )}

          <Markdown
            text={turn.answer}
            onCitationClick={hasSources ? revealSources : undefined}
          />

          {meta.quiet ? null : (
            <Citations ref={citationsRef} pdfs={turn.pdfs} urls={turn.urls} flash={flash} />
          )}

          <footer className="turn__tools">
            <CopyButton text={turn.answer} />
          </footer>
        </div>
      ) : null}

      {/* --- it did not work --------------------------------------------- */}
      {turn.status === TURN_STATUS.FAILED ? (
        <div className="turn__failure" role="alert">
          <Icon name="alertCircle" size="sm" className="turn__failure-icon" />
          <p className="turn__failure-text">{turn.error}</p>

          {turn.retryable ? (
            <button type="button" className="turn__retry" onClick={onRetry}>
              <Icon name="refresh" size="xs" />
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

/**
 * Copy the answer.
 *
 * The label changes and the width does not — the button is sized for the
 * longer of the two words, so a row of tools does not jump when one of them
 * is pressed.
 */
function CopyButton({ text }) {
  const [done, setDone] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1800);
    } catch {
      /* Clipboard denied, or a non-secure origin. The text is selectable. */
    }
  };

  return (
    <button
      type="button"
      className="turn__tool"
      onClick={copy}
      data-done={done || undefined}
      aria-live="polite"
    >
      <Icon name={done ? 'check' : 'copy'} size="xs" />
      {done ? 'Copied' : 'Copy'}
    </button>
  );
}

/** Same words, ignoring case, punctuation and quote style. */
function sameQuestion(a, b) {
  const flatten = (value) =>
    value
      .toLowerCase()
      .replace(/[\u2018\u2019]/g, "'")
      .replace(/[^a-z0-9']+/g, ' ')
      .trim();

  return flatten(a) === flatten(b);
}

/** "09:14". The date is carried by the day separator above the turn. */
function clock(date) {
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

/** 840 → "0.8s", 62_400 → "1m 2s". Rounded: nobody needs the millisecond. */
function duration(ms) {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;

  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)}m ${total % 60}s`;
}
