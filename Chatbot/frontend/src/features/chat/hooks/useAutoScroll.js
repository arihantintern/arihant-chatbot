import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Keep the newest turn in view — unless the person is reading something else.
 *
 * THE RULE: follow the bottom while they are *at* the bottom, and never move
 * the page once they have scrolled away from it. Getting this wrong is one of
 * the most irritating things a chat interface can do: you scroll up to reread
 * an answer, the assistant finishes writing, and you are yanked to the end of
 * a conversation you were deliberately not looking at.
 *
 * So "pinned" is a fact about the scroll position, re-measured on every scroll
 * event, and every automatic scroll is conditional on it.
 *
 * A ResizeObserver rather than only reacting to the turn list changing,
 * because the two things that move the bottom are different in kind. A new
 * turn is a state change and could be watched from React; the *pending* turn
 * growing — the activity trace adding a note, an answer replacing it — is a
 * layout change with no state change of its own. Observing the content's
 * height catches both without a list of dependencies to keep in step.
 */

/**
 * How close to the bottom still counts as "at the bottom".
 *
 * Generous on purpose: a couple of lines of slack means nudging the wheel
 * while an answer arrives does not silently switch following off.
 */
const PINNED_WITHIN_PX = 120;

export function useAutoScroll() {
  const viewportRef = useRef(null);
  const contentRef = useRef(null);

  /* A ref as well as state: the observer callback needs the current value
     without being re-created every time it changes, and the pill that offers
     the way back needs to re-render when it does. */
  const pinnedRef = useRef(true);
  const [pinned, setPinned] = useState(true);

  const scrollToEnd = useCallback((behavior = 'smooth') => {
    const viewport = viewportRef.current;
    if (!viewport) return;

    pinnedRef.current = true;
    setPinned(true);
    viewport.scrollTo({ top: viewport.scrollHeight, behavior });
  }, []);

  /* --- measure ---------------------------------------------------------- */
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return undefined;

    const measure = () => {
      const distance = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
      const near = distance <= PINNED_WITHIN_PX;

      pinnedRef.current = near;
      /* Only when it actually changes — a scroll event fires per frame, and
         setting the same value would still re-render the whole column. */
      setPinned((current) => (current === near ? current : near));
    };

    measure();
    viewport.addEventListener('scroll', measure, { passive: true });
    return () => viewport.removeEventListener('scroll', measure);
  }, []);

  /* --- follow ----------------------------------------------------------- */
  useEffect(() => {
    const viewport = viewportRef.current;
    const content = contentRef.current;
    if (!viewport || !content) return undefined;

    const observer = new ResizeObserver(() => {
      if (!pinnedRef.current) return;

      /* 'auto', not 'smooth'. This fires while content is growing, and a
         smooth scroll that is restarted every frame never arrives. */
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: 'auto' });
    });

    observer.observe(content);
    return () => observer.disconnect();
  }, []);

  return { viewportRef, contentRef, pinned, scrollToEnd };
}
