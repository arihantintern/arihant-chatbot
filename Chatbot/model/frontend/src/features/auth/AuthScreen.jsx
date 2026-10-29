import './AuthScreen.css';

import { useCallback, useState } from 'react';

import { Logo } from '@/components/brand';
import { ThemeToggle } from '@/components/theme';
import { Alert } from '@/components/ui';
import { useAuth } from '@/context/auth';

import { AuthShowcase } from './components/AuthShowcase';
import { AuthTabs } from './components/AuthTabs';
import { ServiceStatus } from './components/ServiceStatus';
import { SignInForm } from './components/SignInForm';
import { SignUpForm } from './components/SignUpForm';

const VIEW = { SIGN_IN: 'signIn', SIGN_UP: 'signUp' };

const TABS = [
  { value: VIEW.SIGN_IN, label: 'Sign in' },
  { value: VIEW.SIGN_UP, label: 'Create account' },
];

const HEADINGS = {
  [VIEW.SIGN_IN]: {
    title: 'Welcome back',
    lead: 'Sign in to pick up your conversations where you left them.',
  },
  [VIEW.SIGN_UP]: {
    title: 'Create your account',
    lead: 'A minute to set up, and the assistant is yours.',
  },
};

/**
 * The whole unauthenticated experience: sign in, or make an account.
 *
 * It owns two pieces of state, and both are here rather than inside the forms
 * for the same reason — they have to survive the tab switch:
 *
 *   `view`   which form is showing
 *   `email`  what has been typed into the email field, either of them
 *
 * The email is the one that matters. Someone types their address, presses
 * sign in, is told the account does not exist, switches to Create account —
 * and finds the address already filled in. Re-typing it would be a small,
 * entirely avoidable insult.
 */
export function AuthScreen() {
  const { notice, dismissNotice } = useAuth();
  const [view, setView] = useState(VIEW.SIGN_IN);
  const [email, setEmail] = useState('');

  const switchTo = useCallback(
    (next) => {
      setView(next);
      /* The notice explains why the *last session* ended. Once someone has
         started doing something else, it is stale — leaving it above a
         registration form to say "your session expired" is just noise. */
      dismissNotice();
    },
    [dismissNotice],
  );

  const heading = HEADINGS[view];

  return (
    <main className="auth">
      {/*
        The form comes first in the DOM and is placed in the second column by
        the grid. Two reasons, and they point the same way: on a phone (where
        the showcase is not rendered at all) the form is what the page opens
        with, and for a screen reader the h1 is reached before the showcase's
        h2 rather than after it.
      */}
      <div className="auth__panel">
        <div className="auth__panel-inner">
          <header className="auth__head">
            {/* On wide screens the showcase states the brand; repeating the
                lockup here would be the third Arihant logo on one screen. */}
            <Logo variant="lockup" height={30} className="auth__logo" />
            <ThemeToggle size="sm" />
          </header>

          {/* Keyed by view so the heading is re-mounted and re-animated when
              the tab changes — the two forms should not feel like one form
              whose labels quietly changed.

              The key is *prefixed* because the panel below is keyed by view
              too, and they are siblings: two children of one parent sharing a
              key is unsupported, and React reconciles it by leaving both on
              screen. */}
          <div className="auth__intro" key={`intro-${view}`}>
            <h1 className="t-h1 auth__title">{heading.title}</h1>
            <p className="t-caption auth__lead">{heading.lead}</p>
          </div>

          <AuthTabs value={view} options={TABS} onChange={switchTo} idPrefix="auth" />

          {notice ? (
            <Alert tone={notice.tone} onDismiss={dismissNotice} compact>
              {notice.message}
            </Alert>
          ) : null}

          <div
            key={`panel-${view}`}
            id={`auth-panel-${view}`}
            role="tabpanel"
            aria-labelledby={`auth-tab-${view}`}
            className="auth__form a-fade-in-up"
          >
            {view === VIEW.SIGN_IN ? (
              <SignInForm
                email={email}
                onEmailChange={setEmail}
                onNeedAccount={() => switchTo(VIEW.SIGN_UP)}
              />
            ) : (
              <SignUpForm
                email={email}
                onEmailChange={setEmail}
                onHaveAccount={() => switchTo(VIEW.SIGN_IN)}
              />
            )}
          </div>

          <footer className="auth__foot">
            <ServiceStatus />
            <p className="auth__legal">
              Arihant Capital Markets Ltd · Internal research tool. Answers are
              generated and should be checked before they are acted on.
            </p>
          </footer>
        </div>
      </div>

      <AuthShowcase />
    </main>
  );
}
