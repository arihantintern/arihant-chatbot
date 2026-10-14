import { useEffect } from 'react';

/**
 * The keyboard, for the three things that are worth a shortcut.
 *
 *   ⌘K / Ctrl+K   search everything you have asked
 *   ⌘⇧O           start a new conversation
 *   /             focus the composer, from anywhere that is not a text field
 *
 * ONE LISTENER, ON THE DOCUMENT. Not one per component: three listeners racing
 * for the same keystroke is how a shortcut ends up doing two things, and
 * having them in one table is the only way to see at a glance that none of
 * them collide.
 *
 * THE BARE `/` NEEDS THE GUARD BELOW. It is the single best shortcut in a chat
 * app — no modifier, right there — and it is also a character people type. So
 * it only fires when focus is somewhere that is not accepting text, which is
 * what stops it from swallowing the slash in "P/E ratio".
 *
 * Escape is deliberately absent: each overlay handles its own, because "close
 * the top-most thing" is a fact only that thing knows (the search palette
 * closes an expanded result first, then itself).
 *
 * @param {object} handlers
 * @param {() => void} handlers.onSearch
 * @param {() => void} handlers.onNew
 * @param {() => void} handlers.onFocusComposer
 */
export function useChatShortcuts({ onSearch, onNew, onFocusComposer }) {
  useEffect(() => {
    const onKeyDown = (event) => {
      /* metaKey on a Mac, ctrlKey everywhere else. Accepting either means the
         shortcut works for someone on a Mac with an external PC keyboard, and
         costs nothing. */
      const command = event.metaKey || event.ctrlKey;

      if (command && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        onSearch();
        return;
      }

      if (command && event.shiftKey && event.key.toLowerCase() === 'o') {
        event.preventDefault();
        onNew();
        return;
      }

      if (event.key === '/' && !command && !isTyping(event.target)) {
        event.preventDefault();
        onFocusComposer();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onSearch, onNew, onFocusComposer]);
}

/**
 * Is this element somewhere text goes?
 *
 * `isContentEditable` as well as the tags, because a rich-text field is not an
 * input and would otherwise lose every slash typed into it.
 */
function isTyping(target) {
  if (!target) return false;
  if (target.isContentEditable) return true;

  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}
