"""where the conversations go: mongodb, one document per turn.

Three collections and two joins, which is the whole data model:

    users  --<  conversations  --<  messages
           1:N                 1:N

`users` lives in auth.py. `conversations` is one document per chat -- who, when,
how many turns, what the first question was -- and it is what you list. `messages`
is one document per question and answer, and it is what you search. A conversation
points at its owner with `user_id`, and so does every message in it.

The owner is on the message as well as on the conversation, which is a duplicated
field and worth the duplication: mongodb's text index cannot join, so scoping a
search to one person's turns has to be answerable from the message alone. Without
it, "find my questions about sensex" is a full scan of everybody's.

Everything the working notes print is kept beside the answer: the autocorrection,
the date filter, which chunks and which urls the answer was built from, which lane
won and how long each took. An answer with no record of where it came from is not
worth reading back later, and `source` is the field that says whether the bot was
quoting the pdfs or improvising.

Nothing in here is allowed to break a chat. No uri in .env, no network, a cluster
that has gone away mid-session -- each of those prints one line and switches the
saving off for the rest of the process. The bot exists to answer questions; losing
the log of one is not a reason to lose the answer.

That tolerance stops at the door of who-owns-what. A read without an owner does not
quietly widen to everybody's chats: the functions below take `owner` and refuse
rather than default. Losing a log is a nuisance, showing one person another
person's transcript is not.

    python history.py                      your last conversations
    python history.py <session_id>         that conversation, in full
    python history.py -f <text>            every turn of yours matching some text
    python history.py --all                everyone's, if you are an admin
"""
from __future__ import annotations

import contextvars
import getpass
import re
import socket
import sys
import uuid
from datetime import datetime, timezone

from config import (
    CHAT_MODEL, EMBED_MODEL, MONGO_DB, MONGO_TIMEOUT_MS, MONGO_URI, SMALL_MODEL,
)

CONVERSATIONS, MESSAGES, USERS = "conversations", "messages", "users"
# `users` is auth.py's collection and its indexes are created below with the rest,
# because db() is the one place that knows the connection just came up. The name
# lives here rather than there so that auth.py can import history and history never
# has to import auth -- the two of them in a cycle would be an import error at
# whichever one python happened to load first.

_db = None          # the handle, made once per process
_off = False        # set when there is no mongodb to talk to; never retried


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _who() -> str:
    try:
        return f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:
        return "unknown"


def _why(e: Exception) -> str:
    """the reason, short. A ServerSelectionTimeoutError carries the whole topology
    description with it, which is a paragraph of pymongo internals in the middle of
    a chat -- the first clause of it is the part that says what to fix."""
    return f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"


