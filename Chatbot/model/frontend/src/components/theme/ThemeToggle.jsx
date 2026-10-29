import './ThemeToggle.css';

import { useId } from 'react';

import { Icon } from '@/components/ui';
import { THEME, THEME_LABELS, useTheme } from '@/context/theme';

const OPTIONS = [
  { value: THEME.LIGHT, icon: 'sun' },
  { value: THEME.SYSTEM, icon: 'monitor' },
  { value: THEME.DARK, icon: 'moon' },
];

/**
 * The theme switcher: light, system, dark.
 *
 * Three states rather than a two-state switch, because "system" is a real
 * preference and not a default — someone whose laptop goes dark at sunset
 * wants this app to follow, and a binary toggle cannot express that.
 *
 * Built on native radio inputs. A `div` with `role="radiogroup"` needs arrow
 * keys, roving tabindex and focus management written by hand; real radios
 * bring all of it, correctly, in every browser and every screen reader. They
 * are hidden visually, not semantically.
 *
 * @param {object} props
 * @param {'sm'|'md'} [props.size='md']
 */
export function ThemeToggle({ size = 'md', className = '' }) {
  const { theme, setTheme } = useTheme();
  const groupName = `theme-${useId()}`;
  const activeIndex = OPTIONS.findIndex((option) => option.value === theme);

  return (
    <fieldset className={`theme-toggle theme-toggle--${size} ${className}`.trim()}>
      <legend className="u-sr-only">Colour theme</legend>

      <div className="theme-toggle__track">
        {/* The thumb is one element that slides, not three that fade: the
            movement is what tells you the control has three positions. */}
        <span
          className="theme-toggle__thumb"
          style={{ '--active-index': Math.max(activeIndex, 0) }}
          aria-hidden="true"
        />

        {OPTIONS.map(({ value, icon }) => (
          <label key={value} className="theme-toggle__option" title={THEME_LABELS[value]}>
            <input
              className="u-sr-only"
              type="radio"
              name={groupName}
              value={value}
              checked={theme === value}
              onChange={() => setTheme(value)}
            />
            <Icon name={icon} size={size === 'sm' ? 'sm' : 'md'} />
            <span className="u-sr-only">{THEME_LABELS[value]}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
