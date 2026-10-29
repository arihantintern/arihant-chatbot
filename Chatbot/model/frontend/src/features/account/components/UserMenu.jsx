import './UserMenu.css';

import { useCallback, useEffect, useRef, useState } from 'react';

import { ThemeToggle } from '@/components/theme';
import { Avatar, Icon } from '@/components/ui';
import { useAuth } from '@/context/auth';
import { useClickOutside } from '@/hooks/useClickOutside';

import { SignOutDialog } from './SignOutDialog';

/**
 * Who you are signed in as, and the way out.
 *
 * Deliberately *not* ARIA menu semantics. `role="menu"` promises that every
 * child is a `menuitem` navigated with arrow keys — and this panel contains a
 * radio group (the theme switcher), which would then be unreachable in the
 * way its own role documents. A disclosure (`aria-expanded` on the trigger, a
 * labelled group as the panel) describes what this actually is, and Tab
 * behaves the way people expect inside it.
 *
 * Closes on Escape, on a press outside, and when focus leaves the panel
 * entirely — the last one is what stops a tab-away leaving it hanging open
 * behind whatever the person moved on to.
 */
export function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const wrapperRef = useRef(null);
  const triggerRef = useRef(null);
  const panelRef = useRef(null);

  const close = useCallback(({ restoreFocus = false } = {}) => {
    setOpen(false);
    /* Returning focus is right when the person dismissed the panel (Escape,
       or picking something in it) and wrong when they left by clicking
       elsewhere — that would yank focus back from wherever they went. */
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useClickOutside(wrapperRef, () => close(), open);

  /* Move focus into the panel when it opens — onto the panel itself, not onto
     its first button. Landing on "Sign out" would make Enter, pressed by
     someone who was still deciding, sign them out. */
  useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);

  const onKeyDown = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      close({ restoreFocus: true });
    }
    /* Down-arrow on the trigger opens it, which is what a disclosure holding
       a list of things is expected to do. */
    if (event.key === 'ArrowDown' && !open && event.target === triggerRef.current) {
      event.preventDefault();
      setOpen(true);
    }
  };

  const onBlurWithin = (event) => {
    // relatedTarget is where focus went; null means it left the document.
    if (!open) return;
    if (event.currentTarget.contains(event.relatedTarget)) return;
    setOpen(false);
  };

  return (
    <>
      <div className="user-menu" ref={wrapperRef} onKeyDown={onKeyDown} onBlur={onBlurWithin}>
        <button
          ref={triggerRef}
          type="button"
          className="user-menu__trigger"
          aria-expanded={open}
          aria-haspopup="true"
          onClick={() => setOpen((current) => !current)}
        >
          <Avatar name={user.name} seed={user.id} size="sm" />

          <span className="user-menu__identity">
            <span className="user-menu__name u-truncate">{user.name}</span>
            <span className="user-menu__email u-truncate">{user.email}</span>
          </span>

          <Icon name="chevronDown" size="sm" className="user-menu__chevron" />
        </button>

        {open ? (
          <div
            ref={panelRef}
            className="user-menu__panel a-scale-in"
            /* Focusable so it can receive focus on open, but not a tab stop —
               Tab from here goes to the first control inside. */
            tabIndex={-1}
            role="group"
            aria-label="Account"
          >
            <div className="user-menu__header">
              <Avatar name={user.name} seed={user.id} size="md" />
              <div className="user-menu__header-text">
                <p className="user-menu__header-name u-truncate">{user.name}</p>
                <p className="user-menu__header-email u-truncate">{user.email}</p>
              </div>
            </div>

            <p className="user-menu__badges">
              <span className="user-menu__badge" data-role={user.role}>
                {user.role === 'admin' ? 'Administrator' : 'Standard access'}
              </span>
              {user.lastLoginAt ? (
                <span className="user-menu__meta">Last signed in {when(user.lastLoginAt)}</span>
              ) : null}
            </p>

            <div className="u-divider" role="presentation" />

            <div className="user-menu__row">
              <span className="user-menu__row-label">Appearance</span>
              <ThemeToggle size="sm" />
            </div>

            <div className="u-divider" role="presentation" />

            <button
              type="button"
              className="user-menu__action user-menu__action--danger"
              onClick={() => {
                close({ restoreFocus: true });
                setConfirming(true);
              }}
            >
              <Icon name="logOut" size="sm" />
              Sign out
            </button>
          </div>
        ) : null}
      </div>

      <SignOutDialog
        open={confirming}
        user={user}
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false);
          signOut();
        }}
      />
    </>
  );
}

/**
 * "today at 09:14", "yesterday at 18:02", "12 Aug at 09:14".
 *
 * Relative for the two days people actually reason about relatively, and a
 * plain date beyond that — "5 days ago" is harder to place than "15 Aug".
 */
function when(date) {
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const days = daysBetween(date, new Date());

  if (days === 0) return `today at ${time}`;
  if (days === 1) return `yesterday at ${time}`;

  return `${date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} at ${time}`;
}

/** Whole calendar days apart — not 24-hour blocks, which would call 11pm
    last night "0 days ago" at 1am. */
function daysBetween(from, to) {
  const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return Math.round((startOfDay(to) - startOfDay(from)) / 86_400_000);
}