def db():
    """the database, or None if there is not one. Connects on first use.

    pymongo connects lazily and would raise on the first *write* instead, which is
    the worst possible moment, so the ping happens here and the failure is spent
    once. The indexes are created in the same breath: they are idempotent, and the
    alternative is a setup script somebody forgets to run.
    """
    global _db, _off
    if _db is not None or _off:
        return _db
    if not MONGO_URI:
        _off = True
        print("  [history] no MONGODB_URI in .env -- this chat is not being saved")
        return None
    try:
        from pymongo import ASCENDING, DESCENDING, MongoClient

        client = MongoClient(MONGO_URI, appname="abot",
                             serverSelectionTimeoutMS=MONGO_TIMEOUT_MS)
        client.admin.command("ping")
        database = client[MONGO_DB]
        # one turn per (session, seq): a retry writing the same turn twice is a bug
        # you want to hear about as a duplicate key, not as a doubled transcript.
        database[MESSAGES].create_index([("session_id", ASCENDING), ("seq", ASCENDING)],
                                        unique=True, name="session_seq")
        database[MESSAGES].create_index([("ts", DESCENDING)], name="recent")
        database[MESSAGES].create_index([("source", ASCENDING), ("ts", DESCENDING)],
                                        name="by_source")
        # one text index per collection is all mongodb allows, so it covers both
        # halves of a turn -- the team searches for what was asked and what was said.
        database[MESSAGES].create_index([("question", "text"), ("answer", "text")],
                                        name="search")
        database[CONVERSATIONS].create_index([("last_at", DESCENDING)], name="recent")
        database[CONVERSATIONS].create_index([("user", ASCENDING)], name="by_user")

        # the owner-scoped reads, which are now every read a logged-in person makes.
        # Compound and in this order: mongodb uses a prefix of an index, so
        # (user_id, last_at) serves "my conversations, newest first" from the index
        # alone and "my conversations" on its own as well. The reverse would not.
        database[CONVERSATIONS].create_index([("user_id", ASCENDING),
                                              ("last_at", DESCENDING)], name="owner")
        database[MESSAGES].create_index([("user_id", ASCENDING), ("ts", DESCENDING)],
                                        name="owner")
        # accounts. The unique index is not a nicety: it is what makes register()
        # safe against two people claiming one address at the same moment, which a
        # find-then-insert cannot be.
        database[USERS].create_index([("email", ASCENDING)], unique=True, name="email")
        _db = database
    except Exception as e:
        _off = True
        print(f"  [history] mongodb unreachable ({_why(e)}) -- "
              "this chat is not being saved")
    return _db


class Session:
    """one conversation. Held by the caller, passed to `save` on every turn.

    `user_id` is the account that owns it and the reason this class exists rather
    than a bare uuid: it is stamped on the conversation and on every message, and it
    is what every read filters by. None means nobody owns it -- the cli run by
    somebody who never logged in, and the rows written before there were accounts.
    Those stay readable by admins and by nothing else.
    """

    def __init__(self, interface: str = "cli", user: str | None = None,
                 tags: list[str] | None = None, user_id: str | None = None,
                 session_id: str | None = None, turns: int = 0) -> None:
        self.id = session_id or uuid.uuid4().hex
        self.interface = interface        # "cli", "api", whatever calls this next
        self.user_id = user_id            # the account; None -> unowned
        self.user = user or _who()        # the label that gets printed
        self.tags = tags or []
        self.started = _now()
        self.turns = turns

    @classmethod
    def for_user(cls, account: dict, interface: str = "api",
                 tags: list[str] | None = None) -> Session:
        """a new conversation belonging to an authenticated account. `account` is
        what auth.authenticate / auth.by_id hand back."""
        return cls(interface=interface, user=account["email"],
                   user_id=account["_id"], tags=tags)

    @classmethod
    def resume(cls, session_id: str, account: dict, interface: str = "api") -> Session:
        """an existing conversation, carried on. Raises PermissionError if it belongs
        to somebody else -- this is the check that stops a guessed id in a request
        body from being a way to read and then append to another person's chat.

        `turns` has to come back off the conversation row and not start at zero:
        `recent_turns` short-circuits on `turns == 0`, so a resumed chat with the
        counter reset would answer its next follow-up with no memory of the turns
        above it, and then overwrite turn 1 on the way out -- the unique index on
        (session_id, seq) would reject it.
        """
        database = db()
        if database is None:
            raise PermissionError("no mongodb -- cannot resume a conversation")
        row = database[CONVERSATIONS].find_one({"_id": session_id})
        if row is None:
            raise PermissionError("no such conversation")
        if row.get("user_id") != account["_id"]:
            raise PermissionError("that conversation belongs to somebody else")
        return cls(interface=interface, user=account["email"], user_id=account["_id"],
                   tags=row.get("tags") or [], session_id=session_id,
                   turns=int(row.get("turns") or 0))

    def _register(self, question: str, when: datetime) -> None:
        """upsert the conversation row. `$setOnInsert` for the things that are true
        once -- who started it, when, and the question that opened it."""
        database = db()
        if database is None:
            return
        database[CONVERSATIONS].update_one(
            {"_id": self.id},
            {"$setOnInsert": {"started_at": self.started, "user": self.user,
                              "user_id": self.user_id,
                              "interface": self.interface, "tags": self.tags,
                              "title": question[:120],
                              "models": {"chat": CHAT_MODEL, "small": SMALL_MODEL,
                                         "embed": EMBED_MODEL}},
             "$set": {"last_at": when},
             "$inc": {"turns": 1}},
            upsert=True)

    def save(self, question: str, out: dict | None = None, total_ms: int | None = None,
             error: str | None = None) -> str | None:
        """one turn -> one document. Returns its id, or None if nothing was saved.

        `out` is whatever `chain.ask` got back, read with `.get` throughout: a turn
        that died halfway through is still worth keeping, and it arrives here as a
        half-filled dict or as no dict at all.
        """
        database = db()
        if database is None:
            return None
        out = out or {}
        self.turns += 1
        when = _now()
        docs = out.get("docs") or []
        pages = out.get("pages") or []
        turn = {
            "_id": f"{self.id}-{self.turns:04d}",
            "session_id": self.id,
            "seq": self.turns,
            "ts": when,
            "user": self.user,
            "user_id": self.user_id,      # denormalised from the conversation, so
            #                               that a text search can be scoped -- see
            #                               the note at the top of this file

            "question": question,
            "fixed": out.get("fixed"),          # what autocorrect made of it
            "standalone": out.get("standalone"),  # and what the turns before it made
            #                                       of that, if it was a follow-up
            "answer": out.get("answer"),
            "source": out.get("source"),        # documents | web | general | ...
            "date_filter": out.get("date"),
            "chunks": [d.metadata.get("chunk_id") for d in docs],
            "pdfs": sorted({d.metadata.get("source") for d in docs} - {None}),
            "urls": [p.get("url") for p in pages],
            "timing_ms": {"doc": out.get("doc_ms"), "web": out.get("web_ms"),
                          "total": total_ms},
            "error": error,
        }
        try:
            database[MESSAGES].insert_one(turn)
            self._register(question, when)
        except Exception as e:
            global _off
            _off = True                          # one warning, then quietly off
            print(f"  [history] save failed ({_why(e)}) -- "
                  "the rest of this chat is not being saved")
            return None
        return turn["_id"]


