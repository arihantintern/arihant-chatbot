import { useCallback, useState } from 'react';

/**
 * The form machinery both auth forms share: values, when to show an error,
 * submitting, and what to do with what the API sends back.
 *
 * WHEN ERRORS APPEAR — the whole reason this is a hook and not two copies of
 * `useState`. Validating on every keystroke tells someone their email is
 * invalid when they have typed "k", which is true and useless. Validating
 * only on submit makes them hunt for what went wrong after the fact. So:
 *
 *   · while a field is untouched — say nothing
 *   · on blur — check it, and say so
 *   · once it has been checked — re-check on every keystroke, so the message
 *     disappears the instant it stops being true
 *
 * @param {object} options
 * @param {Record<string, string>} options.initialValues
 * @param {(values: Record<string, string>) => Record<string, string|null>} options.validate
 *   All fields at once; returns a message per invalid field.
 * @param {(values: Record<string, string>) => Promise<void>} options.onSubmit
 *   Rejecting with an `ApiError` is expected — its message becomes the form's
 *   banner and its `fieldErrors` land under the right inputs.
 * @param {(name: string, value: string) => void} [options.onValueChange]
 *   Notified on every edit. AuthScreen uses it to keep the typed email when
 *   the person switches between signing in and signing up.
 * @param {import('react').RefObject<HTMLFormElement>} options.formRef
 *   The caller's ref on its `<form>`. Passed *in* rather than handed back,
 *   deliberately: a hook that returns a ref makes every read of its result an
 *   ambiguous "is this a ref?" for React's compiler, and the component needs
 *   the ref on its own element anyway.
 */
export function useAuthForm({
  initialValues,
  validate,
  onSubmit,
  onValueChange,
  formRef,
}) {
  const [values, setValues] = useState(initialValues);
  const [touched, setTouched] = useState({});
  const [clientErrors, setClientErrors] = useState({});
  const [serverErrors, setServerErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  /* Bumped on every rejected submit. The form uses it to replay its shake and
     re-announce the banner — a second identical failure has to be visible, or
     it looks like the button did nothing at all. */
  const [failureCount, setFailureCount] = useState(0);

  const setValue = useCallback(
    (name, value) => {
      const next = { ...values, [name]: value };
      setValues(next);

      /* Re-check a field that has already been shown an error, so the message
         clears as soon as it is fixed rather than at the next blur. Fields
         that have never been touched stay silent. */
      setClientErrors((errors) =>
        errors[name] ? { ...errors, [name]: validate(next)[name] ?? null } : errors,
      );

      /* The server's opinion was about the old value. Typing invalidates it —
         keeping "that email already has an account" under a half-edited
         address is just wrong. */
      setServerErrors((errors) => (errors[name] ? { ...errors, [name]: null } : errors));

      onValueChange?.(name, value);
    },
    [values, validate, onValueChange],
  );

  const handleBlur = useCallback(
    (event) => {
      const { name } = event.target;
      setTouched((current) => ({ ...current, [name]: true }));
      setClientErrors((errors) => ({ ...errors, [name]: validate(values)[name] ?? null }));
    },
    [validate, values],
  );

  /** Everything an input needs, so a form body stays readable. */
  const field = useCallback(
    (name) => ({
      name,
      value: values[name],
      onChange: (event) => setValue(name, event.target.value),
      onBlur: handleBlur,
      error: (touched[name] ? clientErrors[name] : null) || serverErrors[name] || undefined,
    }),
    [values, setValue, handleBlur, touched, clientErrors, serverErrors],
  );

  const handleSubmit = useCallback(
    async (event) => {
      event.preventDefault();
      if (submitting) return;

      const found = validate(values);
      const invalid = Object.keys(found).filter((name) => found[name]);

      if (invalid.length > 0) {
        /* Everything is now "touched": pressing submit is a request to be
           told about all of it, not just the field the cursor last sat in. */
        setTouched(Object.fromEntries(Object.keys(values).map((name) => [name, true])));
        setClientErrors(found);
        setFailureCount((count) => count + 1);

        /* Put the cursor on the first problem. `form.elements` is a live
           collection keyed by input name, so this needs no refs and no wait
           for a re-render. */
        formRef?.current?.elements?.[invalid[0]]?.focus();
        return;
      }

      setSubmitting(true);
      setFormError(null);
      setServerErrors({});

      try {
        await onSubmit(values);
        /* Deliberately no success state: a successful sign-in unmounts this
           whole form, and setting state on the way out is how you get a
           warning about updating an unmounted component. */
      } catch (error) {
        setFormError(error?.message || 'Something went wrong. Try again.');
        setFailureCount((count) => count + 1);

        const fields = error?.fieldErrors ?? {};
        if (Object.keys(fields).length > 0) {
          setServerErrors(fields);
          setTouched((current) => ({ ...current, ...mapToTrue(fields) }));
          formRef?.current?.elements?.[Object.keys(fields)[0]]?.focus();
        }

        setSubmitting(false);
      }
    },
    [submitting, validate, values, onSubmit, formRef],
  );

  const dismissFormError = useCallback(() => setFormError(null), []);

  return {
    values,
    field,
    submitting,
    formError,
    failureCount,
    setValue,
    handleSubmit,
    dismissFormError,
  };
}

function mapToTrue(source) {
  return Object.fromEntries(Object.keys(source).map((key) => [key, true]));
}
