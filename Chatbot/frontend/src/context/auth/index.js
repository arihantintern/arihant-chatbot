/**
 * Public surface of the auth module.
 *
 * Import from '@/context/auth' — never reach into the individual files, so
 * the module's internals (how the session is stored, when it is refreshed)
 * stay free to change.
 */
export { AuthProvider } from './AuthProvider';
export { useAuth } from './useAuth';
export { AUTH_STATUS, SIGN_OUT_REASON } from './auth.constants';
