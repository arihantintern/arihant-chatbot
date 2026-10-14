"""who is asking: accounts, passwords, tokens, roles.

One collection, `users`, and it is the "one" side of the one-to-many that
history.py writes the other half of. A conversation carries the `_id` of the
account that opened it, and so does every message in it -- see `history.Session`.

Three things live here and nothing else does:

  accounts   `register` and `authenticate`. Passwords are bcrypt hashes and the
             plaintext is never written anywhere, not to mongodb and not to a log.
  tokens     a signed JWT saying "this is user X, until this time". Stateless on
             purpose: verifying one is a signature check, not a database round
             trip in front of every question.
  roles      "user" reads its own chats, "admin" reads everyone's. The check is
             `require_admin`, and it is the only thing standing between a support
             query and somebody else's transcript.

Unlike history.py, this module is *not* allowed to fail quietly. A chat that goes
unlogged is a lost note; an authentication that fails open is an account takeover.
Every function in here raises `AuthError` rather than returning something falsy
that a caller might read as success.

    python auth.py add <email> [--admin]     make an account, prompting for the password
    python auth.py list                      the accounts
    python auth.py role <email> <role>       promote or demote
    python auth.py disable <email>           revoke access, keep the history
"""
from __future__ import annotations

import getpass
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import jwt

import history
from config import (
    BCRYPT_ROUNDS, JWT_ALGORITHM, JWT_SECRET, JWT_TTL_MIN, PASSWORD_MIN_LEN, ROLES,
)
from history import USERS   # history owns the collection names; see the note there

# rfc 5322 in full is a monster nobody needs. This rejects the shapes that are
# obviously not an address; the address being *deliverable* is a different question
# and not one a regex gets to answer.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

# bcrypt hashes the first 72 bytes and silently ignores the rest, which would make
# two different long passwords the same password. Rejecting is honest; truncating is
# a security bug that only shows up for people using a password manager.
_MAX_PASSWORD_BYTES = 72


