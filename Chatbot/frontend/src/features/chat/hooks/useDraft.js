import { useCallback, useEffect, useState } from 'react';

import { DRAFT_KEY_PREFIX } from '@/context/chat/chat.constants';
import { readJson, remove, STORAGE, writeJson } from '@/lib/storage';

/**
 * A half-typed question, remembered per conversation.
 *
 * The case this is for: somebody types out a long question, then clicks into
 * an older conversation to check what they already asked about it. Coming back
 * to a cleared box would be the app throwing away their work — and the reverse,
 * carrying one conversation's draft into another, would be just as wrong.
 * Keying by conversation gets both right.
 *
 * sessionStorage rather than localStorage, for the same reason the citation
 * cache uses it: a half-written question is the most private thing in the app,
 * and it should not still be there tomorrow on a shared machine.
 *
 * @param {string|null} conversationId  null while the conversation is new
 * @returns {[string, (value: string) => void, () => void]}  value, set, clear
 */
export function useDraft(conversationId) {
  const key = `${DRAFT_KEY_PREFIX}.${conversationId ?? 'new'}`;

  /* The stored key travels *with* the value, which is what makes switching
     conversation correct without an effect.

     Read in the initialiser, so the box is filled on the first paint — an
     effect would show an empty textarea for one frame first, which reads as
     the draft having been lost. */
  const [stored, setStored] = useState(() => ({
    key,
    value: readJson(key, STORAGE.SESSION) ?? '',
  }));

  /* Switching conversation swaps the draft, and it happens *during render*
     rather than in an effect. React supports exactly this — adjusting state
     when the input it derives from changes — and re-renders immediately
     without painting in between. Doing it in an effect would paint the
     previous conversation's draft for one frame, which is the bug this hook
     exists to prevent. */
  if (stored.key !== key) {
    setStored({ key, value: readJson(key, STORAGE.SESSION) ?? '' });
  }

  const value = stored.value;
  const setValue = useCallback(
    (next) => setStored((current) => ({ key: current.key, value: next })),
    [],
  );

  /* Writing to storage *is* an effect's job: synchronising React state out to
     an external system. */
  useEffect(() => {
    if (value.trim()) {
      writeJson(key, value, STORAGE.SESSION);
    } else {
      /* An empty draft is not worth a key, and leaving one behind means the
         next read has to distinguish "" from absent. */
      remove(key, STORAGE.SESSION);
    }
  }, [key, value]);

  const clear = useCallback(() => setValue(''), [setValue]);

  return [value, setValue, clear];
}
