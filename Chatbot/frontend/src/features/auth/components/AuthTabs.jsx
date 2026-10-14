import './AuthTabs.css';

import { useRef } from 'react';

/**
 * Sign in / Create account, as a two-position segmented control.
 *
 * Tabs rather than two separate screens: the two forms differ by two fields,
 * and someone who came to sign in and discovers they have no account should
 * not lose the email they already typed to find that out. AuthScreen keeps
 * the email between them.
 *
 * Full ARIA tab semantics, which means the keyboard has to work the way a
 * keyboard user expects: arrows move *and* select (automatic activation, the
 * right choice when switching is instant and cheap), Home/End jump to the
 * ends, and only the selected tab is a tab stop — Tab from the tablist goes
 * into the form, not along the tabs.
 *
 * @param {object} props
 * @param {string} props.value
 * @param {{value: string, label: string}[]} props.options
 * @param {(value: string) => void} props.onChange
 * @param {string} props.idPrefix  ties each tab to its panel
 */
export function AuthTabs({ value, options, onChange, idPrefix }) {
  const tabRefs = useRef([]);
  const activeIndex = options.findIndex((option) => option.value === value);

  const move = (nextIndex) => {
    const bounded = (nextIndex + options.length) % options.length;
    onChange(options[bounded].value);
    tabRefs.current[bounded]?.focus();
  };

  const onKeyDown = (event) => {
    const handlers = {
      ArrowRight: () => move(activeIndex + 1),
      ArrowLeft: () => move(activeIndex - 1),
      ArrowDown: () => move(activeIndex + 1),
      ArrowUp: () => move(activeIndex - 1),
      Home: () => move(0),
      End: () => move(options.length - 1),
    };

    const handler = handlers[event.key];
    if (!handler) return;

    event.preventDefault(); // ArrowDown would otherwise scroll the page
    handler();
  };

  return (
    <div className="auth-tabs" role="tablist" aria-label="Sign in or create an account">
      <span
        className="auth-tabs__thumb"
        style={{
          '--active-index': Math.max(activeIndex, 0),
          '--tab-count': options.length,
        }}
        aria-hidden="true"
      />

      {options.map((option, index) => {
        const selected = option.value === value;

        return (
          <button
            key={option.value}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${option.value}`}
            aria-controls={`${idPrefix}-panel-${option.value}`}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            className="auth-tabs__tab"
            onClick={() => onChange(option.value)}
            onKeyDown={onKeyDown}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
