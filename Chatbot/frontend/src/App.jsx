import { AppShell } from '@/app/AppShell';
import { AuthGate } from '@/app/AuthGate';
import { ChatProvider } from '@/context/chat';

/**
 * The app, in one sentence: everything the product does lives behind the gate.
 *
 * There is still no router, and still none is needed — the app has two states,
 * signed out and signed in, and the conversation is not a place you navigate
 * to but the thing that is there once you are in.
 *
 * The chat provider sits *inside* the gate on purpose, and that placement is
 * the whole of the app's session hygiene: signing out unmounts this subtree,
 * so the conversation, the history list and every in-flight request go with
 * it. There is no cleanup to remember, because there is nothing left to clean.
 */
export default function App() {
  return (
    <AuthGate>
      <ChatProvider>
        <AppShell />
      </ChatProvider>
    </AuthGate>
  );
}
