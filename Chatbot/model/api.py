"""the http front: log in, ask, read your own chats back.

    uvicorn api:app --reload            then http://127.0.0.1:8000/docs

Every route below except `/health` and the two under `/auth` needs a bearer token,
and the account that token names is the only account whose conversations the route
can reach. That is not enforced route by route -- it is enforced by never building a
mongodb filter without an owner in it. `history._scope` is where that happens, and
these handlers pass `owner=` into it rather than filtering afterwards.

What this file deliberately does not do:

  it does not hold a session between requests. A conversation is a row in mongodb
  with an id, and the client sends the id back. Two uvicorn workers, a restart
  mid-chat, somebody with the api open in two tabs -- none of those lose a chat,
  because there was never anything in memory to lose.

  it does not trust `conversation_id` from the body. `Session.resume` checks the
  owner before it will carry one on, so a guessed id is a 403 and not a way into
  somebody else's transcript.

The one thing worth knowing about the threading: `chain.ask` is synchronous and slow
-- model calls, a web search, faiss. The `/chat` handler is a plain `def` and not an
`async def`, so fastapi runs it in its threadpool and one person's question does not
block the event loop for everybody else's. The per-request session lives in a
ContextVar (see history.py) which anyio carries into that thread for us.
"""
from __future__ import annotations
from fastapi.responses import FileResponse

import os
import time
from fastapi import FastAPI

import hashlib
import secrets
from datetime import datetime, timedelta,timezone

import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

import auth
import history
from config import JWT_EPHEMERAL, JWT_TTL_MIN, PASSWORD_MIN_LEN

def _warm() -> None:
    """import chain once, off the request path.

    `from chain import ask` is a ~80 second import -- faiss off disk, the ollama
    embedder, langchain's own module tree. Imported lazily inside `/chat` (which is
    still where it lives, so nothing below has to change) that cost lands on
    whichever person happens to ask the first question, and 80 seconds is long
    enough that a browser gives up and the frontend looks broken on its first use.

    So it is paid here instead, on a plain thread at startup. A thread and not an
    `await`: the import is blocking, and on the event loop it would hold off
    /health and /auth/login for the same 80 seconds -- which is the outage this is
    meant to avoid, just moved. Anything that arrives mid-warm still works; only
    /chat waits, and only until the import it was going to do itself is done.
    """
    try:
        import chain                      # noqa: F401  -- imported for the warmth
    except Exception as e:
        # not fatal here. /chat will try the same import and fail loudly per
        # request, which is a better place for it than a dead server.
        print(f"  [api] could not warm the chain ({type(e).__name__}) -- "
              "the first question will be slow and may fail")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """said once, at startup. Three things that are quietly broken rather than
    loudly broken, so they get named before the first request rather than after
    it."""
    if JWT_EPHEMERAL:
        print("  [api] no JWT_SECRET in .env -- tokens are signed with a key that "
              "dies with this process, so a restart logs everybody out")
    if history.db() is None:
        print("  [api] no mongodb -- there are no accounts to log in to")

    # the quietest of the three, and the only one that kills the process. Two
    # copies of libomp in the venv (torch ships one, faiss ships another) means
    # the first faiss search calls abort() and takes the whole worker with it --
    # while `--reload`'s parent keeps the port open, so every later request hangs
    # unanswered and the browser blames its own timeout. openmp_fix.py explains
    # it properly; a pip install is all it takes to undo the fix.
    if sys.platform == "darwin":
        try:
            from openmp_fix import duplicate_runtimes
            if len(duplicate_runtimes()) > 1:
                print("  [api] TWO OpenMP runtimes in this venv -- the first "
                      "question will abort this process. Run: python openmp_fix.py")
        except Exception:
            pass    # a missing helper is not a reason to refuse to start

    threading.Thread(target=_warm, name="warm-chain", daemon=True).start()
    yield


app = FastAPI(title="arihant bot", version="2.0", lifespan=lifespan,
              description="ask the bot, and read back what you asked it")

# the browser origins allowed to call this. A wildcard here plus cookie auth would
# be a cross-site request forgery; with bearer tokens it is merely too generous, and
# it is still worth naming the frontends rather than allowing every page on the
# internet to spend this bot's openai budget.
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:3000", "http://localhost:5173",
                                  "http://localhost:8501"],   # react, vite, streamlit
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# auto_error=False so a missing header arrives here as None and gets the same shaped
# json error as everything else, instead of fastapi's own bare 403
bearer = HTTPBearer(auto_error=False)


# ------------------------------------------------------------------ the shapes
class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=72)
    name: str | None = Field(default=None, max_length=80)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)   # no min: a short one is simply wrong,
    #                                        and saying which is wrong helps nobody


class NewPassword(BaseModel):
    """no email field, deliberately. There is exactly one account this route can
    change and the token already says which -- an email in the body would either be
    ignored, which is confusing, or honoured, which is an account takeover."""
    password: str = Field(min_length=PASSWORD_MIN_LEN, max_length=72)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class Account(BaseModel):
    id: str
    email: str
    name: str
    role: str
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None   # continue that chat; omit to start one


