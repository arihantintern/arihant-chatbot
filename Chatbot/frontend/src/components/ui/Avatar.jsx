import './Avatar.css';

/**
 * Initials in a tinted circle.
 *
 * The tint is derived from the account id rather than picked at random or
 * always brand-green: a person's avatar has to be the same colour every time
 * they see it, or it stops being *theirs*. Six hues, spread far enough apart
 * to be told apart at 28px, all from the data-series tokens so they are
 * already checked against both themes.
 *
 * @param {object} props
 * @param {string} props.name
 * @param {string} [props.seed]  what the colour is derived from; defaults to the name
 * @param {'sm'|'md'|'lg'} [props.size='md']
 */
export function Avatar({ name, seed, size = 'md', className = '', ...rest }) {
  return (
    <span
      className={`avatar avatar--${size} ${className}`.trim()}
      data-series={seriesFor(seed || name)}
      /* The name is always beside it in this app, and hearing "AK" read out
         after it is noise. */
      aria-hidden="true"
      {...rest}
    >
      {initials(name)}
    </span>
  );
}

/**
 * One or two letters.
 *
 * "Vandan Nagori" → VN, "vandan" → V, "" → ?. Only the first and last words
 * are used: a three-part name would otherwise give three letters, and three
 * letters do not fit in a 28px circle.
 */
function initials(name) {
  const words = String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (words.length === 0) return '?';
  if (words.length === 1) return words[0][0].toUpperCase();

  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/** A stable 1–6 from a string. Not a hash worth defending — just spread. */
function seriesFor(value) {
  let total = 0;
  for (let index = 0; index < value.length; index += 1) {
    total = (total + value.charCodeAt(index) * (index + 1)) % 997;
  }
  return (total % 6) + 1;
}
