import './PasswordField.css';

import { useState } from 'react';

import { Icon } from './Icon';
import { TextField } from './TextField';

/**
 * A password input with the two affordances a password input needs.
 *
 * SHOW/HIDE. Masking protects against someone reading over a shoulder, and
 * costs the person the ability to check what they typed — which is why the
 * usual outcome of a masked field is a failed login and a retype. Letting
 * them choose, per field, per moment, is strictly better than deciding for
 * them. It resets to masked on every mount, so nothing is left revealed.
 *
 * CAPS LOCK. The single most common cause of "wrong email or password" when
 * the password was in fact right, and completely invisible in a masked field.
 * The browser will tell us, but only while a key is being pressed — so the
 * warning appears on the first keystroke and is dropped the moment the lock
 * is released.
 *
 * @param {object} props  everything TextField takes, minus `type`
 */
export function PasswordField({ hint, autoComplete = 'current-password', ...rest }) {
  const [revealed, setRevealed] = useState(false);
  const [capsLock, setCapsLock] = useState(false);

  const trackCapsLock = (event) => {
    /* Wrapped: getModifierState is unimplemented on some synthetic events and
       on a few mobile keyboards, and a missing warning is a much smaller
       problem than a crash on keypress. */
    try {
      setCapsLock(event.getModifierState('CapsLock'));
    } catch {
      setCapsLock(false);
    }
  };

  return (
    <TextField
      {...rest}
      type={revealed ? 'text' : 'password'}
      icon="lock"
      autoComplete={autoComplete}
      spellCheck="false"
      onKeyDown={trackCapsLock}
      onKeyUp={trackCapsLock}
      /* The warning takes the hint's slot rather than adding a line, so the
         form does not grow taller mid-typing and shift the button out from
         under the cursor. */
      hint={
        capsLock ? (
          <span className="password-field__caps">
            <Icon name="alertTriangle" size="xs" />
            Caps Lock is on
          </span>
        ) : (
          hint
        )
      }
      trailing={
        <button
          type="button"
          className="password-field__toggle"
          onClick={() => setRevealed((current) => !current)}
          aria-pressed={revealed}
          /* The label says what the button *does*, and the state is carried by
             aria-pressed — a label that flips between "Show" and "Hide" makes
             the announcement ambiguous the moment it is read out of order. */
          aria-label="Show password"
          title={revealed ? 'Hide password' : 'Show password'}
        >
          <Icon name={revealed ? 'eyeOff' : 'eye'} size="sm" />
        </button>
      }
    />
  );
}