# the session the chain resolves its follow-ups against.
#
# A ContextVar and not a module global, and that is the whole of what makes this
# safe to serve two people from one process. `chain.standalone` reaches for the
# current session without being handed one -- it is four `RunnableLambda`s deep in a
# pipeline whose input is a plain string -- and with a global it would reach into
# whichever request happened to set it last. A ContextVar is per-thread and
# per-async-task, so fastapi answering two questions at once resolves each one
# against its own asker's history. Getting this wrong does not raise; it quietly
# answers "and its rating?" out of a stranger's conversation.
#
# The chain's two lanes run on `threading.Thread` (see `chain.both`), and a plain
# Thread does *not* inherit the context. That is fine only because `standalone` runs
# above the lanes and not inside them -- the reads happen before either starts. A
# read moved into a lane would need the context copied into the thread.
_CURRENT: contextvars.ContextVar[Session | None] = \
    contextvars.ContextVar("abot_session", default=None)


def default_session() -> Session:
    """the session for callers that never asked for one -- `chain.ask` on its own, a
    one-shot `python cli.py "..."`. Made on first use, so importing chain.py does not
    open a connection to anything. Unowned: nobody logged in, so no `user_id`."""
    session = _CURRENT.get()
    if session is None:
        session = Session()
        _CURRENT.set(session)
    return session


def use(session: Session) -> Session:
    """make this the session the chain reads its own past out of. Called by
    `chain.ask` on every question, which is what keeps each request's view of "the
    conversation so far" its own."""
    _CURRENT.set(session)
    return session


