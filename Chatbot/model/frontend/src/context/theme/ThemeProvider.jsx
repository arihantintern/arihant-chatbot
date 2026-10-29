import { useCallback, useEffect, useMemo, useState } from 'react';

import { ThemeContext } from './ThemeContext';
import {
  DEFAULT_THEME,
  THEME,
  THEME_STORAGE_KEY,
  THEME_VALUES,
} from './theme.constants';

const DARK_QUERY = '(prefers-color-scheme: dark)';

/** The OS preference, or light when there is no window (SSR, tests). */
function systemTheme() {
  if (typeof window === 'undefined' || !window.matchMedia) return THEME.LIGHT;
  return window.matchMedia(DARK_QUERY).matches ? THEME.DARK : THEME.LIGHT;
}

/**
 * Read the stored preference. Wrapped in try/catch because localStorage
 * throws — not returns null — in Safari private mode and when a browser
 * blocks third-party storage. A theme preference is never worth a crash.
 */
function storedTheme() {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return THEME_VALUES.includes(value) ? value : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

/**
 * Owns the app's light/dark preference and reflects it onto <html>.
 *
 * Nothing below this provider reads `prefers-color-scheme` itself, and no
 * component ever branches on the theme to pick a colour — the CSS in
 * styles/tokens/semantic.css does that. Components read `isDark` only for the
 * handful of things CSS genuinely cannot express, like choosing which logo
 * SVG file to load.
 */
export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(storedTheme);
  const [systemPreference, setSystemPreference] = useState(systemTheme);

  /* Follow the OS while the preference is `system` — someone flipping their
     laptop to dark mode at sunset should see this app follow, mid-session. */
  useEffect(() => {
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event) =>
      setSystemPreference(event.matches ? THEME.DARK : THEME.LIGHT);

    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  const resolved = theme === THEME.SYSTEM ? systemPreference : theme;

  /* Reflect onto <html>, where the CSS is listening. The pre-paint script in
     index.html has already done this for the first frame; from here on it is
     React's job. */
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolved;

    /* Keeps the browser's own chrome — mobile address bar, form controls,
       the flash between page loads — in step with the app. */
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute(
        'content',
        getComputedStyle(root).getPropertyValue('--color-canvas').trim(),
      );
    }
  }, [resolved]);

  const setTheme = useCallback((next) => {
    if (!THEME_VALUES.includes(next)) return;
    setThemeState(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* Storage denied — the choice still applies for this session. */
    }
  }, []);

  /* A toggle is a two-state control, so it commits to an explicit choice
     rather than cycling through `system`. Picking `system` again is a
     deliberate act, done from the settings menu. */
  const toggleTheme = useCallback(() => {
    setTheme(resolved === THEME.DARK ? THEME.LIGHT : THEME.DARK);
  }, [resolved, setTheme]);

  const value = useMemo(
    () => ({
      theme,
      resolved,
      isDark: resolved === THEME.DARK,
      setTheme,
      toggleTheme,
    }),
    [theme, resolved, setTheme, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
