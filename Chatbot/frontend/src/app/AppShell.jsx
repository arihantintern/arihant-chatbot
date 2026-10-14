import './AppShell.css';

import { Logo } from '@/components/brand';
import { ChatScreen } from '@/features/chat';
import { UserMenu } from '@/features/account';

/**
 * The signed-in shell: the top bar, and the product under it.
 *
 * The one structural job this has is the height. It is `100dvh` split into a
 * fixed bar and a `<main>` that takes the rest — and `<main>` has
 * `min-block-size: 0`, which is what lets the conversation inside it scroll
 * rather than growing the document. Everything else about the layout belongs
 * to the chat screen.
 *
 * `dvh` and not `vh`: on mobile browsers `vh` is the height with the address
 * bar hidden, so a `100vh` shell has its last 60 pixels permanently under the
 * chrome — which here would be the composer.
 */
export function AppShell() {
  return (
    <div className="shell">
      <header className="shell__bar">
        <div className="shell__brand">
          <Logo variant="lockup" height={26} />
          <span className="shell__divider" aria-hidden="true" />
          <span className="shell__tag">Research assistant</span>
        </div>

        <span className="u-spacer" />

        <UserMenu />
      </header>

      <main className="shell__main">
        <ChatScreen />
      </main>
    </div>
  );
}
