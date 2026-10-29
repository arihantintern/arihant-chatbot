/**
 * Shared constants for the theme system.
 *
 * ⚠️  The pre-paint script in index.html duplicates THEME_STORAGE_KEY and the
 * resolution rule below. It has to: it runs before any JavaScript module is
 * parsed, which is the only way to set `data-theme` before the first paint and
 * avoid a white flash on a dark-mode reload. If you change the key or the
 * rule here, change it there too — those are the only two places it lives.
 */

/** The user's *preference*: three states, not two. */
export const THEME = {
  LIGHT: 'light',
  DARK: 'dark',
  /** Follow the OS, and keep following it if the OS changes mid-session. */
  SYSTEM: 'system',
};

export const THEME_VALUES = Object.values(THEME);

/** The *resolved* themes — the only values ever written to `data-theme`. */
export const RESOLVED_THEMES = [THEME.LIGHT, THEME.DARK];

export const THEME_STORAGE_KEY = 'arihant.theme';

export const DEFAULT_THEME = THEME.SYSTEM;

/** Human labels for the theme switcher. */
export const THEME_LABELS = {
  [THEME.LIGHT]: 'Light',
  [THEME.DARK]: 'Dark',
  [THEME.SYSTEM]: 'System',
};