class AuthError(Exception):
    """bad credentials, bad token, bad request. Carries an http status so api.py
    does not have to keep a second table mapping these back to codes."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message, self.status = message, status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def users():
    """the users collection, or None when there is no mongodb.

    Shares history.py's client and its one-warning-then-off behaviour, because two
    connections to the same cluster for the same process is one too many.
    """
    database = history.db()
    return None if database is None else database[USERS]


def _collection():
    """the users collection or a refusal. Everything that authenticates goes through
    this rather than through `users()`: with no database there are no accounts, and
    "no accounts" must not read as "no password needed"."""
    collection = users()
    if collection is None:
        raise AuthError("accounts are unavailable -- no mongodb to read them from", 503)
    return collection


# ------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False        # a malformed hash in the database is not a valid password


def _check_password(password: str) -> None:
    if len(password) < PASSWORD_MIN_LEN:
        raise AuthError(f"password must be at least {PASSWORD_MIN_LEN} characters")
    if len(password.encode()) > _MAX_PASSWORD_BYTES:
        raise AuthError(f"password must be at most {_MAX_PASSWORD_BYTES} bytes")


def _check_email(email: str) -> str:
    email = (email or "").strip().lower()   # stored lowercase: nobody means to make
    if not _EMAIL.match(email):             # two accounts out of one capital letter
        raise AuthError("that is not an email address")
    return email


# -------------------------------------------------------------------- accounts
def register(email: str, password: str, name: str | None = None,
             role: str = "user") -> dict:
    """a new account. Raises if the email is taken or the password is too short.

    Returns the *public* shape -- `id`, not `_id`, and no hash. `authenticate`,
    `by_id`, `login` and `me` return the raw document instead, because their callers
    hand it to `history.Session.for_user`, which wants `_id`. Passing this return
    value there is a KeyError rather than a silent mis-attribution, which is the
    right way round for a mistake like that to fail.
    """
    email = _check_email(email)
    _check_password(password)
    if role not in ROLES:
        raise AuthError(f"role must be one of {', '.join(ROLES)}")

    user = {"_id": uuid.uuid4().hex, "email": email,
            "name": (name or email.split("@")[0]).strip(),
            "password_hash": hash_password(password), "role": role,
            "created_at": _now(), "last_login_at": None, "disabled": False}
    try:
        _collection().insert_one(user)
    except Exception as e:
        # the unique index on email is what makes this a race-proof check rather
        # than a find-then-insert with a gap in the middle
        if "duplicate key" in str(e).lower():
            raise AuthError("that email already has an account", 409) from e
        raise AuthError(f"could not create the account: {type(e).__name__}", 503) from e
    return public(user)


def authenticate(email: str, password: str) -> dict:
    """the account, or AuthError. The same message for an unknown email and a wrong
    password, deliberately: telling them apart turns the login form into a way to
    find out who has an account here."""
    email = _check_email(email)
    user = _collection().find_one({"email": email})
    if user is None or not verify_password(password, user.get("password_hash", "")):
        raise AuthError("wrong email or password", 401)
    if user.get("disabled"):
        raise AuthError("this account is disabled", 403)
    _collection().update_one({"_id": user["_id"]}, {"$set": {"last_login_at": _now()}})
    return user


def by_id(user_id: str) -> dict:
    """the account a token names. Checked on every request, so a disabled account
    stops working now rather than whenever its token happens to expire."""
    user = _collection().find_one({"_id": user_id})
    if user is None:
        raise AuthError("this account no longer exists", 401)
    if user.get("disabled"):
        raise AuthError("this account is disabled", 403)
    return user


def set_password(email: str, password: str) -> None:
    _check_password(password)
    email = _check_email(email)
    if _collection().update_one({"email": email},
                                {"$set": {"password_hash": hash_password(password)}}
                                ).matched_count == 0:
        raise AuthError("no account with that email", 404)


def set_role(email: str, role: str) -> None:
    if role not in ROLES:
        raise AuthError(f"role must be one of {', '.join(ROLES)}")
    if _collection().update_one({"email": _check_email(email)},
                                {"$set": {"role": role}}).matched_count == 0:
        raise AuthError("no account with that email", 404)


def set_disabled(email: str, disabled: bool = True) -> None:
    """revoke access without deleting anything. The history stays owned by the
    account -- deleting the user would orphan every conversation it opened."""
    if _collection().update_one({"email": _check_email(email)},
                                {"$set": {"disabled": disabled}}).matched_count == 0:
        raise AuthError("no account with that email", 404)


def public(user: dict) -> dict:
    """the account as anything outside this module is allowed to see it. The hash
    never leaves here: this is the function that makes forgetting to strip it in an
    api response impossible rather than merely unlikely."""
    return {"id": user["_id"], "email": user["email"], "name": user.get("name", ""),
            "role": user.get("role", "user"),
            "created_at": user.get("created_at"),
            "last_login_at": user.get("last_login_at")}


def everyone(limit: int = 100) -> list[dict]:
    collection = users()
    return [public(u) for u in collection.find().sort("created_at", 1).limit(limit)] \
        if collection is not None else []


# ---------------------------------------------------------------------- tokens
def issue_token(user: dict) -> tuple[str, int]:
    """(token, seconds until it expires).

    `sub` is the account id and not the email, so changing an email later does not
    orphan the conversations that id owns.
    """
    expires_in = JWT_TTL_MIN * 60
    now = _now()
    payload = {"sub": user["_id"], "email": user["email"],
               "role": user.get("role", "user"),
               "iat": now, "exp": now + timedelta(seconds=expires_in)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM), expires_in


def read_token(token: str) -> dict:
    """the payload of a token that is genuinely ours, or AuthError.

    `algorithms` is pinned to the one we sign with. Left open, a token arriving with
    `"alg": "none"` is a valid unsigned token and anyone can be an admin.
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise AuthError("this session has expired -- log in again", 401) from e
    except jwt.InvalidTokenError as e:
        raise AuthError("invalid token", 401) from e


def user_for_token(token: str) -> dict:
    """token -> the account behind it. The role comes from the database and not from
    the token: a demotion should take effect immediately, and the copy in the token
    is only there to save a lookup for callers that never needed one."""
    return by_id(read_token(token).get("sub") or "")


