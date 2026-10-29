import './SearchPalette.css';

import { useCallback, useEffect, useRef, useState } from 'react';

import { chatApi } from '@/api';
import { Icon, Spinner } from '@/components/ui';
import { SEARCH_LIMIT } from '@/context/chat';

import { sourceMeta } from '../sources';
import { Markdown } from './Markdown';

/**
 * Search everything this account has ever asked.
 *
 * TWO PROPERTIES OF `GET /search` SHAPE THIS ENTIRE COMPONENT, and neither is
 * obvious from the outside.
 *
 * 1. It matches WHOLE WORDS. `history.find` runs a mongodb `$text` query, and
 *    a text index matches whole terms rather than substrings — "bandhan" finds
 *    everything, "bandh" finds nothing. That is unusual enough that a person
 *    will conclude the search is broken rather than that they typed half a
 *    word, so the empty state says it outright rather than shrugging.
 *
 * 2. It does not say which conversation a hit belongs to. The response model is
 *    `Turn` — `{seq, ts, question, answer, source}` — so there is no
 *    conversation id, and `seq` on its own is a turn number *within* a
 *    conversation, which identifies nothing.
 *
 *    The document underneath does carry it (`history.find` returns whole
 *    message documents, `session_id` included) — the route narrows it away.
 *    So "jump to this turn in its thread" is one field short of possible, and
 *    guessing which thread would be worse than not offering it.
 *
 * So this does not jump you into a conversation, because it cannot, and it does
 * not pretend to: a result opens *in place*, with its whole answer and its
 * source. Which turns out to be the better interaction anyway — you searched
 * for an answer, and here is the answer, without losing the conversation you
 * were already in. "Ask again" is there for when what you actually wanted was
 * to put the question back to a live assistant.
 *
 * MOUNTED ONLY WHILE OPEN, which is why there is no "reset when it opens"
 * anywhere below: every piece of state here starts empty because the component
 * starts. Opening the palette *is* a fresh start, and expressing that as a
 * mount rather than as an effect that clears six fields removes the whole class
 * of bug where one of them is forgotten.
 *
 * @param {object} props
 * @param {() => void} props.onClose
 * @param {(question: string) => void} props.onAskAgain
 */
export function SearchPalette({ onClose, onAskAgain }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [status, setStatus] = useState('idle'); // idle | searching | ready | error
  const [error, setError] = useState(null);
  const [active, setActive] = useState(0);
  const [expanded, setExpanded] = useState(null);

  const inputRef = useRef(null);
  const listRef = useRef(null);
  const timerRef = useRef(null);
  const requestRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  /* --- the search --------------------------------------------------------
     Driven by the keystroke, not by an effect watching the query. Typing is an
     event, and searching is what that event does — routing it through state
     and back out through an effect would add a render in the middle and make
     the debounce harder to reason about, not easier. */
  const search = useCallback((raw) => {
    const trimmed = raw.trim();

    clearTimeout(timerRef.current);
    requestRef.current?.abort();

    if (!trimmed) {
      setResults([]);
      setStatus('idle');
      return;
    }

    setStatus('searching');

    /* Debounced, and every superseded request aborted: typing "bandhan bank"
       is one search rather than eleven, and a slow early response can never
       land on top of a fast later one. */
    timerRef.current = setTimeout(() => {
      const controller = new AbortController();
      requestRef.current = controller;

      chatApi
        .searchTurns(trimmed, { limit: SEARCH_LIMIT, signal: controller.signal })
        .then((turns) => {
          if (controller.signal.aborted) return;
          setResults(turns);
          setStatus('ready');
          setActive(0);
          setExpanded(null);
        })
        .catch((failure) => {
          if (controller.signal.aborted || failure.name === 'AbortError') return;
          setError(failure.message);
          setStatus('error');
        });
    }, 300);
  }, []);

  const onQueryChange = (value) => {
    setQuery(value);
    search(value);
  };

  useEffect(
    () => () => {
      clearTimeout(timerRef.current);
      requestRef.current?.abort();
    },
    [],
  );

  /* --- keyboard ---------------------------------------------------------- */
  const askAgain = useCallback(
    (question) => {
      onClose();
      onAskAgain(question);
    },
    [onClose, onAskAgain],
  );

  const onKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      /* Escape closes the open result first, and only then the palette —
         one Escape, one thing undone. */
      if (expanded !== null) setExpanded(null);
      else onClose();
      return;
    }

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActive((current) => clamp(current + step, 0, results.length - 1));
      return;
    }

    if (event.key === 'Enter' && results[active]) {
      event.preventDefault();
      setExpanded((current) => (current === active ? null : active));
    }
  };

  /* Keep the highlighted row in view when arrowing past the fold. */
  useEffect(() => {
    listRef.current
      ?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);

  return (
    <div className="palette" role="presentation">
      <button
        type="button"
        className="palette__scrim"
        onClick={onClose}
        tabIndex={-1}
        aria-label="Close search"
      />

      <div
        className="palette__panel a-scale-in"
        role="dialog"
        aria-modal="true"
        aria-label="Search your questions"
        onKeyDown={onKeyDown}
      >
        <div className="palette__field">
          <Icon name="search" size="md" className="palette__field-icon" />

          <input
            ref={inputRef}
            className="palette__input"
            type="text"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="Search everything you have asked…"
            autoComplete="off"
            spellCheck={false}
            aria-controls="palette-results"
          />

          {status === 'searching' ? <Spinner size="sm" /> : null}

          <kbd className="palette__key">esc</kbd>
        </div>

        <div className="palette__results" id="palette-results" ref={listRef}>
          {status === 'idle' ? (
            <p className="palette__tip">
              <Icon name="info" size="xs" />
              Whole words only — the backend matches on word boundaries, so
              “bandhan” finds your questions about Bandhan Bank and “bandh”
              finds nothing.
            </p>
          ) : null}

          {status === 'error' ? (
            <p className="palette__empty" role="alert">
              {error}
            </p>
          ) : null}

          {status === 'ready' && results.length === 0 ? (
            <p className="palette__empty">
              Nothing matched “{query.trim()}”. Try a whole word — a partial one
              never matches.
            </p>
          ) : null}

          {results.map((result, index) => (
            <Result
              key={`${result.seq}:${result.at?.getTime() ?? index}`}
              result={result}
              terms={terms}
              active={index === active}
              open={expanded === index}
              onHover={() => setActive(index)}
              onToggle={() => setExpanded((current) => (current === index ? null : index))}
              onAskAgain={askAgain}
            />
          ))}
        </div>

        {results.length > 0 ? (
          <footer className="palette__foot">
            <span>
              <kbd className="palette__key">↑</kbd>
              <kbd className="palette__key">↓</kbd> move
            </span>
            <span>
              <kbd className="palette__key">↵</kbd> open
            </span>
            <span className="u-spacer" />
            <span>
              {results.length}
              {results.length === SEARCH_LIMIT ? '+' : ''} found
            </span>
          </footer>
        ) : null}
      </div>
    </div>
  );
}

