"""ask it things.

    python cli.py login           who you are, remembered until /logout
    python cli.py                 interactive
    python cli.py "what is X"     one question and out

/graph draws the pipeline, /quiet hides the working, /history lists what *you* have
asked, /show brings a conversation back, /whoami says who you are, /bye leaves.

Logging in is optional and the bot answers either way. What it buys is a chat history
with your name on it: an anonymous run still gets saved, but with no owner, and an
unowned conversation is one only an admin can read back. There is nothing secret in
this file -- the login exists so that /history means "mine" instead of "everyone's".
"""
import sys

import auth
import history


def _login(visible: bool = False) -> int:
    """prompt, authenticate, cache the token. Its own subcommand rather than a
    prompt on startup, because most runs are already logged in and being asked for a
    password before every question is how people end up not using it.

    `--visible` echoes the password. Needed in terminals where the hidden prompt
    reads nothing at all and blocks -- see auth._ask_secret for why that happens.
    """
    email = input("email: ").strip()
    try:
        user = auth.login(email, auth._ask_secret("password: ", visible))
    except auth.AuthError as e:
        print(f"  [auth] {e.message}")
        return 1
    print(f"  logged in as {user['email']} ({user.get('role', 'user')})")
    return 0


def _session_for(account: dict | None) -> history.Session:
    """one conversation per run, so a whole sitting reads back as one chat rather
    than as a pile of unrelated turns."""
    return history.Session.for_user(account, interface="cli") if account \
        else history.Session(interface="cli")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "login":
        raise SystemExit(_login("--visible" in args))
    if args and args[0] == "logout":
        auth.forget_token()
        print("  logged out")
        return

    account = auth.me()          # None when nobody has logged in on this machine

    print("loading the index and the models ...", flush=True)
    from chain import ask, show_graph   # late, so the banner prints before ollama warms

    session = _session_for(account)

    if args:
        ask(" ".join(args), session=session)
        return

    who = account["email"] if account else "not logged in -- python cli.py login"
    print(f"\n{who}")
    print("ask a question. /graph draws the pipeline, /bye leaves.\n")
    show = True

    while True:
        try:
            question = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not question:
            continue
        if question in ("/bye", "/quit", "/exit"):
            return
        if question in ("/quiet", "/show"):
            show = question == "/show"
            print(f"  (working {'shown' if show else 'hidden'})")
            continue
        if question == "/whoami":
            print(f"  {account['email']} ({account['role']})" if account
                  else "  nobody -- python cli.py login")
            continue
        if question == "/logout":
            auth.forget_token()
            account = None
            # a fresh conversation, and an unowned one. Carrying the old session on
            # would keep stamping the account that just logged out onto new turns --
            # the token is gone but `session.user_id` would not be
            session = _session_for(None)
            print("  logged out -- starting a fresh, unattributed conversation")
            continue
        if question == "/graph":
            show_graph()
            continue
        if question.split()[0] in ("/history", "/log"):
            # bare -> your recent conversations, with an id -> that transcript. Both
            # scoped to you: the team-wide view is an admin route now, see api.py.
            if account is None:
                print("  log in to read your history -- python cli.py login")
                print()
                continue
            rest = question.split(maxsplit=1)[1:]
            owner, is_admin = account["_id"], account.get("role") == "admin"
            (history.print_transcript(rest[0], owner=owner, admin=False) if rest
             else history.print_recent(owner=owner, admin=False))
            if is_admin:
                print("  (admin: python history.py --all  for everyone's)")
            print()
            continue

        try:
            ask(question, show_working=show, session=session)
        except Exception as e:        # a bad answer should not end the session
            print(f"  [failed] {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    main()