def current() -> Session | None:
    """whatever `use` last set in this context, without making one. For callers that
    want to know rather than to have."""
    return _CURRENT.get()


# ------------------------------------------------------- the chain reads it back
def recent_turns(limit: int, session: Session | None = None) -> list[dict]:
    """the last few turns of this session, oldest first.

    `turns == 0` short-circuits: the first question of a session has nothing behind
    it, and a round trip to atlas to be told so would sit in front of every opening
    question of every chat. Failed turns are left out -- an error is not something a
    follow-up can refer back to.
    """
    session = session or default_session()
    database = db()
    if database is None or session.turns == 0 or limit <= 0:
        return []
    try:
        # `user_id` is redundant next to a uuid4 session id that nobody can guess,
        # and it is in the filter anyway. This read is the one that ends up inside a
        # prompt, so it is the last place to rely on an id being unguessable; it also
        # costs nothing, being the `owner` index's own prefix.
        rows = list(database[MESSAGES]
                    .find({"session_id": session.id, "user_id": session.user_id,
                           "error": None},
                          {"question": 1, "answer": 1, "seq": 1})
                    .sort("seq", -1).limit(limit))
    except Exception as e:
        print(f"  [history] could not read this session ({_why(e)})")
        return []
    return rows[::-1]


def as_context(turns: list[dict], answer_chars: int) -> str:
    """the turns as the transcript the rewrite prompt expects. The answers are cut:
    what a follow-up points at is named in the first line or two of the answer, and
    the rest is a paragraph the small model has to read past to find it."""
    return "\n".join(
        f"you> {t.get('question', '')}\nbot> "
        f"{' '.join((t.get('answer') or '').split())[:answer_chars]}"
        for t in turns)


# ------------------------------------------------------------------- reading it
def _scope(owner: str | None, admin: bool = False) -> dict:
    """the filter that limits a read to what the caller is allowed to see. Every
    read below starts from this, so there is one place to be right about it.

    An admin gets `{}` and sees everything, which is the team-wide view this file
    used to give everybody. Anyone else gets their own `user_id` and nothing else.

    That also hides the rows written before there were accounts: they have no
    `user_id`, so they match no owner. They were stamped with a machine login --
    `someone@somehost` -- which is not an account and not reliably a person either,
    and handing them to whoever has a similar username would be a guess. Admins can
    still read them; nobody else needs to.

    No owner and not an admin raises. A caller that forgot to say who it is has a
    bug, and the wrong way to resolve that bug is to show it everything.
    """
    if admin:
        return {}
    if not owner:
        raise PermissionError("no account -- log in to read chat history")
    return {"user_id": owner}


def recent(limit: int = 10, owner: str | None = None,
           admin: bool = False) -> list[dict]:
    """the caller's conversations, newest first. Served straight off the `owner`
    index -- (user_id, last_at) is exactly this query."""
    database = db()
    return list(database[CONVERSATIONS].find(_scope(owner, admin))
                .sort("last_at", -1).limit(limit)) if database is not None else []


def transcript(session_id: str, owner: str | None = None,
               admin: bool = False) -> list[dict]:
    """one conversation in full, if it is the caller's. The owner is in the filter
    rather than checked afterwards: a query that cannot match somebody else's rows
    cannot leak them through a forgotten `if`, and an empty result is the same
    answer as "no such conversation" -- which is the right answer to give someone
    guessing at ids."""
    database = db()
    return list(database[MESSAGES].find({"session_id": session_id,
                                         **_scope(owner, admin)}).sort("seq", 1)) \
        if database is not None else []


def find(text: str, limit: int = 20, owner: str | None = None,
         admin: bool = False) -> list[dict]:
    """the text index, newest first. Words, not substrings -- mongodb's text search
    matches whole terms, so "sensex" finds it and "sens" does not.

    This is the read the denormalised `user_id` on each message is for: a text index
    cannot span a join, so without the owner on the message there would be no way to
    search one person's turns short of listing their conversations first.
    """
    database = db()
    return list(database[MESSAGES].find({"$text": {"$search": text},
                                         **_scope(owner, admin)})
                .sort("ts", -1).limit(limit)) if database is not None else []