class Answer(BaseModel):
    answer: str
    source: str | None = None
    conversation_id: str
    seq: int
    standalone: str | None = None
    pdfs: list[str] = []
    urls: list[str] = []
    took_ms: int | None = None


class Turn(BaseModel):
    seq: int
    ts: datetime | None = None
    question: str
    answer: str | None = None
    source: str | None = None


class Conversation(BaseModel):
    id: str
    title: str | None = None
    turns: int = 0
    started_at: datetime | None = None
    last_at: datetime | None = None
    interface: str | None = None


# ------------------------------------------------------------------ the guards
def _fail(e: auth.AuthError) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if e.status == 401 else None
    return HTTPException(status_code=e.status, detail=e.message, headers=headers)


def account(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    """the account behind the bearer token, or 401. This is the dependency that
    makes a route private -- a route without it is public, so there is exactly one
    thing to check when reading this file."""
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "log in first",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return auth.user_for_token(creds.credentials)
    except auth.AuthError as e:
        raise _fail(e) from e


def admin(user: dict = Depends(account)) -> dict:
    """...and an admin at that. Layered on `account` rather than reimplementing it,
    so there is no second copy of the token check to drift out of step."""
    try:
        return auth.require_admin(user)
    except auth.AuthError as e:
        raise _fail(e) from e


# -------------------------------------------------------------------- accounts
@app.get("/health")
def health() -> dict:
    return {"ok": True, "mongodb": history.db() is not None}


@app.post("/auth/register", response_model=Token,
          status_code=status.HTTP_201_CREATED)
def register(body: Register) -> Token:
    """a new account, logged straight in. Always role "user": if signing up could
    name its own role, the role would not mean anything. Promotion is
    `python auth.py role <email> admin`, on purpose -- off the network entirely.
    """
    try:
        auth.register(body.email, body.password, body.name)
        user = auth.authenticate(body.email, body.password)
    except auth.AuthError as e:
        raise _fail(e) from e
    token, expires_in = auth.issue_token(user)
    return Token(access_token=token, expires_in=expires_in, user=auth.public(user))


@app.post("/auth/login", response_model=Token)
def login(body: Login) -> Token:
    try:
        user = auth.authenticate(body.email, body.password)
    except auth.AuthError as e:
        raise _fail(e) from e
    token, expires_in = auth.issue_token(user)
    return Token(access_token=token, expires_in=expires_in, user=auth.public(user))


@app.get("/auth/me", response_model=Account)
def whoami(user: dict = Depends(account)) -> Account:
    return Account(**auth.public(user))


@app.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: NewPassword, user: dict = Depends(account)) -> None:
    """your own password, and only your own -- the account comes from the token."""
    try:
        auth.set_password(user["email"], body.password)
    except auth.AuthError as e:
        raise _fail(e) from e


# ------------------------------------------------------------------ asking it
@app.post("/chat", response_model=Answer)
def chat(body: Ask, user: dict = Depends(account)) -> Answer:
    """ask a question, on a new conversation or an existing one of yours.

    A plain `def`: `chain.ask` blocks for seconds on model calls, and on the event
    loop that would be seconds of every other request waiting behind it.
    """
    from chain import ask       # late: importing chain warms faiss and ollama, and
    #                             /health and /auth/login should not pay for that

    if body.conversation_id:
        try:
            session = history.Session.resume(body.conversation_id, user)
        except PermissionError as e:
            # the same 404 for "not yours" and "not there", so that the api cannot
            # be used to find out which conversation ids exist
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "no such conversation") from e
    else:
        session = history.Session.for_user(user, interface="api")

    started = time.perf_counter()
    try:
        out = ask(body.question, show_working=False, session=session)
    except Exception as e:
        # the turn is already saved with its error by `ask` itself
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"the chain failed: {type(e).__name__}") from e
    # timed here rather than read off `out`: `ask` computes the wall time and hands it
    # to `session.save`, which is where `timing_ms` gets assembled -- the dict that
    # comes back out of `ask` never had the field.
    took_ms = int((time.perf_counter() - started) * 1000)

    docs = out.get("docs") or []
    return Answer(
        answer=out.get("answer") or "",
        source=out.get("source"),
        conversation_id=session.id,
        seq=session.turns,
        standalone=out.get("standalone"),
        pdfs=sorted({d.metadata.get("source") for d in docs} - {None}),
        urls=[p.get("url") for p in (out.get("pages") or []) if p.get("url")],
        took_ms=took_ms)


# ------------------------------------------------------- reading it back
@app.get("/conversations", response_model=list[Conversation])
def my_conversations(limit: int = 20, user: dict = Depends(account)
                     ) -> list[Conversation]:
    rows = history.recent(min(max(limit, 1), 100), owner=user["_id"])
    return [Conversation(id=r["_id"], title=r.get("title"),
                         turns=r.get("turns", 0), started_at=r.get("started_at"),
                         last_at=r.get("last_at"), interface=r.get("interface"))
            for r in rows]


