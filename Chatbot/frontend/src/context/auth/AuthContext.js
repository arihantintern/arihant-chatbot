import { createContext } from 'react';

/**
 * The auth context object.
 *
 * In its own file with no component in it, for the same reason ThemeContext
 * is: Fast Refresh can hot-reload a module that exports components *or*
 * values, not both. Splitting context / provider / hook is what keeps a save
 * in AuthProvider.jsx from signing you out.
 *
 * @typedef  {object} AuthContextValue
 * @property {'loading'|'anonymous'|'authenticated'} status
 * @property {import('@/api/auth.api').User|null} user
 * @property {boolean} isAuthenticated
 * @property {boolean} isAdmin
 * @property {{tone: string, message: string}|null} notice
 *   Why the last session ended — shown on the auth screen, so being signed
 *   out is never unexplained.
 * @property {(credentials: {email: string, password: string, remember?: boolean}) => Promise<import('@/api/auth.api').User>} signIn
 * @property {(details: {name?: string, email: string, password: string, remember?: boolean}) => Promise<import('@/api/auth.api').User>} signUp
 * @property {() => void} signOut
 * @property {() => void} dismissNotice
 */

/** @type {import('react').Context<AuthContextValue | null>} */
export const AuthContext = createContext(null);
