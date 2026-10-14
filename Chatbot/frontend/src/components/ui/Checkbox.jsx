import './Checkbox.css';

import { useId } from 'react';

import { Icon } from './Icon';

/**
 * A checkbox with a real `<input type="checkbox">` under it.
 *
 * `appearance: none` on the input keeps every native behaviour that matters —
 * Space to toggle, form participation, the accessibility tree, indeterminate
 * state — and gives up only the operating system's own drawing of the box,
 * which is the one part worth replacing.
 *
 * @param {object} props
 * @param {string} props.label
 * @param {import('react').ReactNode} [props.hint]
 */
export function Checkbox({ label, hint, id, className = '', ...inputProps }) {
  const generatedId = useId();
  const inputId = id ?? `checkbox-${generatedId}`;
  const hintId = `${inputId}-hint`;

  return (
    <div className={`checkbox ${className}`.trim()}>
      <input
        type="checkbox"
        id={inputId}
        className="checkbox__input"
        aria-describedby={hint ? hintId : undefined}
        {...inputProps}
      />

      <label className="checkbox__label" htmlFor={inputId}>
        <span className="checkbox__box" aria-hidden="true">
          <Icon name="check" size="xs" />
        </span>

        <span className="checkbox__text">
          {label}
          {hint ? (
            <span className="checkbox__hint t-meta" id={hintId}>
              {hint}
            </span>
          ) : null}
        </span>
      </label>
    </div>
  );
}