def require_admin(user: dict) -> dict:
    if user.get("role") != "admin":
        raise AuthError("this needs an admin account", 403)
    return user


# ------------------------------------------------- staying logged in on a terminal
# The api hands its token to a browser and the browser keeps it. A terminal has
# nowhere to keep one between two `python cli.py` runs, so it goes in a file under
# the home directory -- not in the project, which is a git checkout somebody will
# eventually commit.
TOKEN_FILE = Path.home() / ".abot" / "token"


def cache_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)     # owner only. A no-op on windows, where the
    except OSError:                 # per-user home directory is the protection
        pass


def cached_token() -> str | None:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def forget_token() -> None:
    TOKEN_FILE.unlink(missing_ok=True)


def me() -> dict | None:
    """the account a terminal is logged in as, or None. Never raises: not being
    logged in is an ordinary state for a cli, and the caller decides whether it
    matters. An expired or tampered token reads the same as no token, and the stale
    file is cleared so the next run does not check it again."""
    token = cached_token()
    if not token:
        return None
    try:
        return user_for_token(token)
    except AuthError:
        forget_token()
        return None


def login(email: str, password: str) -> dict:
    """authenticate and remember it. Returns the account."""
    user = authenticate(email, password)
    cache_token(issue_token(user)[0])
    return user


# ------------------------------------------------------------------- the cli
def _ask_secret(prompt: str, visible: bool = False) -> str:
    """one password, hidden by default and echoed when hiding it does not work.

    On windows `getpass` does not read stdin -- it reads the console device through
    `msvcrt.getwch()`. Inside a pseudo-terminal that is not a real win32 console
    (vscode's integrated terminal is the common one) those keystrokes never arrive
    and it blocks forever without raising, so there is nothing to catch and no
    timeout: the prompt just sits there looking like a hung program while you type.

    Hence `--visible`, which skips getpass entirely and uses `input()`. The password
    is echoed on screen, which is a real cost and a smaller one than not being able
    to make an account. It stays out of the shell history either way, which is the
    part that actually persists -- unlike passing it as an argument.
    """
    if visible:
        secret = input(prompt)
        print("\033[1A\033[2K", end="")   # scrub the echoed line back off the screen
        print(f"{prompt}{'*' * len(secret)}")
        return secret
    try:
        return getpass.getpass(prompt)
    except (getpass.GetPassWarning, EOFError, OSError):
        print("  (this terminal cannot hide input -- what you type will be visible)")
        return input(prompt)


def _prompt_password(visible: bool = False) -> str:
    first = _ask_secret("password: ", visible)
    if not first.strip():
        raise AuthError("no password was entered")
    if first != _ask_secret("again: ", visible):
        raise AuthError("those did not match")
    return first


def _main(args: list[str]) -> int:
    what = args[0] if args else "list"
    # --visible for terminals where the hidden prompt reads nothing; see _ask_secret
    visible = "--visible" in args
    args = [a for a in args if a != "--visible"]
    try:
        if what == "add":
            if not args[1:]:
                print("usage: python auth.py add <email> [--admin] [--visible]")
                return 2
            role = "admin" if "--admin" in args else "user"
            user = register(args[1], _prompt_password(visible), role=role)
            print(f"  created {user['email']} ({user['role']})")
        elif what == "list":
            rows = everyone()
            if not rows:
                print("no accounts yet -- python auth.py add <email> --admin")
                return 0
            for u in rows:
                seen = u["last_login_at"].strftime("%d %b %H:%M") \
                    if isinstance(u["last_login_at"], datetime) else "never"
                print(f"  {u['email']:<34} {u['role']:<6} last login {seen}")
        elif what == "role" and len(args) > 2:
            set_role(args[1], args[2])
            print(f"  {args[1]} is now {args[2]}")
        elif what == "password" and len(args) > 1:
            set_password(args[1], _prompt_password(visible))
            print(f"  password changed for {args[1]}")
        elif what in ("disable", "enable") and len(args) > 1:
            set_disabled(args[1], what == "disable")
            print(f"  {args[1]} {what}d")
        else:
            print(__doc__)
            return 2
    except AuthError as e:
        print(f"  [auth] {e.message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
