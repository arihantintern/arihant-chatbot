import './Alert.css';

import { Icon } from './Icon';

/** Each tone brings its own icon, so a caller cannot pair "success" with a
    warning triangle by accident. */
const TONE_ICONS = {
  danger: 'alertCircle',
  warning: 'alertTriangle',
  success: 'checkCircle',
  info: 'info',
};

/**
 * An inline message about the thing next to it — a failed sign-in, an
 * explanation of why the session ended.
 *
 * The `role` is chosen by tone, and it matters more than it looks:
 * `role="alert"` interrupts a screen reader mid-sentence, which is right when
 * a submit just failed and wrong for "you have been signed out", which the
 * person already knows because they asked. Failures assert; the rest is a
 * polite status.
 *
 * @param {object} props
 * @param {'danger'|'warning'|'success'|'info'} [props.tone='info']
 * @param {string} [props.title]
 * @param {() => void} [props.onDismiss]
 * @param {boolean} [props.compact]
 */
export function Alert({
  tone = 'info',
  title,
  onDismiss,
  compact = false,
  className = '',
  children,
  ...rest
}) {
  const assertive = tone === 'danger' || tone === 'warning';

  return (
    <div
      className={['alert', `alert--${tone}`, compact ? 'alert--compact' : '', className]
        .filter(Boolean)
        .join(' ')}
      role={assertive ? 'alert' : 'status'}
      {...rest}
    >
      <Icon name={TONE_ICONS[tone]} size="md" className="alert__icon" />

      <div className="alert__body">
        {title ? <p className="alert__title">{title}</p> : null}
        <div className="alert__text">{children}</div>
      </div>

      {onDismiss ? (
        <button
          type="button"
          className="alert__dismiss"
          onClick={onDismiss}
          /* "Dismiss" alone is fine visually and useless in a list of
             buttons read out of context. */
          aria-label="Dismiss this message"
        >
          <Icon name="x" size="sm" />
        </button>
      ) : null}
    </div>
  );
}
