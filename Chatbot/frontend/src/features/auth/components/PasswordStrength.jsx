import './PasswordStrength.css';

import { STRENGTH_LABELS, passwordStrength } from '../validation';

const MAX_SCORE = STRENGTH_LABELS.length - 1;

/**
 * How good the password being typed is.
 *
 * Advisory, and it says so by never blocking anything: the backend's rule is
 * eight characters, and a password this meter calls "Weak" registers exactly
 * as successfully as one it calls "Excellent". A meter that quietly refuses to
 * let you submit is a rule wearing a hint's clothing.
 *
 * Not a live region. It updates on every keystroke, and announcing four
 * different strength labels while someone types their password is the kind of
 * accessibility that makes people turn accessibility off. The rule that
 * *does* gate submission — eight characters — is on the field itself, where a
 * screen reader will read it as part of the input's description.
 */
export function PasswordStrength({ password }) {
  const { score, label, suggestion } = passwordStrength(password);

  // Nothing typed yet: no meter, and no reserved gap where one might appear.
  if (!password) return null;

  return (
    <div className="strength" data-score={score}>
      <div className="strength__meter" aria-hidden="true">
        {Array.from({ length: MAX_SCORE }, (_, index) => (
          <span
            key={index}
            className="strength__segment"
            data-filled={index < score ? '' : undefined}
            /* Each segment fills a beat after the one before it, so growing
               stronger reads as a movement rather than a step change. */
            style={{ '--stagger-index': index }}
          />
        ))}
      </div>

      <p className="strength__caption">
        <span className="strength__label">{label}</span>
        {suggestion ? <span className="strength__hint">{suggestion}</span> : null}
      </p>
    </div>
  );
}
