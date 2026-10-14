/**
 * Public surface of the theme module.
 *
 * Import from '@/context/theme' — never reach into the individual files, so
 * the module's internals stay free to change.
 */
export { ThemeProvider } from './ThemeProvider';
export { useTheme } from './useTheme';
export { THEME, THEME_LABELS, THEME_VALUES } from './theme.constants';
