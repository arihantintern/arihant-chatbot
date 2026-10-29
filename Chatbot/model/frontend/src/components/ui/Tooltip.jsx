import './Tooltip.css';

/**
 * A label that appears beside an icon-only control on hover or focus.
 *
 * Deliberately *not* an accessibility feature, and that distinction is the
 * whole design. The control inside must already carry its own accessible name
 * — `<Icon title>` or an `aria-label` — because a tooltip is unreachable by
 * touch, and a name that only exists on hover is a name half the people using
 * the app never get. So the bubble is `aria-hidden` and adds nothing to the
 * accessibility tree: it is a *reminder* for people who can see it, sitting on
 * top of a control that is already labelled properly underneath.
 *
 * No JS, no portal, no positioning library: it is a `position: absolute` child
 * revealed by `:hover`/`:focus-visible` on the wrapper. The one thing that
 * costs is that a tooltip cannot escape an `overflow: hidden` ancestor — which
 * is why the rail that uses it does not clip.
 *
 * @param {object} props
 * @param {string} props.label
 * @param {'end'|'start'|'top'|'bottom'} [props.side='end']  where it appears
 * @param {string} [props.shortcut]  a key hint shown after the label, e.g. '⌘K'
 */
export function Tooltip({ label, side = 'end', shortcut, className = '', children }) {
  return (
    <span className={`tooltip ${className}`.trim()} data-side={side}>
      {children}

      <span className="tooltip__bubble" role="presentation" aria-hidden="true">
        {label}
        {shortcut ? <kbd className="tooltip__key">{shortcut}</kbd> : null}
      </span>
    </span>
  );
}
