/**
 * Public surface of the auth feature.
 *
 * The screen is the only thing outside this folder needs. Its forms, tabs and
 * validation are implementation detail, and keeping them unexported is what
 * stops a future page from importing `SignInForm` and rendering it somewhere
 * it cannot work.
 */
export { AuthScreen } from './AuthScreen';
