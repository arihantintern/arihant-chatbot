import './Button.css';

import { Icon } from './Icon';
import { Spinner } from './Spinner';

/**
 * The app's button.
 *
 * Two decisions worth knowing about:
 *
 * `loading` keeps the label on screen and swaps the leading icon for a
 * spinner, rather than replacing the text with one. A button that empties
 * itself mid-submit changes width, which shifts the whole form, and it also
 * throws away the one piece of information the person wants — which action
 * they are waiting on. `loadingLabel` lets it say so in the present tense.
 *
 * `loading` also disables the button, so a double-click cannot send a second
 * registration. That is not defence in depth, it is the actual defence: the
 * backend's unique index would reject the duplicate, but the person would see
 * "that email already has an account" about the account they just made.
 *
 * @param {object} props
 * @param {'primary'|'secondary'|'ghost'|'danger'} [props.variant='primary']
 * @param {'sm'|'md'|'lg'} [props.size='md']
 * @param {boolean} [props.loading]
 * @param {string} [props.loadingLabel]  replaces the label while loading
 * @param {boolean} [props.fullWidth]
 * @param {import('./icons').IconName} [props.iconStart]
 * @param {import('./icons').IconName} [props.iconEnd]
 * @param {'button'|'submit'|'reset'} [props.type='button']
 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  loadingLabel,
  fullWidth = false,
  iconStart,
  iconEnd,
  type = 'button',
  disabled = false,
  className = '',
  children,
  ...rest
}) {
  const iconSize = size === 'sm' ? 'sm' : 'md';

  return (
    <button
      type={type}
      className={[
        'btn',
        `btn--${variant}`,
        `btn--${size}`,
        fullWidth ? 'btn--full' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      {...rest}
    >
      {/* The wash that sweeps across a primary button on hover. Painted here
          rather than with ::before so it can sit *under* the label without
          the label needing its own stacking context. */}
      <span className="btn__sheen" aria-hidden="true" />

      {loading ? (
        <Spinner size={size === 'lg' ? 'md' : 'sm'} />
      ) : iconStart ? (
        <Icon name={iconStart} size={iconSize} />
      ) : null}

      <span className="btn__label">
        {loading && loadingLabel ? loadingLabel : children}
      </span>

      {iconEnd && !loading ? (
        <Icon name={iconEnd} size={iconSize} className="btn__icon-end" />
      ) : null}
    </button>
  );
}
