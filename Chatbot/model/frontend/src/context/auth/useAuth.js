import { useContext } from 'react';

import { AuthContext } from './AuthContext';

/**
 * Read the current session.
 *
 * @returns {import('./AuthContext').AuthContextValue}
 * @throws  if called outside <AuthProvider> — a loud failure at the call site
 *          beats a silent `undefined.user` three renders later.
 */
export function useAuth() {
  const context = useContext(AuthContext);

  if (context === null) {
    throw new Error('useAuth() must be used inside an <AuthProvider>.');
  }

  return context;
}