@app.get("/conversations/{conversation_id}", response_model=list[Turn])
def my_transcript(conversation_id: str, user: dict = Depends(account)) -> list[Turn]:
    rows = history.transcript(conversation_id, owner=user["_id"])
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such conversation")
    return [Turn(seq=m["seq"], ts=m.get("ts"), question=m["question"],
                 answer=m.get("answer"), source=m.get("source")) for m in rows]


@app.get("/search", response_model=list[Turn])
def search_mine(q: str, limit: int = 20, user: dict = Depends(account)) -> list[Turn]:
    """your own turns, by text. Whole words -- see history.find."""
    rows = history.find(q, min(max(limit, 1), 100), owner=user["_id"])
    return [Turn(seq=m["seq"], ts=m.get("ts"), question=m["question"],
                 answer=m.get("answer"), source=m.get("source")) for m in rows]


# ----------------------------------------------------------------- admin only
@app.get("/admin/users", response_model=list[Account])
def all_users(limit: int = 100, _: dict = Depends(admin)) -> list[Account]:
    return [Account(**u) for u in auth.everyone(min(max(limit, 1), 500))]


@app.get("/admin/conversations", response_model=list[Conversation])
def all_conversations(limit: int = 50, _: dict = Depends(admin)
                      ) -> list[Conversation]:
    """everyone's, which is what this file used to show everyone. It is the audit
    view now and it needs the role."""
    rows = history.recent(min(max(limit, 1), 200), admin=True)
    return [Conversation(id=r["_id"], title=r.get("title"),
                         turns=r.get("turns", 0), started_at=r.get("started_at"),
                         last_at=r.get("last_at"), interface=r.get("interface"))
            for r in rows]


@app.get("/admin/conversations/{conversation_id}", response_model=list[Turn])
def any_transcript(conversation_id: str, _: dict = Depends(admin)) -> list[Turn]:
    rows = history.transcript(conversation_id, admin=True)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such conversation")
    return [Turn(seq=m["seq"], ts=m.get("ts"), question=m["question"],
                 answer=m.get("answer"), source=m.get("source")) for m in rows]


@app.post("/admin/users/{email}/role", status_code=status.HTTP_204_NO_CONTENT)
def promote(email: str, role: str, me: dict = Depends(admin)) -> None:
    if email.strip().lower() == me["email"] and role != "admin":
        # the last admin demoting themselves leaves nobody who can promote anyone,
        # and the only way back is the mongo shell
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "you cannot demote yourself")
    try:
        auth.set_role(email, role)
    except auth.AuthError as e:
        raise _fail(e) from e


@app.post("/admin/users/{email}/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable(email: str, disabled: bool = True, me: dict = Depends(admin)) -> None:
    if email.strip().lower() == me["email"] and disabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "you cannot disable yourself")
    try:
        auth.set_disabled(email, disabled)
    except auth.AuthError as e:
        raise _fail(e) from e

@app.get("/chat-ui", include_in_schema=False)
def chat_ui():
    return FileResponse("static/chat.html")

from pydantic import BaseModel

class ChatAPIRequest(BaseModel):
    question: str

@app.post("/chat-api")
def chat_api(
    request: ChatAPIRequest,
    user: dict = Depends(account)
):
    body = Ask(
        question=request.question,
        conversation_id=None
    )

    return chat(body=body, user=user)

from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
import secrets

class ShareAccessRequest(BaseModel):
    minutes: int = 60

create_chat_access_tokens = {}

@app.post("/admin/create-chat-access")
def create_chat_access(
    body: ShareAccessRequest,
    user: dict = Depends(admin)
):
    if not 1 <= body.minutes <= 1440:
        raise HTTPException(
            status_code=400,
            detail="Duration must be 1 to 1440 minutes"
        )

    access_token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(
        access_token.encode()
    ).hexdigest()

    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=body.minutes
    )

    create_chat_access_tokens[token_hash] = expires_at

    return {
        "access_token": access_token,
        "expires_at": expires_at.isoformat(),
        "message": "Access credential generated"
    }

from fastapi import Header

def verify_chat_access(
    x_chat_token: str = Header(default="")
):
    if not x_chat_token:
        raise HTTPException(
            status_code=401,
            detail="Chat access token required"
        )

    token_hash = hashlib.sha256(
        x_chat_token.encode()
    ).hexdigest()

    expires_at = create_chat_access_tokens.get(token_hash)

    if expires_at is None:
        raise HTTPException(
            status_code=403,
            detail="Invalid access token"
        )

    if datetime.now(timezone.utc) >= expires_at:
        create_chat_access_tokens.pop(token_hash, None)
        raise HTTPException(
            status_code=403,
            detail="Access token expired"
        )

    return True

@app.post("/shared-chat")
def shared_chat(
    body: ChatAPIRequest,
    verified: bool = Depends(verify_chat_access)
):
    chat_body = Ask(
        question=body.question,
        conversation_id=None
    )

    return chat(
        body=chat_body,
        user={
            "_id": "shared-chat",
            "email": "shared@local.invalid",
            "role": "user"
        }
    )

if __name__ == "__main__":
    import uvicorn

    print(f"tokens last {JWT_TTL_MIN} minutes -- http://127.0.0.1:8000/docs")
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)

        