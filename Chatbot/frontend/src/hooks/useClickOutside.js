import { useEffect } from 'react';

/**
 * Call `handler` when a pointer goes down anywhere outside `ref`.
 *
 * `pointerdown`, not `click`: a click fires after the button comes back up, by
 * which time the person may have pressed inside the menu and released outside
 * it (a text selection that ran past the edge, a drag). Reacting to the press
 * is what matches the intent — and it also means the menu is gone before the
 * thing underneath receives its own click.
 *
 * @param {import('react').RefObject<HTMLElement>} ref
 * @param {(event: PointerEvent) => void} handler
 * @param {boolean} [active=true]  skip the listener entirely while closed
 */
export function useClickOutside(ref, handler, active = true) {
  useEffect(() => {
    if (!active) return undefined;

    const onPointerDown = (event) => {
      const element = ref.current;
      if (!element || element.contains(event.target)) return;
      handler(event);
    };

    /* On the capture phase, so a child that calls stopPropagation for its own
       reasons cannot leave the menu stuck open. */
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [ref, handler, active]);
}
