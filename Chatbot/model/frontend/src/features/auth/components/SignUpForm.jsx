import './AuthForm.css';

import { useCallback, useEffect, useRef, useState } from 'react';

import { Alert, Button, Checkbox, PasswordField, TextField } from '@/components/ui';
import { useAuth } from '@/context/auth';

import { useAuthForm } from '../hooks/useAuthForm';
import { PasswordStrength } from './PasswordStrength';
import {
  NAME_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  validateConfirmation,
  validateEmail,
  validateName,
  validatePassword,
} from '../validation';

/**
 * Create an account, and be signed in by it.
 *
 * `POST /auth/register` returns a token as well as creating the account, so
 * there is no second step and no moment where the account exists while the
 * person is still looking at a form. Registering *is* signing in.
 *
 * The confirmation field is ours, not the backend's. It exists because a
 * mistyped password on a service with no self-service reset is not an
 * inconvenience, it is a lost account — the fix is a CLI command run by
 * somebody else.
 */
export function SignUpForm({ email, onEmailChange, onHaveAccount }) {
  const { signUp } = useAuth();
  const [remember, setRemember] = useState(true);

  const formRef = useRef(null);
  const nameRef = useRef(null);

  const validate = useCallback(
    (values) => ({
      name: validateName(values.name),
      email: validateEmail(values.email),
      password: validatePassword(values.password, { isNew: true }),
      confirmation: validateConfirmation(values.password, values.confirmation),
    }),
    [],
  );

  const submit = useCallback(
    async (values) => {
      try {
        await signUp({
          name: values.name,
          email: values.email,
          password: values.password,
          remember,
        });
      } catch (error) {
        /* "That email already has an account" is a fact about one field, and
           the backend can only send it as a whole-form message (409, a string
           detail). Re-aiming it at the email input puts it where the person
           is looking, and frees the banner to say the useful part — that the
           way out of this is to sign in. */
        if (error?.status === 409) {
          error.fieldErrors = { email: error.message };
          error.message = 'That account already exists. Sign in instead.';
        }
        throw error;
      }
    },
    [signUp, remember],
  );

  const handleValueChange = useCallback(
    (name, value) => {
      if (name === 'email') onEmailChange(value);
    },
    [onEmailChange],
  );

  const form = useAuthForm({
    initialValues: { name: '', email, password: '', confirmation: '' },
    validate,
    onSubmit: submit,
    onValueChange: handleValueChange,
    formRef,
  });

  /* Mount only. Focusing on a pointer-sized screen just puts the cursor where
     the person was going to click anyway; on a phone it would open the
     keyboard over the form before they have read it. */
  useEffect(() => {
    if (window.matchMedia('(min-width: 768px)').matches) nameRef.current?.focus();
  }, []);

  return (
    <form ref={formRef} className="auth-form" onSubmit={form.handleSubmit} noValidate>
      {form.formError ? (
        /* Keyed by attempt: a second identical failure still has to move and
           still has to be announced. See SignInForm for the full note. */
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
          {...form.field('name')}
          inputRef={nameRef}
          label="Name"
          icon="user"
          autoComplete="name"
          placeholder="How you should be greeted"
          maxLength={NAME_MAX_LENGTH}
          optional
          hint="Left blank, we use the first part of your email."
        />

        <TextField
          {...form.field('email')}
          label="Work email"
          type="email"
          icon="mail"
          autoComplete="username"
          placeholder="you@arihantcapital.com"
          spellCheck="false"
          autoCapitalize="none"
          inputMode="email"
        />

        <div className="auth-form__field-group">
          <PasswordField
            {...form.field('password')}
            label="Password"
            autoComplete="new-password"
            hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          />
          <PasswordStrength password={form.values.password} />
        </div>

        <PasswordField
          {...form.field('confirmation')}
          label="Confirm password"
          autoComplete="new-password"
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
        loadingLabel="Creating your account…"
      >
        Create account
      </Button>

      <p className="auth-form__foot">
        Already have an account?{' '}
        <button type="button" className="auth-form__link" onClick={onHaveAccount}>
          Sign in
        </button>
      </p>

      <p className="auth-form__note">
        Your questions and the assistant’s answers are saved to your account, so you can
        search them later. New accounts get standard access.
      </p>
    </form>
  );
}
