import './Logo.css';

import {
  LOCKUP_PATHS,
  LOCKUP_RATIO,
  LOCKUP_VIEWBOX,
  MARK_PATHS,
  MARK_RATIO,
  MARK_VIEWBOX,
} from './logoPaths';

/**
 * The Arihant Plus logo.
 *
 * Rendered as inline SVG rather than an <img>, for three reasons that all
 * matter here: the wordmark can invert for dark mode through a CSS variable,
 * it costs no extra network request, and it can be given a real accessible
 * name instead of alt text on a decorative image.
 *
 * @param {object}  props
 * @param {'lockup'|'mark'} [props.variant='lockup']
 *   'lockup' is the mark plus the "arihant plus" wordmark — use it wherever
 *   the brand is being stated (auth screens, the top bar, print).
 *   'mark' is the eleven squares alone — use it where space is tight or the
 *   brand is already established (the collapsed rail, the agent avatar).
 * @param {number}  [props.height=32]  Height in px; width follows the ratio.
 * @param {string}  [props.title]
 *   Accessible name. Pass `null` for a purely decorative instance sitting
 *   next to a text label — it is then hidden from screen readers rather than
 *   read out twice.
 * @param {string}  [props.className]
 */
export function Logo({
  variant = 'lockup',
  height = 32,
  title = 'Arihant Plus',
  className = '',
  ...rest
}) {
  const isLockup = variant === 'lockup';
  const paths = isLockup ? LOCKUP_PATHS : MARK_PATHS;
  const viewBox = isLockup ? LOCKUP_VIEWBOX : MARK_VIEWBOX;
  const ratio = isLockup ? LOCKUP_RATIO : MARK_RATIO;
  const decorative = title === null;

  return (
    <svg
      className={`logo logo--${variant} ${className}`.trim()}
      viewBox={viewBox}
      width={Math.round(height * ratio)}
      height={height}
      fill="none"
      role={decorative ? 'presentation' : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : title}
      {...rest}
    >
      {paths.map(({ role, d }, index) => (
        // Path data is static and never reordered, so the index is a stable
        // identity here.
        <path key={index} className={`logo__path logo__path--${role}`} d={d} />
      ))}
    </svg>
  );
}
