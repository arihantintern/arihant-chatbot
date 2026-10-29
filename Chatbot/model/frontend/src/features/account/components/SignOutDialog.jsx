import './SignOutDialog.css';

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

import { Button } from '@/components/ui';

/**
 * "Sign out?" — asked, rather than done on the first click.
 *
 * Signing out is cheap to undo *if you know your password*, and this app has
 * no self-service reset. It is also one click away from an avatar people
 * click for other reasons. One confirmation is the right trade.
 *
 * Built on the native `<dialog>`, which brings the parts that are tedious and
 * easy to get wrong: a real modal backdrop, focus moved into the dialog and
 * restored on close, focus trapped while open, Escape to dismiss, and the
 * rest of the page marked inert. base/elements.css already styles
 * `::backdrop`.
 *
 * Rendered into `<body>` through a portal, and that is not decoration. It is
 * declared by the account menu, which lives in a top bar with a
 * `backdrop-filter` on it — and any filtered ancestor becomes the containing
 * block for `position: fixed` descendants. Left in place, this modal would be
 * centred inside the 64px-tall bar rather than in the viewport.
 *
 * @param {object} props
 * @param {boolean} props.open
 * @param {import('@/api/auth.api').User} props.user
 * @param {() => void} props.onCancel
 * @param {() => void} props.onConfirm
 */
export function SignOutDialog({ open, user, onCancel, onConfirm }) {
  const dialogRef = useRef(null);

  /* `open` as an attribute would show the dialog non-modally — no backdrop,
     no focus trap, the page behind it still interactive. `showModal()` is the
     only way to get the modal behaviour, so the prop drives the method. */
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return createPortal(
    <dialog
      ref={dialogRef}
      className="signout-dialog"
      aria-labelledby="signout-title"
      aria-describedby="signout-body"
      /* Escape fires `cancel` and then closes the dialog on its own; without
         telling React, the state would still say open and the next click on
         the menu item would do nothing. */
      onCancel={onCancel}
      onClose={onCancel}
      /* A click on the backdrop lands on the dialog element itself, never on
         its contents — which is what makes this a reliable dismiss. */
      onClick={(event) => {
        if (event.target === dialogRef.current) onCancel();
      }}
    >
      <div className="signout-dialog__panel">
        <h2 id="signout-title" className="t-h3">
          Sign out?
        </h2>

        <p id="signout-body" className="signout-dialog__body">
          You will need your email and password to sign back in as{' '}
          <strong>{user?.email}</strong>. Your conversations stay saved to your account.
        </p>

        <div className="signout-dialog__actions">
          <Button variant="secondary" onClick={onCancel}>
            Stay signed in
          </Button>
          <Button variant="danger" iconStart="logOut" onClick={onConfirm}>
            Sign out
          </Button>
        </div>
      </div>
    </dialog>,
    document.body,
  );
}