/**
 * One hit: the question, a window of the answer, and its source.
 *
 * Opening it reveals the whole answer, rendered the same way it was rendered
 * in the conversation — same component, same tables, same citation marks
 * (inert here, because the sources of an old turn are not in this response).
 */
function Result({ result, terms, active, open, onHover, onToggle, onAskAgain }) {
  const meta = sourceMeta(result.source);

  return (
    <div className="palette__result" data-active={active} data-open={open || undefined}>
      <button
        type="button"
        className="palette__result-row"
        onClick={onToggle}
        onMouseEnter={onHover}
        aria-expanded={open}
      >
        <span className="palette__result-head">
          <span className="palette__result-question">
            <Highlight text={result.question} terms={terms} />
          </span>
          {result.at ? (
            <time className="palette__result-when" dateTime={result.at.toISOString()}>
              {when(result.at)}
            </time>
          ) : null}
        </span>

        {/* Collapsed: a window around the match. Expanded: the full answer
            below, so this line would just be a duplicate of its first words. */}
        {!open && result.answer ? (
          <span className="palette__result-snippet">
            <Highlight text={snippet(result.answer, terms)} terms={terms} />
          </span>
        ) : null}

        <span className="palette__result-foot">
          {meta.quiet ? null : (
            <span className="palette__result-source" data-tone={meta.tone}>
              <Icon name={meta.icon} size="xs" />
              {meta.label}
            </span>
          )}
          <Icon
            name="chevronDown"
            size="xs"
            className={`palette__result-chevron ${open ? 'is-open' : ''}`.trim()}
          />
        </span>
      </button>

      {open ? (
        <div className="palette__result-body">
          {result.answer ? (
            <Markdown text={result.answer} />
          ) : (
            <p className="palette__result-none">
              This question has no saved answer — the assistant failed on it.
            </p>
          )}

          <div className="palette__result-actions">
            <button
              type="button"
              className="palette__ask"
              onClick={() => onAskAgain(result.question)}
            >
              <Icon name="refresh" size="xs" />
              Ask this again
            </button>

            {/* Deliberately no "open the conversation": /search does not say
                which conversation a turn came from, so there is nothing to
                open. Better an absent button than one that guesses. */}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The matched words, marked.
 *
 * Splitting the string on the terms and wrapping the pieces in `<mark>` — not
 * replacing into html. Same rule as the markdown renderer, for the same
 * reason: this text came out of a model, and nothing here is ever parsed as
 * markup.
 */
function Highlight({ text, terms }) {
  if (terms.length === 0) return text;

  /* Escaped, or a search for "c++" is a broken regex rather than a search. */
  const pattern = new RegExp(`(${terms.map(escapeRegex).join('|')})`, 'gi');

  return text.split(pattern).map((part, index) =>
    terms.includes(part.toLowerCase()) ? (
      <mark className="palette__mark" key={index}>
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * A window of the answer around the first match, not its opening line.
 *
 * The match is why this row is in the list, and an answer's first sentence
 * often does not contain it — showing the beginning would leave the reader
 * wondering what matched.
 */
function snippet(answer, terms, width = 150) {
  const flat = answer.replace(/\s+/g, ' ').trim();
  if (flat.length <= width) return flat;

  const lower = flat.toLowerCase();
  const at = terms.reduce((found, term) => {
    const index = lower.indexOf(term);
    return index !== -1 && (found === -1 || index < found) ? index : found;
  }, -1);

  if (at === -1) return `${flat.slice(0, width)}…`;

  const from = Math.max(0, at - 40);
  return `${from > 0 ? '…' : ''}${flat.slice(from, from + width)}…`;
}

function when(date) {
  const days = Math.round((Date.now() - date.getTime()) / 86_400_000);

  if (days < 1) return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  if (days === 1) return 'yesterday';

  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(value, high));
}
