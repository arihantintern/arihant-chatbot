import './DaySeparator.css';

/**
 * "Today", "Yesterday", "12 August 2026" — between the turns of one date.
 *
 * Sticky, so scrolling back through a long conversation always has the date of
 * whatever is on screen at the top of it. `--z-sticky` puts it above the turns
 * and below the composer and the top bar, which is exactly its place in the
 * stack.
 */
export function DaySeparator({ date }) {
  return (
    <div className="day">
      <span className="day__label">{label(date)}</span>
    </div>
  );
}

/**
 * Relative for the two days people reason about relatively, absolute beyond
 * that. "5 days ago" is harder to place than "15 August".
 */
function label(date) {
  const days = daysBetween(date, new Date());

  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';

  return date.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    /* The year only when it is not this one — "12 August" is unambiguous
       inside the current year and shorter to read. */
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
  });
}

/** Whole calendar days apart, not 24-hour blocks — 11pm last night is
    "yesterday" at 1am, not "0 days ago". */
function daysBetween(from, to) {
  const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return Math.round((startOfDay(to) - startOfDay(from)) / 86_400_000);
}
