import './Spinner.css';

/**
 * An indeterminate spinner.
 *
 * Silent to assistive technology by default: the thing that is busy — a
 * button, a panel — carries `aria-busy`, and announcing "loading" from the
 * decoration as well means hearing it twice. Pass a `label` only when the
 * spinner stands alone with nothing else to describe it.
 *
 * @param {object} props
 * @param {'sm'|'md'|'lg'} [props.size='md']
 * @param {string} [props.label]  announced, and shown to nobody
 * @param {string} [props.className]
 */
export function Spinner({ size = 'md', label, className = '', ...rest }) {
  return (
    <span
      className={`spinner spinner--${size} ${className}`.trim()}
      role={label ? 'status' : 'presentation'}
      aria-hidden={label ? undefined : true}
      {...rest}
    >
      {label ? <span className="u-sr-only">{label}</span> : null}
    </span>
  );
}
