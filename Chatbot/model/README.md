# Abot

A finance assistant over a folder of Arihant Capital research PDFs.

`arihantBotFinal` with three changes:

1. **The index and the web are hit in parallel** rather than one after the other —
   [Two lanes, at once](#two-lanes-at-once).
2. **OpenAI writes the answers**, not `llama3.2:3b` — [The model](#the-model).
3. **A table row is no longer allowed to describe a company** —
   [What is Bandhan Bank](#fixed-what-is-bandhan-bank-was-answered-out-of-a-table).

```bash
ollama pull nomic-embed-text   # embeddings only; the writing is openai
ollama serve

# OPENAI_API_KEY and OPENAI_MODEL are read from MyBot/.env, one level up
pip install -r requirements.txt

python cli.py         # the index is already built -- just ask it things
```

`python build.py` is only needed after adding or changing a PDF; `index/` ships
with the folder. Nothing else here is run directly — they are imported.

`--refresh` re-reads the PDFs. Use it after editing `ingest.py` — the cache watches
the PDF files, not the parsing code, so a code change alone won't invalidate it.

## The files

| | | |
|---|---|---|
| `config.py` | | every knob, the prompts, and the finance vocabulary. |
| `ingest.py` | | folder → chunks. The long one, and the only one that needs to be. |
| `store.py` | | build and load the FAISS index. |
| `build.py` | **only after a new PDF** | reads the PDFs, writes the index. |
| `retrieve.py` | | similarity + date filter + the literal rescue. |
| `web.py` | | the DuckDuckGo lane. |
| `chain.py` | | the wiring. Its docstring is the pipeline diagram (`/graph`). |
| `history.py` | **also runnable** | every turn, saved to MongoDB and read back. |
| `auth.py` | **also runnable** | accounts, passwords, tokens, roles. |
| `api.py` | **the http front** | log in, ask, read your own chats back. |
| `cli.py` | **this is the one you run** | ask it things. |

## Chat history

Every question and answer is written to MongoDB, and every one of them belongs to
the account that asked it. One line in `.env` turns the storage on:

```bash
MONGODB_URI=mongodb+srv://user:pass@cluster.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=abot          # optional, this is the default
```

Three collections, created on first use along with their indexes — there is no setup
script to forget:

| | | |
|---|---|---|
| `users` | one per account | email, the bcrypt hash of the password, role, when it last logged in |
| `conversations` | one per chat | `user_id`, who, when, how many turns, the opening question, which models |
| `messages` | one per question and answer | `user_id`, the question, the autocorrection, the answer, `source`, the chunks and URLs behind it, the per-lane timings |

```
users  --<  conversations  --<  messages
       1:N                 1:N
```

Conversations join to `users` on `user_id` and to `messages` on `session_id`.
`source` is the field worth filtering on: it says whether an answer came from the
PDFs, the web, or the model's own knowledge.

The owner is stored on the message as well as on the conversation. That is a
duplicated field and it is deliberate: MongoDB's text index cannot span a join, so
scoping a search to one person's turns has to be answerable from the message alone.

```bash
python history.py              # your conversations, newest first
python history.py <id>         # that conversation in full — yours only
python history.py -f sensex    # every turn of yours mentioning a word
python history.py --all        # everyone's, if you are an admin
```

The same live in the CLI as `/history` and `/history <id>`, scoped to you.

## Accounts

`python cli.py` answers questions whether or not you have logged in. Logging in is
what gives the chat history your name on it — an anonymous run is still saved, but
with no owner, and an unowned conversation is one only an admin can read back.

The first account has to be made from a terminal, because a signup form that could
hand out the admin role would make the role meaningless:

```bash
python auth.py add you@arihantcapital.com --admin   # prompts for the password twice
python auth.py list                                 # the accounts
python auth.py role someone@arihantcapital.com admin
python auth.py disable someone@arihantcapital.com   # revoke access, keep the history
```

Then, on a terminal:

```bash
python cli.py login      # remembered in ~/.abot/token until /logout
python cli.py            # /whoami says who you are
```

### If the password prompt takes no input

Add `--visible` — `python auth.py add ... --visible`, `python cli.py login --visible`.

The hidden prompt uses `getpass`, which on Windows does not read stdin: it reads the
console device through `msvcrt.getwch()`. In a pseudo-terminal that is not a real
win32 console — VS Code's integrated terminal being the one people hit — those
keystrokes never arrive, and it blocks without raising and without a timeout. There
is nothing to catch, and from the outside it is indistinguishable from a hung
program while you type into a prompt that will never see it.

`--visible` skips `getpass` and uses `input()`, then overwrites the echoed line with
asterisks. The password stays out of the shell history either way, which is the part
that persists — unlike passing it as an argument, which PowerShell records in
`ConsoleHost_history.txt`.

Also: run these one at a time rather than pasting several lines at once. A pasted
block sits in the console input buffer, and the line after the command can be
swallowed as the answer to the prompt.

Two roles. A **user** reads its own conversations and nothing else. An **admin**
keeps the team-wide view this project used to give everybody — it is the audit view
now, behind `--all` on the command line and `/admin/...` over http.

The rows written before any of this existed have no owner, so they are admin-only.
They were stamped with a machine login (`someone@somehost`), which is not an account
and not reliably a person either; handing them to whoever has a similar username
would be a guess.

## The HTTP API

```bash
pip install -r requirements.txt
uvicorn api:app --reload        # then http://127.0.0.1:8000/docs
```

Add a signing key to `.env` first. Without one the process invents one at import and
every token dies with the process — fine for a demo, and a restart logs everybody
out:

```bash
JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
JWT_TTL_MIN=720          # optional, 12h is the default
```

| | |
|---|---|
| `POST /auth/register` | a new account, logged straight in. Always role `user` |
| `POST /auth/login` | → `{access_token, expires_in, user}` |
| `GET /auth/me` | who this token is |
| `POST /auth/password` | change your own, and only your own |
| `POST /chat` | `{question, conversation_id?}` — omit the id to start a chat, send it back to continue one |
| `GET /conversations` | yours, newest first |
| `GET /conversations/{id}` | that transcript, if it is yours |
| `GET /search?q=` | your own turns, by word |
| `GET /admin/users`, `GET /admin/conversations` | everyone's — needs the admin role |

Everything but `/health` and the two under `/auth` needs `Authorization: Bearer
<token>`. Reading or continuing a conversation that is not yours is a `404` and not
a `403`, so the api cannot be used to find out which conversation ids exist.

There is no server-side session. A conversation is a row with an id and the client
sends the id back, so two workers, a restart mid-chat, or the same person in two tabs
all behave.

### One process, two askers

`chain.standalone` reaches for "the conversation so far" without being handed it — it
sits four `RunnableLambda`s deep in a pipeline whose input is a plain string. That
used to be a module global, which is correct for a CLI and wrong for a server: two
requests and the second one's session wins for both.

It is a `contextvars.ContextVar` now (`history._CURRENT`). A ContextVar is
per-thread and per-async-task, so two people asking at once each resolve their
follow-ups against their own history. `/chat` is a plain `def` rather than an `async
def` so that FastAPI runs the slow, synchronous chain in its threadpool instead of
blocking the event loop; anyio carries the context into that thread.

Worth knowing if you move code around: the chain's two lanes run on bare
`threading.Thread` (`chain.both`), and a bare Thread does **not** inherit the
context. That is fine only because the history read happens above the lanes, not
inside one.

### Follow-ups

The log is also read back *into* the chat, which is what lets a question lean on the
one before it:

```
you> what was the sensex close on 10 may 2022
bot> ...

you> and the nifty?
  [follow-up]   -> What was the Nifty close on 10 May 2022?
  [date filter] -> 2022-05-10
```

`and the nifty?` is a question to a person and three stopwords to FAISS. Before
anything searches, the session's last four turns come out of `messages` and a small
model puts the missing words back — here it carried over both the metric and the
date, so the date filter fired on a line that contains no date. Everything below
that point — scope, the rating scale, both lanes — sees the rewrite, and the rewrite
is stored beside the original as `standalone`.

Three things keep it from doing harm. It reads **this session only**, so nobody's
chat can leak into anybody else's answer. It runs only on lines that look like they
lean backwards (`FOLLOWUP_Q`) and never on the first question of a session, so most
questions don't pay for it. And a rewrite much longer than the line it replaced is
thrown away — that shape means the small model answered the question instead of
rewriting it, and an answer used as a search string retrieves the chunks that agree
with it.

Saving happens *after* the answer is printed, so a slow cluster costs the log and
never the reply. No `MONGODB_URI`, no network, or a cluster that disappears
mid-session — each prints one line and switches saving off for the rest of the run.
The bot answers exactly as it did before.

## The model

`OPENAI_MODEL` and `OPENAI_API_KEY` come out of `MyBot/.env` — one level up, so a
copy of this folder does not carry a copy of the key. `config.py` loads it, and a
`.env` inside this folder overrides it if this ever moves out on its own.

Both model roles are OpenAI now: the writing, and the errands (autocorrect and the
in-scope router, at temperature 0). Set `OPENAI_SMALL_MODEL` to put the errands on
something cheaper — they are two calls per question and neither needs a good model.

**Embeddings stayed on Ollama.** The vectors in `index/` were made by
`nomic-embed-text`, and a query has to be embedded by the same model that made
them, so `ollama serve` is still required — for that one thing. Point `EMBED_MODEL`
at an OpenAI model and every vector has to be rebuilt (`python build.py`) before
anything can be searched at all.

The upgrade is not cosmetic. Asked for the Sensex close on 17 Nov 2022, retrieval
hands over shredded OCR (`APARINDS | 1,544! | 1,649 | 52 Week Low`) and a bare
column of ratios — the close is not in there. `llama3.2:3b` read `10.32` out of
that column and reported it as the Sensex close. `gpt-5.6-luna` replies
`NOT IN THE DOCUMENTS`, and the web lane, which is already running, answers it.

## Fixed: "what is Bandhan Bank" was answered out of a table

```
you> what is bandhan bank
Bot: Bandhan Bank is an Accumulate research call with a Potential Upside % of 19%
     and Absolute Return % of -20%.
```

That is a sentence about a table, not about a bank, and every gate passed it. The
reco table has a `Bandhan Bank | Accumulate | 19% | -20%` row, so the words of that
answer really are all in the context and `grounded()` scored it high — that check
asks whether the answer is *made of* the context, and this one was. There is no
threshold that separates it from a correct answer about a target price.

What separates them is not in the text at all: the question asked what something
**is**, and every chunk behind the answer was a `Table`. `doc_verdict()` reads the
`[1][2]` the answer cites, looks up those chunks' category, and declines when the
question wanted a description and the citations are all table cells.
`wants_description()` is what tells `what is bandhan bank` (declines) from
`what is bandhan bank's target price` (answers, ₹338) — the metric words in
`METRIC_Q` are the whole difference between the two.

The two halves fit together: declining costs nothing, because the parallel web lane
has been looking up what Bandhan Bank is since the question was asked.

```
you> what is bandhan bank
Bot: Bandhan Bank is an Indian private-sector universal bank headquartered in
     Kolkata, West Bengal. It began operations on August 23, 2015 ... [1][2]
  [source]      -> web
```

`DOC_PROMPT` also tells the model outright that a row of numbers is not a
description. That alone would be a prompt hoping to be obeyed, which is why the
citation check exists underneath it.

## Four tiers

```
1  arihant     the rating scale and the firm, parsed from report boilerplate
2  documents   the PDFs, cited, with Arihant's own call leading the answer
3  web         DuckDuckGo, read when the documents came up empty
4  general     the model's own knowledge, with a disclaimer
```

Two things never enter the four. A line that is *only* a greeting is answered from
a table — checked before the spellchecker so `hi` costs nothing, and again after it
so `hellping` still lands. And a question that is not about finance at all gets one
short line and a redirect, rather than a web search and two citations.

## Two lanes, at once

Tiers 2 and 3 used to be a sequence: search the index, write an answer, judge it,
and only then — if it missed — go to the web and do all of that again. The two
share nothing. One reads FAISS on disk, the other reads DuckDuckGo, and each ends
in its own Ollama call, so both spend nearly all their time inside an HTTP call
with the GIL released. `chain.both()` therefore starts the web lane on a thread at
the same moment the index lane starts.

Started together, **not joined together.** The router prefers the documents, so
when the PDFs answer, the web lane's result was never going to be read — joining
on it would make the question the corpus *can* answer the slowest one there is.
It is left running and the answer returns; only a document miss ever waits on it.
The thread is a daemon for that reason: a normal one is joined at interpreter exit
and the CLI would hang on a search it had already decided it did not want.

What this is and is not worth, measured in-process on this corpus with
`llama3.2:3b` (so the index load and Ollama warmup are excluded):

| the question ends on | before | after |
|---|---|---|
| **documents** — *"sensex close on 17 november 2022"* | 2.1s, 2.0s | 2.2s, 2.5s |
| **web or general** — *"teslas total revenue in 2024"* | 16.5s, 11.1s | 16.9s, 13.3s |

Read that honestly: **the saving is exactly the document lane, and nothing else.**
A question the PDFs answer was already paying for one lane and still is — the
extra ~0.2s is the background thread competing for the same Ollama. A question the
PDFs miss used to pay documents *then* web, and now pays the web alone, which on
these runs is 1.2–3.5s off a 11–17s answer. DuckDuckGo plus three page fetches
varies by more than that between two runs of the same question, so the win is real
but you will not see it in any single pair of runs. `/show` prints both lanes so
the arithmetic is visible rather than asserted:

```
  [lanes]       -> docs 3472ms, web 12065ms, side by side 12065ms (saved 3472ms)
  [lanes]       -> docs 1146ms, web started, left running unread
```

The other half of the change is not latency. The web answer is now being written
*while* the documents are still being read, so by the time the router runs on a
document miss both answers exist and tiers 2 and 3 are a choice between two
finished drafts rather than a chain of fallbacks.

A lane that raises no longer takes the other down with it — a dead network used to
cost only the web answer, but running alongside a good document answer it would
have killed that too, so each lane catches and reports as a miss.

## The three things that were actually broken

Each of these was found by running the bot, not by reading it.

**The date filter was silently lying.** FAISS cannot search inside a metadata
subset — LangChain fetches `fetch_k` neighbours over the *whole* index and drops the
failures afterwards, and `fetch_k` defaults to 20. On a corpus of near-identical
dailies the 20 nearest chunks to a Sensex question came from nine different days, 2
survived the filter, and the right table was never a candidate. Setting `fetch_k` to
the index size took the market-data table's top-4 recall from **3/20 to 11/20**.

**Dense search cannot find a company in a table.** "axis bank current price" has
nothing to match against four columns of digits — but `Axis Bank` is *printed*
there, in 4 chunks out of 447. `literal()` adds chunks containing a phrase that
rare, and generates the report's own date format so "29 april 2022" finds a cell
printed `29-Apr-22`.

**Tables were being handed to the model as raw HTML.** `<table><thead><tr><th
rowspan="2">` is hostile to a 3B model — given it, the model says it cannot see a
company plainly in it. `ingest.py` renders every table as `a | b | c` rows with a
caption naming its columns and row labels. The caption is also what makes the table
*embeddable*: without it the chunk is digits, and digits sit near nothing.

## Fixed: a split table's caption named rows it didn't have

`split_tables()` cut an over-budget table by rows but copied the *whole* table's
caption onto every piece unchanged. `caption()` also caps its row list at 14, and
on the Company Reco table (70+ rows, banking first) those 14 are always the
banking names -- so a piece holding Ambuja Cement, Maruti Suzuki and Hero
MotoCorp still carried a caption reading `Rows: ... Axis Bank, Bandhan Bank ...
HDFC Bank ... NBFC*`.

Checked against the built index: 16 chunks contained the phrase "axis bank", and
only 4 of them held Axis Bank's actual row -- the other 12 were split pieces of
the same reco tables, matching purely on a caption that had nothing to do with
their content. With `RESCUE_K = 2`, that's enough noise to bump the real chunk
out of the literal rescue on an undated question, or to hand the model a table
that plainly does not contain the company it's being asked about.

`split_tables()` now rebuilds each piece's `Rows:` line from that piece's own
first column, the same rule `caption()` uses, before rejoining it with the
column-names sentence and the date suffix. Re-run against the corpus: piece 2
of the 10th-Nov reco table now captions itself with Ambuja Cement, Ramco Cement,
M&M, Maruti Suzuki, Hero MotoCorp -- not Axis Bank.

## What it is still not good at

**A question with no date in it has several right answers.** Axis Bank's current
price is 659, 785, 874 and 855 across four dailies. Undated, the bot answers "₹874"
without saying which one — true, but unfalsifiable. Answers over a dated table
should carry the date they came from, and do not yet.

## Fixed: a table's date is not its filename's date

A reco table is as of the previous *trading* day, so the table headed `16-Nov-22`
sits inside `17th Nov 2022.pdf` — and `16th_Nov_2022.pdf` does not contain it at
all. `12th_September_2022.pdf` carries `09-SEP-2022`, three days back over a
weekend, so the offset is not a constant either. Meanwhile the market-data tables in
those same files *are* same-day.

The date therefore belongs to the table, not to the pdf it arrived in. `table_date()`
reads it from the table's own header row and `tag()` files the chunk under it,
keeping the filename's date as `published`. Only the 8 reco-table chunks move; the
other 433 keep the date they had. `dates_in()` also learned `DD-Mon-YY`, the format
the reports print and the one a reader types — it previously understood only
"16 november 2022" and ISO, so the filter almost never fired.

Asked for Axis Bank on 16-Nov-22, retrieval now returns
`Axis Bank | 26-Jul-22 | 780 | 855 | 980 | Hold`, and on 09-Nov-22 the same row from
the other daily reading `780 | 874 | 940 | Buy`.

## Fixed: tables were being OCR'd, not read

`STRATEGY = "hi_res"` rasterizes each page and runs OCR over the picture, which
shredded every table in the corpus — **5 of 179 rows survived**. The Bandhan Bank
row indexed as `Bandhan Bank | | | | | | ao | 20g | 2a | | 2a | 81.45)` against a
real row of `25-Jul-22 | 285 | 229 | 338 | Accumulate | 19% | -20%`.

No reader model can survive that, and a stronger one made it worse rather than
better: `llama3.2:3b` answered "20g", which is visibly garbage, while `gpt-5.6-luna`
answered a confident cited "₹280, Buy" — plausible, wrong, and much harder to catch.

Every pdf here is digital and carries those rows as real text, so `pdf_tables()` in
`ingest.py` now reads them with `pymupdf.find_tables()` and unstructured keeps only
the job it is good at, finding where things are. **212 of 250 rows now parse
cleanly** and the Bandhan question answers 285 / Accumulate.

There is also no conversation memory. `ask()` is stateless, so "and the day before?"
cannot work until the question is rewritten against the history first.

## Fixed: the server died on the first question and the port stayed open

The browser said *"The assistant took too long to answer"* after three minutes. It
had not taken too long — nothing was there to answer. The worker process was
already dead, killed by the very question it was asked:

```
OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib
                already initialized.
Abort trap: 6
```

Three wheels in the venv ship their own build of the same LLVM OpenMP runtime:
`torch/lib/libomp.dylib`, `faiss/.dylibs/libomp.dylib`, `sklearn/.dylibs/`. A
runtime registers itself in a per-process slot the first time it runs a parallel
region, not when it is loaded — so torch's copy claims the slot at import, the
process looks perfectly healthy, and the second copy only turns up when faiss runs
its first search. It finds the slot taken and calls `abort()`:

```
__kmp_register_library_startup -> __kmp_fatal -> abort
```

That is a question in, no answer out, and the whole worker gone.

**Why the port stayed open.** `uvicorn --reload` is a parent that holds the
listening socket and a child that serves. The parent restarts the child when a
*file* changes — never when one dies. So the child aborted, the parent kept
accepting connections, and every later request sat in a socket nobody was reading
until the client gave up. `/health` hung the same way. The one honest signal — a
connection refused — was the one thing the setup could not produce, which is why
the frontend's own timeout was left to invent an explanation.

**The fix** is the one the error message actually asks for: *ensure that only a
single OpenMP runtime is linked into the process*. `openmp_fix.py` points faiss's
`@loader_path/.dylibs/libomp.dylib` at torch's copy with a symlink, so dyld
resolves both to one file and there is only ever one runtime to register.

```bash
python openmp_fix.py     # idempotent; re-run after any pip install
```

Verified rather than assumed, because "they are both libomp" is a guess:

* all 40 OpenMP symbols `libfaiss.dylib` and `_swigfaiss.abi3.so` import are
  exported by torch's build — nothing goes unresolved. The 7 symbols only faiss's
  copy has are device-offload entry points (`omp_get_device_from_uid` and friends)
  that faiss never calls.
* results are unchanged: exact agreement with a brute-force numpy top-10 over
  5000×128, distances within 4e-06, identical output at 8 threads.
* one `libomp` image mapped in the live process, confirmed through `_dyld`.

Not `KMP_DUPLICATE_LIB_OK=TRUE`. That does not remove the second runtime, it only
stops it complaining — two thread pools then oversubscribe the cores, and llvm's
own wording for what follows is "may cause crashes or silently produce incorrect
results". A real dedupe costs nothing and keeps that promise properly.

**Torch is on the answering path, and deferring the pdf loaders does not change
that.** `load_folder` is right to import `UnstructuredPDFLoader` lazily, but that
is not where torch comes from. It arrives through the text splitter:

```
chain.py:74      import web
web.py:17        from ingest import clean_text
ingest.py:37     from langchain_text_splitters import RecursiveCharacterTextSplitter
  langchain_text_splitters/__init__.py:42   from .spacy import SpacyTextSplitter
  langchain_text_splitters/spacy.py:13      import spacy   -> thinc -> torch
```

`langchain_text_splitters/__init__` imports its spacy splitter eagerly, so any
import of that package pulls spacy, thinc and torch — and `web.py` needs one
function out of `ingest.py` to get there. Keeping torch off the answering path for
real means giving `clean_text` a home that does not import a splitter. Until then
the dedupe is what holds, and it holds regardless of who imports what in which
order.

`api.py` now says so at startup if the symlink is ever undone, rather than letting
the next question take the server down:

```
[api] TWO OpenMP runtimes in this venv -- the first question will abort
      this process. Run: python openmp_fix.py
```
