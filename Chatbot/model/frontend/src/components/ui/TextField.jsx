import './TextField.css';

import { useId } from 'react';

import { Icon } from './Icon';

/**
 * A labelled text input.
 *
 * The accessibility wiring is the point of this component. Every field gets a
 * real `<label for>` (not a placeholder pretending to be one — placeholders
 * vanish the moment you start typing, exactly when you might need to check
 * what the field wanted), and its hint and error are tied to the input with
 * `aria-describedby`, so a screen reader reads "Email, edit text, invalid,
 * that is not an email address" instead of leaving the message stranded.
 *
 * `error` is a string, not a boolean: there is no state where a field is
 * invalid and cannot say why.
 *
 * @param {object} props
 * @param {string} props.label
 * @param {import('react').ReactNode} [props.hint]     shown while valid
 * @param {string} [props.error]                       replaces the hint
 * @param {import('./icons').IconName} [props.icon]    leading affordance
 * @param {import('react').ReactNode} [props.trailing] a control inside the field
 * @param {boolean} [props.optional]                   labels the field, not the requirement
 * @param {import('react').Ref<HTMLInputElement>} [props.inputRef]
 */
export function TextField({
  label,
  hint,
  error,
  icon,
  trailing,
  optional = false,
  id,
  className = '',
  inputRef,
  ...inputProps
}) {
  const generatedId = useId();
  const inputId = id ?? `field-${generatedId}`;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;

  const describedBy = [error ? errorId : null, hint ? hintId : null]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={`field ${className}`.trim()} data-invalid={error ? '' : undefined}>
      <div className="field__header">
        <label className="field__label t-label" htmlFor={inputId}>
          {label}
        </label>
        {optional ? <span className="field__optional t-meta">Optional</span> : null}
      </div>

      <div className="field__control">
        {icon ? <Icon name={icon} size="sm" className="field__icon" /> : null}

        <input
          id={inputId}
          ref={inputRef}
          className="field__input"
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          {...inputProps}
        />

        {trailing ? <span className="field__trailing">{trailing}</span> : null}

        {/* The focus underline. A separate element so it can animate its own
            transform without the input's border jumping the text by a pixel. */}
        <span className="field__underline" aria-hidden="true" />
      </div>

      {/* One message slot, and the error owns it when there is one — stacking
          both makes the person read a hint about the rule they just broke. */}
      {error ? (
        <p className="field__message field__message--error" id={errorId}>
          <Icon name="alertCircle" size="xs" />
          {error}
        </p>
      ) : hint ? (
        <p className="field__message" id={hintId}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
