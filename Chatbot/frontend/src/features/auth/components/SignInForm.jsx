import './AuthForm.css';

import { useCallback, useEffect, useRef, useState } from 'react';

import { Alert, Button, Checkbox, PasswordField, TextField } from '@/components/ui';
import { useAuth } from '@/context/auth';

import { useAuthForm } from '../hooks/useAuthForm';
import { validateEmail, validatePassword } from '../validation';

/**
 * Sign in to an existing account.
 *
 * The password is validated for *presence* only. The backend's `Login` model
 * has no minimum length on purpose — an existing password is either the right
 * one or it is not, and telling someone their real password is "too short to
 * try" is both false and baffling. Only registration applies the rule.
 */
export function SignInForm({ email, onEmailChange, onNeedAccount }) {
  const { signIn } = useAuth();
  const [remember, setRemember] = useState(true);

  const formRef = useRef(null);
  const emailRef = useRef(null);
  const passwordRef = useRef(null);

  const validate = useCallback(
    (values) => ({
      email: validateEmail(values.email),
      password: validatePassword(values.password),
    }),
    [],
  );

  const submit = useCallback(
    (values) => signIn({ email: values.email, password: values.password, remember }),
    [signIn, remember],
  );

  const handleValueChange = useCallback(
    (name, value) => {
      if (name === 'email') onEmailChange(value);
    },
    [onEmailChange],
  );

  const form = useAuthForm({
    initialValues: { email, password: '' },
    validate,
    onSubmit: submit,
    onValueChange: handleValueChange,
    formRef,
  });

  /* Land the cursor on the first thing still to fill in — which is the
     password when the email came across from the other tab.

     Only on a pointer-sized screen: focusing an input on mount opens the
     on-screen keyboard on a phone, which covers the form the person has not
     read yet. */
  useEffect(() => {
    if (!window.matchMedia('(min-width: 768px)').matches) return;

    /* Read the email out of the input rather than out of state, so this effect
       depends on nothing and genuinely runs once: it is about where the cursor
       starts, and re-running it later would yank focus mid-typing. */
    const target = emailRef.current?.value ? passwordRef : emailRef;
    target.current?.focus();
  }, []);

  return (
    <form ref={formRef} className="auth-form" onSubmit={form.handleSubmit} noValidate>
      {form.formError ? (
        /*
          Keyed by attempt, which does two jobs at once. React remounts the
          banner on every rejection — so the shake replays and a screen reader
          announces it again — even when the message is identical to last
          time. Without that, a second failed attempt looks like a button that
          did not fire.
        */
        <Alert
          key={form.failureCount}
          tone="danger"
          onDismiss={form.dismissFormError}
          className="auth-form__banner a-shake"
        >
          {form.formError}
        </Alert>
      ) : null}

      <div className="auth-form__fields">
        <TextField
          {...form.field('email')}
          inputRef={emailRef}
          label="Email"
          type="email"
          icon="mail"
          autoComplete="username"
          placeholder="you@arihantcapital.com"
          spellCheck="false"
          autoCapitalize="none"
          /* `noValidate` on the form turns off the browser's own bubbles, and
             this keeps its heuristics from second-guessing ours. */
          inputMode="email"
        />

        <PasswordField
          {...form.field('password')}
          inputRef={passwordRef}
          label="Password"
          autoComplete="current-password"
        />
      </div>

      <div className="auth-form__row">
        <Checkbox
          name="remember"
          label="Keep me signed in"
          checked={remember}
          onChange={(event) => setRemember(event.target.checked)}
        />
      </div>

      <Button
        type="submit"
        size="lg"
        fullWidth
        iconEnd="arrowRight"
        loading={form.submitting}
        loadingLabel="Signing in…"
      >
        Sign in
      </Button>

      <p className="auth-form__foot">
        No account yet?{' '}
        <button type="button" className="auth-form__link" onClick={onNeedAccount}>
          Create one
        </button>
      </p>

      {/*
        Told plainly, because the alternative is a "Forgot password?" link that
        goes nowhere: there is no self-service reset in this backend. A
        password change is `python auth.py password <email>`, run by whoever
        administers the deployment.
      */}
      <p className="auth-form__note">
        Lost your password? It can only be reset by an administrator — there is no
        self-service reset yet.
      </p>
    </form>
  );
}
