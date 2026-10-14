import './Composer.css';

import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';

import { Icon } from '@/components/ui';
import { QUESTION_MAX_LENGTH, useChat } from '@/context/chat';

/**
 * Where a question is written.
 *
 * THE HEIGHT. A textarea cannot size itself to its content in CSS, so the
 * height is written from the scroll height on every change, bounded by
 * `--height-composer-min` and `--height-composer-max`. Above the maximum it
 * scrolls: a fifteen-line question should not push the conversation off the
 * screen it is about.
 *
 * THE LIMIT. 2000 characters, and it is the *backend's* limit — model/api.py
 * declares `Field(min_length=1, max_length=2000)`. Mirroring it here turns a
 * 422 nobody can act on into a counter that appears while there is still time
 * to shorten the question. The counter stays hidden until it is nearly
 * relevant, because a character count on an empty box is an instruction to
 * write less.
 *
 * WHILE A QUESTION IS OUT. The box is disabled and says why. `/chat` is one
 * blocking request and two of them on one conversation would have their turns
 * interleaved server-side; the Stop button in the activity trace is the way
 * out, and it is the only one, so there is no ambiguity about what Enter does.
 *
 * @param {object} props
 * @param {string} props.value
 * @param {(value: string) => void} props.onChange
 * @param {() => void} props.onSubmit
 */
export const Composer = forwardRef(function Composer({ value, onChange, onSubmit }, ref) {
  const { isSending } = useChat();
  const textareaRef = useRef(null);

  /* The screen above focuses this from a keyboard shortcut and after a starter
     is picked, and it has no business knowing the internal element. */
  useImperativeHandle(ref, () => ({
    focus: () => textareaRef.current?.focus(),
  }));

  /* Re-measured on every change, and also when `isSending` flips: the box is
     re-enabled at a different height than it was disabled at if the draft was
     restored underneath. */
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = 'auto';
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, [value, isSending]);

  const trimmed = value.trim();
  const canSend = trimmed.length > 0 && !isSending && value.length <= QUESTION_MAX_LENGTH;

  const remaining = QUESTION_MAX_LENGTH - value.length;
  /* Two hundred characters of warning is enough to finish a sentence and cut
     something; a counter that appears at 1999 is an alarm, not a help. */
  const showCount = remaining <= 200;

  const submit = () => {
    if (!canSend) return;
    onSubmit();
  };

  const onKeyDown = (event) => {
    /* Enter sends; Shift+Enter is a newline. The IME check matters for anyone
       typing an Indic script through a composition editor — Enter while a
       candidate is open is "accept that word", not "send this question". */
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="composer__field" data-disabled={isSending || undefined}>
        <label className="u-sr-only" htmlFor="composer-input">
          Ask the research assistant a question
        </label>

        <textarea
          id="composer-input"
          ref={textareaRef}
          className="composer__input"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={
            isSending ? 'Waiting for the answer…' : 'Ask about a company, a rating or a number…'
          }
          disabled={isSending}
          rows={1}
          /* The browser's own spellcheck is right for prose and wrong for scrip
             codes; autocorrect turning "CMOTS" into something else mid-question
             is worse than a red underline. */
          autoCorrect="off"
          autoCapitalize="sentences"
          spellCheck
          aria-describedby="composer-hint"
          /* Deliberately not capped in the DOM: a hard maxLength silently
             truncates a pasted question, and losing the end of somebody's
             paragraph without saying so is worse than telling them it is long. */
        />

        <div className="composer__actions">
          {showCount ? (
            <span
              className="composer__count"
              data-over={remaining < 0 || undefined}
              aria-live="polite"
            >
              {remaining < 0
                ? `${Math.abs(remaining)} over`
                : `${remaining} left`}
            </span>
          ) : null}

          <button
            type="submit"
            className="composer__send"
            disabled={!canSend}
            aria-label="Send question"
          >
            <Icon name="send" size="sm" />
          </button>
        </div>
      </div>

      <p className="composer__hint" id="composer-hint">
        {isSending ? (
          <span className="composer__waiting">
            <Icon name="clock" size="xs" />
            One question at a time — stop the current one above to ask something
            else.
          </span>
        ) : (
          /* Hidden on touch, where there are no keys to press. */
          <span className="composer__keys">
            <kbd className="composer__key">
              <Icon name="enter" size="xs" />
            </kbd>
            to send,
            <kbd className="composer__key">Shift</kbd>+
            <kbd className="composer__key">
              <Icon name="enter" size="xs" />
            </kbd>
            for a new line
          </span>
        )}
      </p>
    </form>
  );
});
