import { createContext } from 'react';

/**
 * The theme context object.
 *
 * Deliberately in its own file with no component in it: React Fast Refresh
 * can only hot-reload a module that exports components *or* values, not both.
 * Splitting context / provider / hook is what keeps edits to ThemeProvider
 * from blowing away app state on every save.
 *
 * @typedef  {object} ThemeContextValue
 * @property {'light'|'dark'|'system'} theme      what the user picked
 * @property {'light'|'dark'}          resolved   what is actually on screen
 * @property {boolean}                 isDark     convenience for `resolved === 'dark'`
 * @property {(next: 'light'|'dark'|'system') => void} setTheme
 * @property {() => void}              toggleTheme  light ⇄ dark, leaving `system`
 */

/** @type {import('react').Context<ThemeContextValue | null>} */
export const ThemeContext = createContext(null);
