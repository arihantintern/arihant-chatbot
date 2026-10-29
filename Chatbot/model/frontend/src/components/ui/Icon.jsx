import './Icon.css';

import { ICONS } from './icons';

/** Named sizes come from tokens; a number is an escape hatch, in px. */
function dimension(size) {
  return typeof size === 'number' ? `${size}px` : `var(--icon-size-${size})`;
}

/**
 * One icon from the set in icons.js.
 *
 * Accessibility, which is the whole reason this is a component and not a
 * `<svg>` copy-pasted twenty times: an icon is *decorative by default*.
 * Almost every icon in this app sits beside a text label that already says
 * what it means, and announcing it again is noise. Pass `title` only when the
 * icon is the only thing carrying the meaning — an icon-only button.
 *
 * @param {object} props
 * @param {import('./icons').IconName} props.name
 * @param {'xs'|'sm'|'md'|'lg'|'xl'|'2xl'|number} [props.size='md']
 * @param {string} [props.title]  accessible name; omit for decorative icons
 * @param {number} [props.strokeWidth]
 * @param {string} [props.className]
 */
export function Icon({ name, size = 'md', title, strokeWidth, className = '', ...rest }) {
  const paths = ICONS[name];

  if (!paths) {
    /* A typo'd name should be loud in development and invisible in
       production — never a broken glyph box in the middle of a button. */
    if (import.meta.env.DEV) console.warn(`<Icon> unknown name: "${name}"`);
    return null;
  }

  return (
    <svg
      className={`icon ${className}`.trim()}
      viewBox="0 0 24 24"
      style={{
        '--icon-dimension': dimension(size),
        ...(strokeWidth ? { '--icon-stroke': strokeWidth } : null),
      }}
      data-size={typeof size === 'string' ? size : undefined}
      role={title ? 'img' : 'presentation'}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      {...rest}
    >
      {/* Path data is static and never reordered, so the index is a stable
          identity here. */}
      {paths.map((d, index) => (
        <path key={index} d={d} />
      ))}
    </svg>
  );
}
