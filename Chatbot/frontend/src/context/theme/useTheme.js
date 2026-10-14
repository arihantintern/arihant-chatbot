import { useContext } from 'react';

import { ThemeContext } from './ThemeContext';

/**
 * Read the current theme.
 *
 * @returns {import('./ThemeContext').ThemeContextValue}
 * @throws  if called outside <ThemeProvider> — a loud failure at the call
 *          site beats a silent `undefined.isDark` three renders later.
 */
export function useTheme() {
  const context = useContext(ThemeContext);

  if (context === null) {
    throw new Error('useTheme() must be used inside a <ThemeProvider>.');
  }

  return context;
}