def _stamp(when) -> str:
    """utc goes in, local time comes out. Stored in utc because the team is not
    all in one timezone forever and a comparison between two rows has to mean
    something; printed local, because 11:40 for a question asked at 17:10 reads as
    a bug. pymongo hands back naive utc, hence the tzinfo before the conversion."""
    if not isinstance(when, datetime):
        return "?"
    return (when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when) \
        .astimezone().strftime("%d %b %H:%M")


def print_recent(limit: int = 10, owner: str | None = None,
                 admin: bool = False) -> None:
    rows = recent(limit, owner, admin)
    if not rows:
        print("no conversations saved yet")
        return
    for c in rows:
        print(f"{c['_id'][:12]}  {_stamp(c.get('last_at')):<13} "
              f"{c.get('turns', 0):>3} turns  {c.get('user', ''):<22} "
              f"{(c.get('title') or '')[:52]}")
    print("\npython history.py <id>  for the whole conversation")


def print_transcript(session_id: str, owner: str | None = None,
                     admin: bool = False) -> None:
    # the short id printed above is a prefix, so it is what gets typed back in
    database = db()
    if database is None:
        return
    # scoped, so that the prefix cannot be widened into somebody else's conversation
    # by typing fewer characters of it
    match = database[CONVERSATIONS].find_one({"_id": {"$regex": f"^{re.escape(session_id)}"},
                                              **_scope(owner, admin)})
    rows = transcript(match["_id"] if match else session_id, owner, admin)
    if not rows:
        print(f"nothing saved under {session_id}")
        return
    for m in rows:
        print(f"\n[{m['seq']}] {_stamp(m.get('ts'))}  you> {m['question']}")
        print(f"    bot> {(m.get('answer') or '').strip()}")
        print(f"    source: {m.get('source')}   chunks: {m.get('chunks')}"
              + (f"   urls: {m.get('urls')}" if m.get("urls") else ""))


def _caller() -> tuple[str | None, bool]:
    """(owner, admin) for somebody running this file from a terminal.

    `--all` is a request, not a grant: it only widens the read if the account
    actually is an admin, and says so plainly when it is not. Anything else is
    scoped to whoever `python cli.py login` last logged in as.
    """
    import auth

    account = auth.me()
    if account is None:
        print("not logged in -- python cli.py login")
        raise SystemExit(1)
    wants_all = "--all" in sys.argv[1:]
    if wants_all and account.get("role") != "admin":
        print(f"--all needs an admin account; {account['email']} is not one")
        raise SystemExit(1)
    return account["_id"], wants_all


def _main(args: list[str]) -> None:
    who, everything = _caller()
    args = [a for a in args if a != "--all"]
    if args and args[0] in ("-f", "--find"):
        hits = find(" ".join(args[1:]), owner=who, admin=everything)
        for m in hits:
            print(f"{m['session_id'][:12]}  {_stamp(m.get('ts'))}  {m['question'][:60]}")
            print(f"    {(m.get('answer') or '')[:200].strip()}\n")
        print(f"{len(hits)} matching turns")
    elif args:
        print_transcript(args[0], owner=who, admin=everything)
    else:
        print_recent(owner=who, admin=everything)


if __name__ == "__main__":
    # `python history.py` runs this file as `__main__`, and `_caller` imports auth,
    # which imports `history` -- a second copy of this module, with its own `_db` and
    # its own `_off`. Two connections to the same cluster, and a patched MONGO_DB
    # taking effect in only one of them. Handing the work to that copy rather than
    # doing it in this one means auth and the reads below share a single connection.
    import history

    history._main(sys.argv[1:])
