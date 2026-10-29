import './AuthGate.css';

import { useEffect, useState } from 'react';

import { Logo } from '@/components/brand';
import { AUTH_STATUS, useAuth } from '@/context/auth';
import { AuthScreen } from '@/features/auth';

/**
 * The one place that decides whether the app or the auth screen is showing.
 *
 * Every protected part of the product sits inside this — which means no
 * component below it has to wonder whether `user` might be null, and no route
 * can be reached by someone who is not signed in because it forgot to check.
 */
export function AuthGate({ children }) {
  const { status } = useAuth();

  if (status === AUTH_STATUS.LOADING) return <BootScreen />;
  if (status === AUTH_STATUS.ANONYMOUS) return <AuthScreen />;

  return children;
}

/**
 * The moment between "the page loaded" and "we know who this is".
 *
 * It waits before showing itself. Restoring a stored session is usually
 * instant — the token is read from storage and trusted, and the API is only
 * consulted in the background — so a spinner that renders immediately would
 * appear and vanish inside two frames, which reads as a flicker, not as
 * progress. Nothing at all for the first fifth of a second is calmer, and
 * after that something has genuinely gone slow and is worth explaining.
 */
function BootScreen() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setVisible(true), 200);
    return () => clearTimeout(timer);
  }, []);

  if (!visible) return null;

  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="boot__inner a-fade-in">
        <Logo variant="mark" height={44} className="boot__mark" title={null} />
        <p className="boot__label">Restoring your session…</p>
      </div>
    </div>
  );
}
