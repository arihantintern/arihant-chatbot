# Arihant Capital Finance Chatbot — Complete Documentation

A finance research assistant for Arihant Capital. A Python/FastAPI backend (`model/`)
answers questions over a folder of Arihant research PDFs, the open web, and Arihant's
own live market-data feed (CMOTS); a React frontend (`frontend/`) is the recruiter-facing
chat client on top of it.

This document covers: the system architecture, every design decision baked into the
backend pipeline, the MongoDB data model, the complete request/response flow for a
chat turn, the frontend architecture, and how to run the whole stack locally.

> **Ownership note.** `model/` was built by someone else and is treated as a fixed,
> working contract — this documentation describes it faithfully but does not propose
> changes to it. `frontend/` is the deliverable this documentation exists to support.

---

## Table of contents

1. [System architecture](#1-system-architecture)
2. [Local setup — running the whole stack](#2-local-setup--running-the-whole-stack)
3. [Backend: the RAG pipeline](#3-backend-the-rag-pipeline)
4. [Backend: the CMOTS market-data subsystem](#4-backend-the-cmots-market-data-subsystem)
5. [Backend: accounts, tokens, roles](#5-backend-accounts-tokens-roles)
6. [MongoDB data model](#6-mongodb-data-model)
7. [The HTTP API](#7-the-http-api)
8. [The complete flow of one chat turn](#8-the-complete-flow-of-one-chat-turn)
9. [Frontend architecture](#9-frontend-architecture)
10. [Known fragility & operational notes](#10-known-fragility--operational-notes)

---

## 1. System architecture

```
┌─────────────────────────┐        HTTPS / JSON, Bearer JWT        ┌──────────────────────────┐
│   frontend/  (React 19,  │ ─────────────────────────────────────▶│   model/api.py (FastAPI)  │
│   Vite, vanilla CSS)     │◀───────────────────────────────────── │   single blocking POST    │
│   localhost:5173          │        Answer / Turn / Conversation   │   /chat, no streaming     │
└─────────────────────────┘                                        └────────────┬─────────────┘
                                                                                  │
                                             ┌────────────────────────────────────┼──────────────────────────────┐
                                             ▼                                    ▼                              ▼
                                   ┌───────────────────┐              ┌───────────────────┐         ┌─────────────────────┐
                                   │  FAISS index       │              │  DuckDuckGo web    │         │  CMOTS live feed     │
                                   │  (model/index/)     │              │  search + fetch    │         │  (cmots.py, its own  │
                                   │  built from PDFs     │              │  (web.py)          │         │  MongoDB `cmots` db, │
                                   │  in model/pdfs/       │              │                    │         │  synced by a cron     │
                                   │  embeddings: Ollama   │              │                    │         │  scheduler)           │
                                   │  nomic-embed-text     │              └───────────────────┘         └─────────────────────┘
                                   └───────────────────┘
                                             │
                                             ▼
                                   OpenAI (gpt-5.6-luna by
                                   default) writes every answer;
                                   embeddings alone stay on Ollama

                                   MongoDB `abot` database
                                   (users / conversations / messages)
                                   — separate DB from `cmots`
```

Two independent MongoDB databases are involved, both on the same local `mongod` in a
typical dev setup:

- **`abot`** — this bot's own accounts and chat history (`users`, `conversations`, `messages`).
- **`cmots`** — Arihant's live market-data mirror, synced on its own schedule, read
  (not written) by the chatbot when a question needs live company/market data.

---

## 2. Local setup — running the whole stack

### 2.1 Prerequisites

| Tool | Why | Check |
|---|---|---|
| Python 3.12 or 3.13 | backend | `python3 --version` |
| Node.js 18+ | frontend (Vite 8, React 19) | `node --version` |
| Ollama | embeddings only (`nomic-embed-text`) — the writing model is OpenAI | `ollama --version` |
| MongoDB (local `mongod`, or Atlas) | chat history + CMOTS mirror | `mongod --version` |
| An OpenAI API key | the chat model and the "small" errand model | — |

macOS note: three Python wheels in the venv (`torch`, `faiss`, `scikit-learn`) each
ship their own copy of the LLVM OpenMP runtime. Two runtimes registering in one
process crashes the worker on the first FAISS search. See
[§10](#10-known-fragility--operational-notes) — run `python openmp_fix.py` once
after creating the venv and again after any `pip install`.

### 2.2 Backend setup (`model/`)

```bash
cd model

# 1. Python environment
python3 -m venv .venv
source .venv/bin/activate           # .venv\Scripts\activate on Windows
pip install -r requirements.txt

# 2. Fix the double-OpenMP problem (macOS) — idempotent, safe to re-run
python openmp_fix.py

# 3. Embeddings model (only embeddings run on Ollama; answers come from OpenAI)
ollama pull nomic-embed-text
ollama serve                        # leave running in its own terminal

# 4. Secrets — model/.env (git-ignored)
cat > .env <<'EOF'
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.6-luna           # optional, this is the default
OPENAI_SMALL_MODEL=gpt-5.6-luna     # optional — put the cheap errands on a cheaper model

MONGODB_URI=mongodb://localhost:27017     # or an Atlas mongodb+srv:// URI
MONGODB_DB=abot                            # optional, default shown

# CMOTS mirror — falls back to MONGODB_URI, then to localhost, if unset
CMOTS_MONGO_URI=mongodb://localhost:27017
CMOTS_DB=cmots

JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
JWT_TTL_MIN=720                     # optional, 12h is the default
EOF
```

Without `MONGODB_URI` the bot still answers questions — it just does not save or
read back any chat history (`history.py` prints one line and turns itself off).
Without `JWT_SECRET` the process invents one at import, so every login is
invalidated on the next restart — fine for a one-off demo, wrong for anything
persistent.

```bash
# 5. Build the FAISS index (only needed once, and again after adding/changing a PDF)
python build.py               # index/ already ships with the repo; re-run after PDF changes
python build.py --refresh     # force re-reading the PDFs (needed after editing ingest.py)

# 6. Make the first account — has to happen from a terminal; a signup endpoint
#    that could hand out the admin role would make the role meaningless
python auth.py add you@arihantcapital.com --admin    # prompts for a password twice

# 7. Run the API
uvicorn api:app --reload      # http://127.0.0.1:8000 — interactive docs at /docs
```

The first `/chat` request after a fresh server start pays an ~80-second import cost
(FAISS off disk, the Ollama embedder, LangChain's module tree) — `api.py` warms this
on a background thread at startup so it lands before the first real request rather
than in front of it, but a request that arrives inside that window still waits.

Optional CLI, no browser needed:

```bash
python cli.py login       # remembered in ~/.abot/token until /logout
python cli.py             # interactive REPL — /graph, /history, /whoami, /bye
python cli.py "what was the sensex close on 17 nov 2022"   # one-shot
```

### 2.3 Frontend setup (`frontend/`)

```bash
cd frontend
npm install

cp .env.example .env.local
# .env.local:
#   VITE_API_BASE_URL=http://127.0.0.1:8000
# (must match a CORS-allowed origin in model/api.py: localhost:3000, :5173, :8501)

npm run dev        # http://localhost:5173, hot-reloading
npm run build       # production bundle -> dist/
npm run lint        # ESLint, react-hooks v7 in React-Compiler-strict mode
npm run preview     # serve the built dist/ locally
```

Only `VITE_`-prefixed variables are exposed to the browser bundle — never put a
secret in the frontend `.env`.

### 2.4 Bringing it all up, in order

```
1. mongod                                  (or point MONGODB_URI at Atlas)
2. ollama serve
3. cd model && uvicorn api:app --reload    (http://127.0.0.1:8000)
4. cd frontend && npm run dev              (http://localhost:5173)
```

Open `http://localhost:5173`, register an account (or log in with the admin
account made in step 6 above), and start chatting.

### 2.5 CMOTS live-data sync (optional, separate concern)

The CMOTS subsystem (§4) syncs Arihant's own market-data feed into the `cmots`
Mongo database on a cron schedule via `apscheduler`. It runs as its own process,
independent of the chat API:

```bash
python cmots_scheduler.py
```

This is not required to run the chatbot — questions that would use CMOTS data
simply get whatever is already in the `cmots` database (or the scheduler can be
left off entirely in a dev setup that doesn't need live market data).

---

## 3. Backend: the RAG pipeline

### 3.1 Four answer tiers, in priority order

| Tier | Source label | What answers |
|---|---|---|
| 1 | `arihant` | The rating scale and firm boilerplate, parsed straight out of report headers/footers — a pattern match, not a model call |
| 2 | `documents` | The PDFs in `model/pdfs/`, retrieved via FAISS, cited `[1][2]` |
| 3 | `web` | DuckDuckGo search + page fetch, read when the documents come up empty |
| 4 | `general` | The model's own knowledge, always appended with a disclaimer |

Two question types never reach any of the four: a line that is *only* a greeting
(`TALK` patterns in `config.py`) is answered from a canned reply table before the
spellchecker even runs, and a question classified `OTHER` by the finance/not-finance
router (`SCOPE_TURNS`) gets one short redirect line instead of a web search.

CMOTS (`source: "cmots-ai"`) sits alongside these as a live-market-data tier — see §4.

### 3.2 Why the writer and the embedder use different models

`CHAT_MODEL` (default `gpt-5.6-luna`, via `OPENAI_MODEL`) writes every answer and
runs the two cheap "errand" calls (spelling autocorrect, in/out-of-scope routing) at
`CHAT_TEMPERATURE = 0.2` — those errands can be pointed at a cheaper model via
`OPENAI_SMALL_MODEL` since neither needs strong reasoning.

`EMBED_MODEL` stays pinned to Ollama's `nomic-embed-text`: the FAISS index on disk
was built with those vectors, and a query has to be embedded by the same model that
produced them. Switching `EMBED_MODEL` to an OpenAI embedding model requires
rebuilding the whole index (`python build.py`) before any search works again. The
switch away from a local Ollama chat model (`llama3.2:3b`) to OpenAI for the writing
half was a correctness fix, not a preference — the small local model was reading
numbers out of the wrong table cell and hallucinating fluently on scraped garbage;
OpenAI's model instead says "not in the documents" and lets the web lane answer.

### 3.3 Two lanes, started together

The documents lane (FAISS) and the web lane (DuckDuckGo) run on separate threads,
started at the same moment (`chain.both()`), not run one after the other. Both spend
nearly all their wall time inside an HTTP call with the GIL released, so running
them concurrently costs almost nothing extra. They are **not joined** — the
documents lane is authoritative when it has an answer, so the code returns as soon
as it resolves and leaves the web lane's daemon thread running unread. Only a
document miss ever waits on the web result. Measured saving: ~1.2–3.5s off an
11–17s web-or-general answer; a documents-tier answer is unaffected (it was never
waiting on the web lane anyway).

### 3.4 Follow-up questions

`history.recent_turns()` pulls the last `HISTORY_TURNS = 4` turns of the *current
session only* before anything searches. A small classifier regex (`FOLLOWUP_Q`)
decides whether a line leans backward ("and its rating?", "what about the nifty");
if it does, a rewrite prompt (`FOLLOWUP_TURNS`) turns it into a question that stands
alone, using the prior Q&A as context. The rewrite is stored beside the original
answer as `standalone` and is what every downstream stage (scope check, retrieval,
both lanes) actually searches against.

### 3.5 Ingestion mechanics (`ingest.py`)

- **Loading**: `load_folder()` uses LangChain/Unstructured's `DirectoryLoader` +
  `UnstructuredPDFLoader` with `mode="elements", strategy="hi_res",
  infer_table_structure=True, languages=["eng"]`. The torch/spacy import chain this
  pulls in is why the loader import is deferred inside the function — importing it
  eagerly would risk the double-OpenMP crash on the answering path (§10).
- **Table detection and rendering**: any element tagged `category == "Table"` is
  rebuilt from the PDF's own text layer via `pymupdf.find_tables()`
  (`pdf_tables()`/`text_layer_rows()`) rather than trusted from `hi_res`
  OCR/HTML — OCR was measured to destroy 174 of 179 rows on this corpus. If no
  text-layer match is found, it falls back to parsing the loader's `text_as_html`
  with a small regex stripper. Header rows that visually span two physical rows
  are merged (`merge_header()`), and every data row is rewritten as `"Column
  Name: value"` labels (`label_rows()`) before being joined into pipe-delimited
  text (`"a | b | c"`) — never left as raw HTML.
- **Table captions**: `caption(rows)` builds `"Table with columns: {headers}.
  Rows: {label1, label2, ...}."` from the first two header-ish rows plus each
  row's first-cell label (2–40 chars, not purely numeric, deduped, capped at 14
  labels), prepended to the rendered table text. This caption is what makes an
  otherwise-numeric table embeddable at all — digits alone embed near nothing.
- **Dates**: two independent layers. A **table's own date**
  (`table_date(rows)`, regex `DD-Mon-YY` read from the header row before it gets
  consumed by header-merging) takes priority over the **filename's date**
  (`date_from_filename()`, parsing `"17th Nov 2022.pdf"`-style names or ISO). The
  final `tag()` step sets `metadata["date"] = printed_date or published` and
  always keeps `metadata["published"] = date_from_filename(...)` — a reco table
  can legitimately be several trading days behind the report it ships inside, so
  the two dates are tracked separately rather than assumed equal.
- **Chunking**: prose sections are split with LangChain's
  `RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)`
  (`CHUNK_SIZE`/`CHUNK_OVERLAP` in `config.py`). **Tables are never run through
  this splitter.** An oversized table is instead cut by whole rows
  (`split_tables()`) once its token count — measured with `tiktoken`'s
  `cl100k_base` encoding — exceeds 90% of `EMBED_TOKEN_LIMIT = 2048` (i.e. a
  budget of 1843 tokens, since Ollama's `nomic-embed-text` silently truncates
  anything longer). Each split piece gets its **own** caption rebuilt from only
  that piece's own rows — an earlier version of this copied the whole table's
  original caption onto every piece unchanged, so a piece containing Ambuja
  Cement and Maruti Suzuki still claimed to contain Axis Bank and HDFC Bank,
  polluting literal-phrase matches for the wrong companies.
- **Sectioning & stitching**: a `"Title"` element starts a new prose section;
  subsequent non-table elements are glued on until the next title. A
  `NarrativeText` element split across a page boundary is re-joined
  (`prepare()`) if the previous fragment doesn't already end in sentence-ending
  punctuation. `JUNK = {"Header", "Footer", "PageNumber"}` elements are dropped
  entirely.
- **Per-chunk metadata**: `chunk_id` (`"{source}#{i}"`), `source` (PDF filename),
  `published`, `date`, `pages` (PDF page numbers), `category`, and `table_part`
  (`"i/n"`) for split-table pieces.

### 3.6 Retrieval mechanics (`retrieve.py`, `store.py`)

- **Embedding & index**: `store.py` embeds with `OllamaEmbeddings(model=
  "nomic-embed-text")` and builds a FAISS index via `FAISS.from_documents(...)`,
  saved to `model/index/`. Raw parsed PDF *elements* (pre-chunking — the
  expensive step) are cached at `model/.cache/elements.pkl`, keyed by a
  fingerprint of every PDF's `(filename, size, mtime)` — the cache is all-or-
  nothing, so adding one new PDF still re-parses the whole folder once. The
  built index is loaded as a process-wide singleton on first use and raises with
  a clear "run build.py" message if `index/index.faiss` doesn't exist yet.
- **Similarity search**: `search()` calls `store.similarity_search(question,
  k=TOP_K)` with **`TOP_K = 4`**.
- **The date filter fix**: when a question names a date, `search()` passes
  `filter={"date": date}` **and** `fetch_k=store.index.ntotal` (the *entire*
  index size). This matters because FAISS cannot search inside a metadata
  subset — LangChain fetches `fetch_k` nearest neighbours over the whole index
  first and drops filter mismatches afterward, and LangChain's own default
  `fetch_k=20` was silently starving the filter on this near-duplicate-heavy
  corpus (the 20 nearest neighbours to a Sensex question came from nine
  different days; only 2 survived the date filter, and the right table was
  never among them). Setting `fetch_k` to the full index size guarantees every
  same-day chunk is actually considered.
- **Literal rescue**: `literal(pool, question, want=RESCUE_K)` with
  **`RESCUE_K = 2`** adds chunks containing an exact phrase from the question —
  dense embedding similarity alone cannot find "Axis Bank" sitting inside four
  columns of digits, but a literal substring match can. It tokenizes the
  question into unigrams/bigrams (dropping generic finance stopwords like
  "price" or "target" that would match nearly every chunk uselessly), keeps only
  grams that hit between 1 and `max(3, chunk_count // 40)` chunks (too common =
  meaningless, zero hits = irrelevant), and returns the top 2 by match count.
  Rescued chunks are deduplicated against the similarity-search results and
  **prepended** to the final list — a model handed the right table 6th out of 6
  chunks was observed to fail where the same table 1st out of N succeeded.

### 3.7 The web lane (`web.py`)

`search(query)` runs a DuckDuckGo text search via the `ddgs` package
(`max_results = WEB_RESULTS = 3`), fetches each result page with LangChain's
`WebBaseLoader`, cleans the text, and truncates to `WEB_CHARS = 2000` characters
per page. Any failure — a bad fetch, a dead search — is swallowed and simply
yields fewer or zero pages rather than raising, since a chat turn must never die
because DuckDuckGo timed out.

### 3.8 Chain wiring & the gating functions (`chain.py`)

The whole file is composed with LangChain Expression Language (LCEL): almost
every stage is `RunnablePassthrough.assign(key=RunnableLambda(fn))`, threading
one accumulating dict (`question → fixed → standalone → docs/doc_answer →
web_answer → ...`) through the `|` pipe operator so no stage loses what an
earlier stage computed.

**Router order** (first match wins, evaluated top to bottom): a pure-greeting
match (`small_talk`, checked once before and once after autocorrection) → the
`arihant` boilerplate check (`RATING_Q`/`FIRM_Q` regexes against parsed report
text, not retrieval) → `cmots_ai_answer()` (§4 — checked *before* the scope
gate) → the `in_scope()` finance/not-finance classifier (a miss here becomes
`soft_refuse`, `source: "out of scope"`) → finally `both()` (the parallel
doc+web lanes) followed by `route()`.

**`route()`** always prefers a grounded documents answer over a grounded web
answer when both exist by the time it runs — not a fallback order, a genuine
choice between two already-finished drafts, which is only possible because
`both()` started both lanes concurrently rather than sequentially.

**Gating functions**, applied to both the documents and web drafts:

- `grounded(answer, context, floor=0.35)` — tokenizes the answer, computes what
  fraction of its words appear literally in the retrieved context, and requires
  ≥0.35. Calibrated against real answers: genuinely grounded replies scored
  0.58–0.83 on this corpus; a hallucinated answer scored 0.18. Applied to *both*
  lanes deliberately — gating only the documents lane would just relocate a
  hallucination to the web branch and cite it there instead of catching it.
- `doc_verdict()` accepts a documents-tier answer only if it (a) passed
  `answered()` — non-empty, doesn't contain the `NOT_IN_DOCS` sentinel, at least
  4 words, and doesn't open with a hedge phrase from `HEDGES` (a list expanded
  more than once after politer models phrased a refusal as an observation — "I
  don't see Axis Bank's information" — that still looked like a normal cited
  answer); (b) passes `grounded()`; and (c) is not a case of
  `wants_description()` being true while every cited chunk (parsed out of the
  answer's own `[n]` markers) is a `Table` category chunk. That third check is
  the fix for "what is Bandhan Bank" being answered out of a reco-table row —
  the sentence was fully grounded in the context, so nothing about *groundedness*
  could catch it; only knowing that the question wanted a description and every
  citation was a table row could.
- `wants_description(question)` is `DESCRIBE_Q` matched (question opens with
  "what is/who is/tell me about/describe/explain/introduce") **and** `METRIC_Q`
  *not* matched (no metric word like price, target, rating, upside, close, P/E,
  or `%` present) — the metric vocabulary is the entire difference between "what
  is Bandhan Bank" (wants a description) and "what is Bandhan Bank's target
  price" (wants a table cell).

The `history._CURRENT` `ContextVar` (§8, step 3) and the daemon-thread mechanics
of `both()` (§3.3) are the two concurrency primitives that make all of the above
safe to run for two different users' requests inside the same FastAPI worker
process at once.

### 3.9 What was actually fixed (see `model/README.md` for full detail)

These are documented in depth in the backend's own README and are summarized here
because they explain *why* the pipeline looks the way it does:

- **The FAISS date filter was silently discarding correct answers** — LangChain
  applies a metadata filter *after* fetching `fetch_k` nearest neighbours, and the
  default `fetch_k=20` wasn't enough on a corpus of near-identical daily reports.
  Raising `fetch_k` to the full index size took recall on dated market-data
  questions from 3/20 to 11/20.
- **Dense embedding search cannot find a company name inside a table of numbers.**
  `retrieve.py`'s "literal rescue" (`RESCUE_K = 2`) adds chunks that contain the
  exact phrase being searched for, on top of the `TOP_K = 4` similarity results.
- **Tables must never be handed to the model as raw HTML** — `ingest.py` renders
  every table as pipe-delimited rows (`a | b | c`) with a generated caption naming
  its columns and rows, which is also what makes a table of digits embeddable at
  all (digits alone embed near nothing; a caption gives them semantic content).
- **A sentence built entirely out of table cells is not a description.**
  `doc_verdict()` reads which chunks an answer actually cited and declines to
  answer a "what is X" question if every citation is a `Table` category chunk —
  `wants_description()` vs. `METRIC_Q` is what tells "what is Bandhan Bank" (declines,
  falls to the web lane) from "what is Bandhan Bank's target price" (answers from the table).
- **PDFs are parsed natively, not OCR'd** — every PDF here is a digital, born-text
  document, so `pdf_tables()` reads tables with `pymupdf.find_tables()` rather than
  rasterizing pages and running OCR over the image, which had shredded 174 of 179
  table rows in an earlier version of the pipeline.

---

## 4. Backend: the CMOTS market-data subsystem

CMOTS is Arihant's own **licensed vendor data feed** — not scraping — reached at
`CMOTS_BASE_URL = "https://cmotsnew.arihantcapital.com"` over an IP-whitelisted
connection with no API key. It covers equities, mutual funds, IPOs, world
indices, and FII/DII flow, mirrored into its own `cmots` MongoDB database
(separate from the chat history database `abot`) on a cron schedule.

### 4.1 The data sources — `cmots.py`, `cmots_mf.py`, `cmots_ipo.py`

All three call a shared `_get()` helper in `cmots.py` against one REST base.
Every endpoint returns the envelope `{"success", "data", "message"}`; `_get()`
retries `CMOTS_RETRIES = 3` times with doubling backoff (`CMOTS_RETRY_BACKOFF_S
= 2` → 2s, 4s, 8s) on connection errors, 5xx responses, or malformed JSON, then
raises. A `success: false` body raises immediately unless the message says "no
data," which is treated as a legitimate empty result rather than a failure —
this module does **not** swallow errors the way `web.py` and `history.py` do,
since it runs out-of-band in the scheduler rather than on a live chat turn, and
a silently-missing sync is worse than a loud one.

- **`cmots.py`** — equities. Bulk endpoints: company master, EOD bhav copy per
  exchange, corporate actions, results calendar, daily announcements, a news
  archive (by section and date range), stock-wise news (batched ≤10 company
  codes/call), FII/DII cash-market activity, world indices. Per-company
  endpoints (looped over the whole active universe): profile, board of
  directors, "about," shareholding pattern, key stats, financial ratios,
  quarterly/yearly results, yearly balance sheet, key financials (peer group),
  and historical price backfill.
- **`cmots_mf.py`** — mutual funds, reusing `cmots._get`. Mostly bulk (scheme
  master, scheme returns, risk factors, dividend details, AUM growth — one call
  returning roughly 140,000 rows — market activity, NFOs, portfolio activity,
  category master). Per-scheme: peer comparison and NAV history.
- **`cmots_ipo.py`** — roughly 150 IPOs total. Bulk: IPO master, calendar
  (upcoming/open/closed), recently-listed performance, draft prospectuses.
  Per-IPO: details, financials, synopsis, strengths, risks, peers.

### 4.2 Storage — `cmots_store.py`

Connects via `CMOTS_MONGO_URI` (falling back to `MONGO_URI`, then to
`mongodb://localhost:27017` — deliberately *not* left empty like the chat
history connection, since CMOTS data shouldn't wait on an Atlas URI being
configured). Database name `CMOTS_DB` (default `"cmots"`). On first use it
lazily creates roughly 30 collections with unique/secondary indexes —
`company_master` (unique `co_code`, plus name/symbol lookup indexes),
`prices_eod` (unique `co_code`+`date`), `corporate_actions`, `results_calendar`,
`news` (unique `Sno`), `keystats`, `financial_ratios`, `key_financials`,
`company_profile`, `shareholding_pattern`, `results_quarterly`/`yearly`,
`balance_sheet_yearly`, `fii_dii_activity`, `world_indices`, plus mirrored
`mf_*` and `ipo_*` collections.

Every write goes through one `_bulk_upsert(collection, rows, key_fn)` helper —
`UpdateOne(key, {"$set": row}, upsert=True)` in an unordered bulk write, keyed
by a natural business key (e.g. `{co_code, date}` for a price row) — so a
re-run of any sync job is idempotent rather than accumulating duplicates.
Writes are allowed to raise (surfacing staleness to the scheduler); reads
(`get_company`, `latest_price`, etc.) are fail-open, returning `None`/`[]` if
MongoDB is unreachable so a chat turn degrades instead of erroring. Company/
scheme/IPO name lookup is a three-tier match: exact numeric id, then exact
symbol/ISIN or a regex substring, then a fuzzy match (`difflib.get_close_matches`,
cutoff 0.6) over a 10-minute-cached name list — the fuzzy tier exists so a
typo'd company name still resolves without loading every row on every lookup.

### 4.3 The sync scheduler — `cmots_scheduler.py`

A standalone process (`python cmots_scheduler.py`), entirely independent of the
chat API — the chatbot only ever reads through `cmots_store.py`. Each job is
wrapped so one job's failure is logged and skipped rather than fatal to the
whole process.

| Cron | Time | What runs |
|---|---|---|
| `CMOTS_BULK_EOD_CRON` | 23:45 | ~20 bulk jobs: company master, prices, corporate actions (30-day window), results calendar, the full MF bulk set, the full IPO bulk set, FII/DII, world indices |
| `CMOTS_PER_COMPANY_CRON` | 00:30 | Per-company fundamentals (keystats/ratios/key-financials/profile/shareholding/results/balance-sheet), each fetch type run through a `ThreadPoolExecutor(max_workers=CMOTS_WORKERS=10)` over every active company code; also IPO per-company sync and stock-wise news |
| `CMOTS_MF_PER_SCHEME_CRON` | 01:00 | Per-scheme MF peer comparison + NAV history, and per-company stock-holders — offset from 00:30 so the two thread pools never compete for the same cores |
| `CMOTS_NEWS_CRON_MINUTES` | every 20 min | News/announcements polling over a rolling 30-day window ("as and when updated" is a polled reality, not a push) |

CLI flags: `--once` runs every job once and exits; `--backfill-prices [days]`
does a one-time historical price pull (default 365 days).

### 4.4 The AI layer — `cmots_ai.py`

`cmots_ai_answer(question)` is the single entry point the chat pipeline calls.
It resolves a question in **two LLM calls**:

1. **Planner** — a cheap model (`SMALL_MODEL`, `temperature=0,
   reasoning_effort="none"` — reasoning models reject tool calls at a default
   reasoning effort on the chat-completions endpoint, hence forcing it off)
   bound to two tools: `query_cmots` (look up one company/scheme/IPO/index by
   name plus a list of fields drawn from the fixed 30+-field vocabulary in
   `CMOTS_FIELDS`) and `web_search` (only for something CMOTS genuinely cannot
   supply). **If the planner calls neither tool, `cmots_ai_answer` returns
   `None`, unconditionally** — it never lets the planner answer from its own
   knowledge, however reasonable-sounding, because scope is decided exclusively
   by the dedicated `in_scope()` classifier that runs later in `chain.py`. A
   finance definition question ("what does P/E mean") costs one extra hop
   through that pipeline instead of ever being answered here — a deliberate
   trade against letting a small model's own judgment gate what's in scope.
2. **Writer** — the main `CHAT_MODEL` turns the fetched CMOTS data (and any web
   extracts) into prose via `CMOTS_AI_WRITER_PROMPT`. If the reply contains the
   sentinel `NOT_ON_CMOTS = "NO CMOTS ANSWER"` (case-insensitive) or is empty,
   the writer step returns `None` too.

**Caching, and the confirmed source of non-determinism**: `cmots_ai.py` keeps
two plain module-level dicts — `_answers` (semantic key → `{value, expires_at}`)
and `_aliases` (normalized question text → semantic key, so an exact repeat
question costs zero model calls). The semantic key is `(companies, fields,
touched_web, web_query)` — sorted company names requested, sorted union of
fields, whether a web call happened, and the literal web query string. TTL for
a pure `query_cmots` answer is the time until the *next* scheduled CMOTS sync
(no point refreshing faster than the data itself refreshes); an answer that
touched the web instead gets `CMOTS_AI_WEB_CACHE_TTL_S = CMOTS_NEWS_CRON_MINUTES
* 60` = 20 minutes, matching the news poll cadence.

Because these dicts are **pure in-process memory, never persisted**, every
process restart (or a second worker process) starts with an empty cache — the
same question triggers a fresh planner+writer call, and since the writer is not
run at temperature 0, that fresh call can phrase the answer completely
differently from a previous run. This was measured directly: the same question
produced 87-, 311-, and 650-character answers across three separate process
runs. It also means answer wording within one process's lifetime depends on
whichever phrasing happened to establish a given cache key first — a
semantically identical but differently worded later question either reuses
that wording verbatim (cache hit) or triggers a fresh, possibly different
answer (a new key). **Practical consequence: a CMOTS answer that looks short,
inconsistent, or "wrong" is not automatically a frontend bug — check the actual
stored `messages` document in MongoDB for what was really generated before
assuming the client mishandled it.**

### 4.5 How `chain.py` decides to use CMOTS at all

There is **no keyword pattern** for CMOTS comparable to the `RATING_Q`/`FIRM_Q`
regexes that gate the `arihant` tier. The router's condition is simply: call
`cmots_ai_answer()` on the follow-up-resolved question (falling back to the raw
question if that returns nothing); if either call returns a non-`None` answer,
wrap it with `source: "cmots-ai"` and stop — this check runs **before** the
`in_scope()` gate and before the parallel documents/web lanes. Routing to CMOTS
is therefore entirely a consequence of the planner's own tool-call decision
inside `cmots_ai.py` (§4.4), not a separate classifier in the main chain.

---

## 5. Backend: accounts, tokens, roles

### 5.1 Passwords

- Hashed with **bcrypt directly** (`bcrypt.hashpw` / `bcrypt.checkpw`), not
  `passlib` — `passlib`'s bcrypt backend reads `bcrypt.__about__`, which bcrypt 4.x
  removed, so that pairing raises on the very first hash.
- `BCRYPT_ROUNDS = 12` (~250ms per verify) — the point of that cost is to make a
  stolen hash expensive to run a wordlist against.
- Minimum length 8 (`PASSWORD_MIN_LEN`), maximum 72 **bytes** — bcrypt silently
  truncates and ignores anything past 72 bytes, which would make two different
  long passwords equivalent; `auth.py` rejects instead of truncating.
- The plaintext password is never written anywhere — not to MongoDB, not to a log.

### 5.2 Tokens

- Signed JWTs (`PyJWT`, algorithm `HS256`), stateless — verifying one is a
  signature check, not a database round trip on every request.
- Claims: `sub` (account UUID, not email — so changing an email never orphans the
  conversations that id owns), `email`, `role`, `iat`, `exp`.
- `JWT_TTL_MIN` (default 720 = 12h) controls lifetime. **The role in the token is
  never trusted for authorization** — `user_for_token()` looks the account back up
  by `sub` on every request, so a demotion or a disable takes effect immediately
  rather than waiting for the token to expire.
- If `JWT_SECRET` is unset, the process invents one with `secrets.token_urlsafe(48)`
  at import time — every token then dies with the process, so a restart logs
  everyone out. `api.py` prints this at startup.

### 5.3 Roles

Two roles only: `user` (reads and writes only their own conversations) and `admin`
(the old team-wide view, now gated behind `/admin/*` routes and CLI `--all`).
Promotion is **CLI-only** (`python auth.py role <email> admin`) — there is no HTTP
route that can grant the admin role, on the reasoning that a signup form which
could hand out admin would make the role meaningless. The first account on a fresh
install therefore has to be created from a terminal:

```bash
python auth.py add you@arihantcapital.com --admin
python auth.py list
python auth.py role someone@arihantcapital.com admin
python auth.py disable someone@arihantcapital.com   # revokes access, keeps history
```

Disabling an account (`disabled: true`) revokes access without deleting anything —
deleting the user document would orphan every conversation it owns. An admin can
never demote or disable themselves via the API (`/admin/users/{email}/role` and
`/disable` both special-case "yourself"), since that could leave an install with no
admin able to reverse it short of a direct database edit.

---

## 6. MongoDB data model

Two logically separate databases are involved. `abot` is this chatbot's own
history; `cmots` is Arihant's market-data mirror and is not written by the chat
pipeline (only read from, when a question routes to the CMOTS tier).

### 6.1 The `abot` database — three collections, one relationship

```
users  ──1:N──<  conversations  ──1:N──<  messages
```

`conversations` joins to `users` on **`user_id`**. `messages` joins back to
`conversations` on **`session_id`**, *not* `conversation_id` — this is a real
naming trap: the field is called `session_id` in `messages` but corresponds to
`conversations._id`.

No collection is created by a setup script — `history.db()` creates all indexes
idempotently the first time any process successfully connects.

#### `users`

| field | type | notes |
|---|---|---|
| `_id` | string (uuid4 hex) | the account id; used as `sub` in JWTs |
| `email` | string | stored lowercased; **unique index** |
| `name` | string | defaults to the local part of the email |
| `password_hash` | string | bcrypt hash — never the plaintext |
| `role` | `"user" \| "admin"` | |
| `created_at` | datetime (UTC) | |
| `last_login_at` | datetime (UTC) \| null | updated on every successful login |
| `disabled` | bool | revokes access without deleting history |

Index: `email` (unique).

#### `conversations`

| field | type | notes |
|---|---|---|
| `_id` | string (uuid4 hex) | the session id |
| `user_id` | string \| null | owner; **null for anonymous/unowned runs** (pre-auth history, or CLI use without login) |
| `user` | string | display label — an email if owned, `user@hostname` if not |
| `title` | string | the opening question, truncated to 120 chars |
| `turns` | int | incremented via `$inc` on every saved turn |
| `tags` | array | |
| `models` | object | `{chat, small, embed}` model names in effect when the conversation started |
| `interface` | string | `"cli"` or `"api"` |
| `started_at` | datetime | set once via `$setOnInsert` |
| `last_at` | datetime | updated on every turn |

Indexes: `(last_at desc)` (`recent`), `(user asc)` (`by_user`), `(user_id asc,
last_at desc)` (`owner` — a compound index, ordered so it serves both "my
conversations, newest first" and "my conversations" from the same index prefix).

#### `messages`

| field | type | notes |
|---|---|---|
| `_id` | string | `"{session_id}-{seq:04d}"` |
| `session_id` | string | joins to `conversations._id` |
| `seq` | int | 1-based turn number within the conversation |
| `ts` | datetime | |
| `user` | string | display label, duplicated from the conversation |
| `user_id` | string \| null | **duplicated from the conversation, deliberately** — see below |
| `question` | string | the raw question as typed |
| `fixed` | string \| null | after spelling/punctuation autocorrect |
| `standalone` | string \| null | the follow-up rewrite, if this question leaned on prior turns |
| `answer` | string \| null | |
| `source` | string \| null | `documents` \| `web` \| `general` \| `arihant` \| `cmots-ai` \| `small talk` \| `out of scope` |
| `date_filter` | string \| null | the date the retrieval filter locked onto, if any |
| `chunks` | array of string \| null | chunk ids the answer was built from |
| `pdfs` | array of string | distinct source PDF filenames behind the answer |
| `urls` | array of string | URLs behind a web-sourced answer |
| `timing_ms` | object | `{doc, web, total}` — per-lane wall time |
| `error` | string \| null | present when the chain raised; the question is still saved |

Indexes: unique `(session_id asc, seq asc)` (`session_seq` — a retry writing the
same turn twice fails as a duplicate key rather than silently doubling the
transcript), `(ts desc)` (`recent`), `(source asc, ts desc)` (`by_source`), a
**text index** over `(question, answer)` (`search` — MongoDB allows only one text
index per collection, so it has to cover both halves of a turn), `(user_id asc, ts
desc)` (`owner`).

**Why `user_id` is duplicated onto every message** instead of living only on the
conversation: MongoDB's text index cannot span a `$lookup`/join. Scoping a text
search ("find my questions about sensex") to one person's turns has to be
answerable from the message document alone, or it would require listing all of a
person's conversation ids first and then filtering — the duplication is a
deliberate denormalization, not an oversight.

**Ownership scoping is centralized in one function**, `history._scope(owner,
admin)` — every read in `history.py` builds its MongoDB filter by calling this
first. An admin gets `{}` (no filter, sees everything); anyone else gets
`{"user_id": owner}`; a caller that passes neither `owner` nor `admin=True` gets a
`PermissionError` rather than a query that defaults to "everything" — a scoping bug
here fails closed, not open.

Rows written before accounts existed at all have no `user_id` (they were stamped
with `getpass.getuser()@socket.gethostname()`, not an account), so they match no
owner filter and are **admin-only** by construction — not because of a special
case, but simply because `{"user_id": someone}` never matches a null field.

### 6.2 The `cmots` database

Arihant's live market-data mirror — equities, mutual funds, IPOs, world indices,
FII/DII flow — synced by `cmots_scheduler.py` on the cron cadence detailed in
§4.3. Around 30 collections total, each keyed by a natural business key and
upserted idempotently (`cmots_store._bulk_upsert`, §4.2): `company_master`
(unique `co_code`), `prices_eod` (unique `co_code`+`date`), `corporate_actions`,
`results_calendar`, `news` (unique `Sno`), `keystats`, `financial_ratios`,
`key_financials`, `company_profile`, `shareholding_pattern`,
`results_quarterly`/`results_yearly`, `balance_sheet_yearly`,
`fii_dii_activity`, `world_indices`, and the mirrored `mf_*` (scheme master,
returns, risk, dividends, AUM, NAV history, peer comparison) and `ipo_*`
(master, calendar, details, financials, synopsis, strengths, risks, peers)
collections. This database is **read-only from the chatbot's perspective** —
only `cmots_scheduler.py` writes to it; `cmots_ai.py` only ever calls
`cmots_store.py`'s read functions.

### 6.3 Operational fragility — read before running any destructive command here

This runs on a **standalone `mongod`** in the reference dev setup: no replica set,
therefore no oplog, and no filesystem snapshots configured. **There is no way to
undo a bad `delete_many` on this database.** Always read a document back and match
an expected count before deleting anything. A prior incident wiped all 17
conversations and 21 messages on this project by querying `{"owner": ...}` — a
field that does not exist on the stored document (the real field is `user_id`;
`owner` is only a *keyword argument name* that `history._scope`/`recent`/
`transcript` translate internally) — which matched nothing, and when the logic was
inverted to find "orphans", it silently classified every real conversation as
orphaned.

---

## 7. The HTTP API

Base URL in local dev: `http://127.0.0.1:8000`. Interactive schema at `/docs`
(FastAPI's generated Swagger UI). Every route except `/health`, `/auth/register`,
and `/auth/login` requires `Authorization: Bearer <token>`.

| Method & path | Auth | Body / query | Returns |
|---|---|---|---|
| `GET /health` | none | — | `{ok, mongodb}` |
| `POST /auth/register` | none | `{email, password, name?}` | `Token` — registers **and logs in**, always role `user` |
| `POST /auth/login` | none | `{email, password}` | `Token` |
| `GET /auth/me` | bearer | — | `Account` |
| `POST /auth/password` | bearer | `{password}` | 204 — changes only the caller's own password (no email field; the token already says whose) |
| `POST /chat` | bearer | `{question, conversation_id?}` | `Answer` |
| `GET /conversations` | bearer | `?limit=20` (max 100) | `Conversation[]`, newest first, caller's own |
| `GET /conversations/{id}` | bearer | — | `Turn[]`, 404 if not found **or not the caller's** (same status either way — the API cannot be used to enumerate ids) |
| `GET /search` | bearer | `?q=&limit=20` | `Turn[]` — the caller's own turns, whole-word text match |
| `GET /admin/users` | admin | `?limit=100` | `Account[]` |
| `GET /admin/conversations` | admin | `?limit=50` | `Conversation[]`, everyone's |
| `GET /admin/conversations/{id}` | admin | — | `Turn[]`, any conversation |
| `POST /admin/users/{email}/role` | admin | `?role=` | 204 — cannot demote yourself |
| `POST /admin/users/{email}/disable` | admin | `?disabled=true` | 204 — cannot disable yourself |

### Response shapes

```jsonc
// Token — from /auth/register and /auth/login
{ "access_token": "...", "token_type": "bearer", "expires_in": 43200, "user": { "id", "email", "name", "role", "created_at", "last_login_at" } }

// Answer — from /chat
{
  "answer": "...",
  "source": "documents",          // documents | web | general | arihant | cmots-ai | small talk | out of scope | null
  "conversation_id": "a1b2c3...",
  "seq": 3,
  "standalone": "What was the Nifty close on 10 May 2022?",  // null if not a follow-up rewrite
  "pdfs": ["10th May 2022.pdf"],
  "urls": [],
  "took_ms": 2214
}

// Turn — from /conversations/{id} and /search
{ "seq": 1, "ts": "2026-08-10T09:00:00Z", "question": "...", "answer": "...", "source": "documents" }

// Conversation — from /conversations
{ "id": "a1b2c3...", "title": "what was the sensex close...", "turns": 3, "started_at": "...", "last_at": "...", "interface": "api" }
```

### Design decisions worth calling out

- **No streaming, no SSE.** `/chat` is a single blocking `POST`. Any "live
  thinking" UI has to be fabricated client-side during the wait and then
  reconciled against the `source` field once the real response lands — see §9.5.
- **The `Turn` model is narrower than the stored `messages` document.** The API
  exposes only `{seq, ts, question, answer, source}`; the database also holds
  `pdfs`, `urls`, `standalone`, `timing_ms`, `chunks`, `error`. Practical
  consequence: reopening a past conversation through `GET /conversations/{id}`
  returns no citations — the frontend has to cache citations client-side
  (`sessionStorage`) at the moment an answer first arrives, because they cannot be
  recovered later from the API. Similarly `GET /search` results carry no
  `session_id`, so a search hit cannot be navigated to its conversation.
- **`conversation_id` is never trusted blindly.** `Session.resume()` checks
  `row["user_id"] == account["_id"]` before continuing a conversation; a guessed
  id belonging to someone else raises `PermissionError`, which the route turns
  into the same 404 used for "doesn't exist" — the API gives no signal that would
  let someone enumerate valid conversation ids.
- **No server-side session state.** A conversation is just a database row with an
  id, and the client is responsible for sending that id back on the next turn.
  This means two `uvicorn` workers, a mid-chat restart, or the same account open
  in two browser tabs all behave correctly — there is nothing in server memory to
  lose or to conflict.
- **`/chat` is a synchronous `def`, not `async def`**, on purpose. `chain.ask` is
  slow (model calls, FAISS, a web fetch) and blocking; FastAPI runs plain `def`
  route handlers in a thread pool, so one person's slow question does not stall
  the event loop for everyone else's `/health` or `/auth/login`. The per-request
  conversation context is carried into that worker thread via a `contextvars.ContextVar`
  (`history._CURRENT`), which `anyio` propagates automatically — this is what lets
  two concurrent requests each resolve their own follow-up questions against their
  own history instead of racing on a shared global.

---

## 8. The complete flow of one chat turn

Walking one question ("what was the sensex close on 10 may 2022", followed by
"and the nifty?") end to end, backend included:

1. **Frontend** sends `POST /chat` with `{question, conversation_id}` (omitted on
   the very first message) and an `Authorization: Bearer <token>` header.
2. **`api.py`** resolves the bearer token to an account (`auth.user_for_token`,
   401 if missing/expired/invalid), then either starts a new `history.Session` or
   resumes an existing one after verifying ownership.
3. `history.use(session)` publishes that session onto the request's `ContextVar`
   so everything downstream in `chain.py` can read "the conversation so far"
   without being handed it explicitly.
4. **Follow-up rewrite**: `history.recent_turns(4)` pulls the last four turns of
   *this session only*. If the question matches the "leans backward" pattern
   (`FOLLOWUP_Q`) — true for "and the nifty?" — a small-model call
   (`FOLLOWUP_TURNS`) rewrites it into a standalone question ("What was the Nifty
   close on 10 May 2022?"), reusing the date the prior turn established. The
   rewrite is stored as `standalone` and is what every stage below actually acts on.
5. **Spelling/punctuation autocorrect** runs on the (possibly rewritten) line.
6. **Small-talk / scope gate**: a pure greeting short-circuits to a canned reply
   before this point; a non-finance question is classified `OTHER` here and gets a
   short redirect instead of continuing.
7. **Two lanes start together** on separate threads: the documents lane embeds the
   question with Ollama's `nomic-embed-text`, searches FAISS (`TOP_K=4` +
   `RESCUE_K=2` literal-match chunks, date-filtered if the question named one), and
   asks the chat model to answer strictly from those chunks; the web lane
   simultaneously runs a DuckDuckGo search, fetches `WEB_RESULTS=3` pages, and asks
   the chat model to answer from those extracts. Both are started; only a document
   miss ever waits on the web lane's result.
8. **Grounding + citation-category checks** run on the documents lane's draft
   answer (`grounded()`, `doc_verdict()`, `wants_description()` vs. `METRIC_Q`) —
   an answer built only from table-row citations is rejected for a "what is X"
   question even if every word in it appears in the context.
9. The router picks the highest-priority tier that actually produced a usable
   answer: `arihant` boilerplate → `documents` → `web` → `general` (with a
   disclaimer appended). CMOTS is checked as its own tier for live market-data
   questions (§4).
10. **`session.save()`** writes one `messages` document with the full working
    state (`question`, `fixed`, `standalone`, `answer`, `source`, `chunks`, `pdfs`,
    `urls`, per-lane `timing_ms`) and upserts the parent `conversations` row
    (`$inc` turn count, `$set` last-active timestamp) — **after** the answer has
    already been computed, so a slow or unreachable MongoDB never delays or breaks
    the reply itself; it only means that turn goes unlogged.
11. **`api.py`** builds the `Answer` response (`pdfs`/`urls` deduplicated straight
    out of the chain's return value, `took_ms` timed independently in the route
    handler) and returns it as one JSON blob — nothing is streamed.
12. **Frontend** receives the full answer in one round trip. Because there was no
    incremental signal during the wait, the "thinking / searching…" activity trace
    the user saw during that time was entirely client-fabricated (§9.5); on
    response arrival the frontend reconciles that trace against the real `source`
    value, renders the markdown/table answer, and caches citations
    (`pdfs`/`urls`) into `sessionStorage` keyed by conversation, since a later
    `GET /conversations/{id}` call will not return them.

---

## 9. Frontend architecture

### 9.1 High-level structure

```
frontend/src/
├── api/            per-resource HTTP clients (auth.api.js, chat.api.js) over a shared
│                   client.js, a typed ApiError, and config.js reading VITE_API_BASE_URL
├── app/            AppShell (signed-in shell) and AuthGate (anonymous vs. authenticated switch)
├── context/        Context API providers — auth/, chat/, theme/ — no prop drilling, no Redux
├── components/     shared primitives: ui/ (Button, TextField, PasswordField, Checkbox,
│                   Alert, Avatar, Icon, Spinner, Tooltip), brand/ (Logo), theme/ (ThemeToggle)
├── features/       feature-scoped UI: auth/ (screen, forms, validation), chat/ (screen,
│                   activity trace, citations, composer, history panel, search palette,
│                   markdown renderer), account/ (user menu, sign-out dialog)
├── hooks/          cross-feature hooks (useClickOutside)
├── lib/            markdown/ (hand-rolled parser — no external markdown library, per the
│                   vanilla-only constraint) and storage.js (localStorage/sessionStorage helpers)
└── styles/         cascade-layer design tokens: reset → tokens → base → layout →
                    components → utilities (later layers win regardless of specificity)
```

State is shared exclusively via three Context providers (`AuthProvider`,
`ChatProvider`, `ThemeProvider`) — there is no Redux, Zustand, or prop-drilled
state anywhere in the tree. All styling is plain `.css` with custom properties;
there is no Tailwind, CSS-in-JS, or component library anywhere in the codebase.
**There is no router library** (no react-router) — navigation is manual
state-based gating, on the reasoning that the app has exactly two states
(signed out, signed in) and a conversation is not a place you navigate *to*, it's
the thing that's already there once you're in.

### 9.2 App bootstrap

- **`main.jsx`** imports `styles/index.css` before any component — it declares
  the cascade `@layer` order, which every component stylesheet depends on being
  established first. Provider nesting is `ThemeProvider > AuthProvider > App` —
  theme is outermost because the auth screens need the theme toggle, and theme
  never needs to know about auth.
- **`App.jsx`** is `AuthGate > ChatProvider > AppShell`. `ChatProvider` sits
  *inside* the gate deliberately: signing out unmounts the whole subtree, so the
  active conversation, history list, and any in-flight request are torn down
  automatically with no manual cleanup code.
- **`AuthGate.jsx`** reads `status` from `useAuth()` — `loading` shows a
  `BootScreen` (its spinner is delayed 200ms so a near-instant session restore
  never flickers one), `anonymous` renders `AuthScreen`, anything else renders
  the authenticated app.
- **`AppShell.jsx`** is the signed-in shell: a fixed top bar (`Logo` + tagline +
  `UserMenu`) over a `<main>` hosting `ChatScreen`, sized with `100dvh` (not
  `vh`, which on mobile browsers includes space hidden under the address-bar
  chrome) and `min-block-size: 0` on `<main>` so the conversation area scrolls
  instead of growing the whole document.

### 9.3 Auth flow end-to-end

**Where the token lives**: a plain module-level variable in
`src/context/auth/sessionStore.js` — deliberately outside React state or a ref.
This is a fix for a real bug: React flushes child effects before parent effects,
so `ChatProvider` (mounted inside `AuthProvider`) fired its `/conversations`
fetch *before* `AuthProvider`'s own effect had published the token. That request
went out with no `Authorization` header, got the same 401 the backend returns
for a rejected token, and the app read a healthy page reload as "your session
was revoked" — signing the user out one frame after restoring them. A module
evaluates at import time, strictly before any render, so the token is available
from the very first `fetch` the app can possibly make. `sessionStore.js` exposes
`getSession()` / `setSession()` / `clearCurrentSession()` /
`onSessionLost(handler)`, and calls `configureAuthBridge({getToken,
onAuthFailure})` on `src/api/client.js` at module load.

**`src/api/client.js`** is the single network chokepoint. A local `credentialed`
flag is set `true` only when a token was actually read and attached as
`Authorization: Bearer <token>` — the "session revoked" callback fires **only**
when `credentialed && error.isAuthFailure`. This is what makes the fix in the
paragraph above load-bearing: since the backend answers a *missing* header with
the same 401 as a *rejected* one, keying the sign-out purely off "got a 401"
would risk ending a perfectly valid session for a request that simply fired one
tick too early. It also builds an `AbortController` combining a timeout
(`REQUEST_TIMEOUT_MS = 20s` for auth/health calls, `CHAT_TIMEOUT_MS = 180s` for
`/chat`) with the caller's own abort signal, and distinguishes a timeout
(friendly "took too long" `ApiError`), a caller-initiated cancel (re-thrown
as-is), and a genuine network failure (`ApiError` with status 0).

**`src/api/ApiError.js`** is the one error shape used everywhere — `status`,
`fieldErrors`, `body`, plus getters `isNetworkFailure` (status 0),
`isAuthFailure` (401/403), `isUnavailable` (503, the "API is up but MongoDB
isn't" case). It normalizes FastAPI's `detail` field (a string for a plain
`HTTPException`, or an array of per-field validation errors for a 422) into one
`message` plus a `fieldErrors` map.

**`src/context/auth/session.js`** turns a login/register response into a
storable session — `expires_in` seconds becomes an absolute `expiresAt` epoch,
checked against the real clock with a 30-second safety margin. It fully
validates a session's shape before trusting it (rejects if `token` /
`expiresAt` / `user.id` are missing or malformed), so a tampered or half-written
localStorage value can never produce an app that looks signed in but has no
working token. Session storage backend (localStorage vs. sessionStorage) is
chosen by "remember me," and saving to one always clears the other first so
unchecking "keep me signed in" doesn't leave a stale long-lived copy behind.

**`AuthProvider.jsx`** is a plain-`useState` state machine with three statuses —
`loading` / `anonymous` / `authenticated`. Its initial state is computed
synchronously inside `useState`'s own initializer (reading
`sessionStore.getSession()` directly, not in an effect), so the very first paint
already reflects the real session and there is no login-screen flash on reload.
Four distinct triggers all funnel through one `endSession(reason)`: manual
sign-out, an expiry timer (self-re-arming in chunks under the 32-bit
`setTimeout` limit), the auth bridge reporting a rejected token, and a
cross-tab `storage` event (another tab signing out, or signing in as a
*different* account — which `ChatProvider` also watches for, so as not to keep
showing one account's conversation under another account's session). A
`visibilitychange` listener re-checks expiry against the real clock whenever a
backgrounded or sleeping tab wakes up, since a throttled background timer can
fire late. Sign-out is purely local — there is no `/auth/logout` endpoint to
call, since the JWT is stateless and the backend keeps no session table;
forgetting the token *is* the sign-out.

**Auth UI** (`src/features/auth/`): `AuthScreen` renders a two-column layout —
the sign-in/sign-up form first in the DOM, a marketing `AuthShowcase` panel
second (hidden below 1024px) — with `AuthTabs` (a full ARIA tab pattern with a
sliding indicator and arrow-key navigation) and a `ServiceStatus` footer that
calls `GET /health` before anyone types a password, distinguishing `ready` from
`degraded` (API up, MongoDB down — login would 503, which is otherwise
indistinguishable from "the form is broken") from `offline`. `SignUpForm` adds a
live `PasswordStrength` meter (advisory only — it never blocks submission, only
the mirrored 8-character/72-byte backend limits do) and a client-only
confirm-password field. Validation constants (`PASSWORD_MIN_LENGTH=8`,
`PASSWORD_MAX_BYTES=72` measured via `TextEncoder` — not `.length`, since bcrypt's
limit is in bytes — `NAME_MAX_LENGTH=80`) are hand-mirrored from `model/config.py`
and `model/api.py` so a rejection is caught client-side before the round trip.

### 9.4 Chat flow end-to-end

**`ChatProvider.jsx`** uses `useReducer` rather than several `useState`s,
because a single event (the answer arriving) has to update multiple fields
atomically — fill in the turn's answer, name the conversation if this was its
first turn, clear any stale notice. Two refs act as the "current truth" for
async code that can't trust a stale closure: `conversationIdRef` (the id the
*next* `/chat` call must send) and `askRef` (the in-flight request's
`AbortController`, which doubles as the "only one request at a time" guard).

- **Sending**: `send(question)` appends a `PENDING` turn (keyed by a locally
  generated `local-N` id, not an array index — so later updates can never land
  on the wrong turn), then calls the API. `chat.api.js`'s `ask()` omits
  `conversation_id` entirely to start a new conversation, or sends the current
  one to continue it. On success, `conversationIdRef` is updated to the id the
  backend returned, citations are cached (below), and — only if this was the
  first turn of a brand-new conversation — the conversation list is refetched
  (a title never changes after creation, so later turns skip this).
- **A 404 on `/chat`** (the conversation id was valid a moment ago but no
  longer resolves — expired, deleted) is treated as "this conversation is
  gone": its cached citations are dropped, `conversationIdRef` resets to null,
  and history is reloaded.
- **`stop()`** only aborts the fetch on the client — `chain.ask` keeps running
  server-side in FastAPI's thread pool with no cancellation path, and the turn
  will still be saved. So `stop()` marks the pending turn as a retryable
  failure and re-fetches history, since a stopped-but-first question may have
  already created a conversation server-side before the abort landed.
- **`retry()`** re-runs only the most recent failed turn, so an earlier failure
  can never have its eventual answer attached to a later question.
- **`openConversation(id)`** fetches the transcript and merges in cached
  citations per turn before rendering it.

**Citations and the API gap** (`src/context/chat/citations.js`): confirmed
exactly per project notes — `POST /chat` returns `pdfs`/`urls`, but `GET
/conversations/{id}` only returns `{seq, ts, question, answer, source}` because
the backend's `Turn` pydantic model narrows the fields away even though MongoDB
stores the rest. Citations are therefore cached client-side in
**sessionStorage** (deliberately not localStorage — "these are the specific
documents behind somebody's questions, and they should not outlive the tab on a
shared desk"), keyed per conversation and per turn sequence number. A reopened
conversation with nothing cached (a different device, a cleared tab) shows
**zero** citations rather than guessing — an unprovable citation says nothing
better than no citation at all.

### 9.5 The live "agent activity" UI

`useActivityTrace.js` is a **pure client-side fabrication**, driven entirely by
elapsed wall-clock time (a 500ms `setInterval`), because `/chat` is a single
blocking call with no SSE or streaming — there is genuinely nothing from the
server to report on while waiting. A hardcoded five-stage sequence, mirrored
from `model/chain.py`'s own documented pipeline order, assigns each stage a
cumulative millisecond threshold: "Reading your question" (0ms) → "Working out
what it's asking" (700ms, the autocorrect/follow-up-rewrite step) → "Checking
the subject" (2200ms, the scope/arihant/cmots gates) → "Searching the research
and the web" (4200ms, describing the two lanes actually running in parallel) →
"Writing the answer" (9200ms). The active stage only ever advances, never
regresses, and holds at the last stage indefinitely rather than inventing a
sixth. Past 22 seconds and 45 seconds (the model-import cold-start window) an
extra note explains the delay so a slow first request doesn't read as broken.

**Reconciliation with the real answer** is a hard swap, not a cross-fade:
`Turn.jsx` renders `ActivityTrace` only while `turn.status === PENDING`. The
instant the reducer records the real answer, the turn's status flips and
`ActivityTrace` unmounts (killing its interval) in favor of the actual reply,
whose header reads `source` through `src/features/chat/sources.js` — a lookup
table mapping every backend `source` string (`documents` / `web` / `arihant` /
`cmots-ai` / `general` / `small talk` / `out of scope`) to a label, sentence,
icon, and tone. `general` (ungrounded model knowledge) is the one value flagged
with a warning tone specifically because it's the only tier with no real
citation behind it. The file's own framing: the fabricated trace is "a
client-side estimate... this [the source field] is the fact; that is the
illustration" — the UI never blends the two or lets the guess outlive the truth.

### 9.6 Chat screen composition and layout

**Confirmed non-standard layout, with the actual mechanism**: there is no
permanent sidebar. `ChatScreen` renders a slim 76px icon-only `ChatRail` (New /
History / Search) beside the conversation column; `HistoryPanel` and
`SearchPalette` are both overlays — summoned over the conversation on demand and
dismissed, rather than parked permanently on screen. The rationale documented
in the code: "every chat product gives a third of the screen to a permanent
list of the conversations you are not reading. For a research tool whose
answers contain tables, that is a third of the width a table could have had."
Below 900px the rail relocates to the bottom edge via CSS `order` while keeping
its DOM position first for tab order.

- **`ConversationView`** owns the scroll viewport, inserts `DaySeparator`s
  across date boundaries, and shows a floating "Latest" jump button only once
  the view has scrolled away from the bottom (`useAutoScroll` tracks "pinned"
  via a `ResizeObserver` on the content, not just on turn count, so a trace
  note appearing mid-answer still counts as new content).
- **`Turn`** stacks, top to bottom: the question, an optional "Read as:
  `<standalone>`" line (shown only when the chain's rewrite meaningfully
  differs from what was typed), the activity trace or the finished answer
  (source header, then the rendered markdown, then citations) — the source
  header is placed *above* the answer specifically so an ungrounded `general`
  answer is read as flagged before it's read at all.
- **`Composer`** is an auto-growing textarea (Enter sends, Shift+Enter inserts
  a newline, guarded against IME composition), shows a character counter only
  within 200 characters of the mirrored 2000-char backend limit, and disables
  entirely while a request is in flight — the only way out mid-request is the
  Stop control inside `ActivityTrace`.
- **`Citations`** renders PDFs as non-clickable, copy-to-clipboard "pills"
  (there is no document-serving route, so a link would be dead) and URLs as
  real external links — deliberately unnumbered even though `[n]` markers
  appear inline, since the citation numbering and the deduplicated file list
  don't correspond one-to-one.
- **`HistoryPanel`** is read-only by design — there is no rename/delete
  endpoint on the backend, so no such controls are offered.
- **`SearchPalette`** debounces 300ms into `GET /search` (a whole-word Mongo
  `$text` query); results expand in place with the full rendered answer rather
  than navigating anywhere, since a search hit carries no `session_id` to
  navigate to (§7, API gap).
- **`useChatShortcuts`** binds ⌘K (search), ⌘⇧O (new conversation), and a bare
  `/` to focus the composer — guarded so `/` doesn't hijack typing that's
  already happening in another field.
- **`useDraft`** persists an in-progress, unsent message per conversation to
  sessionStorage, swapped synchronously during render (not in an effect) when
  the active conversation changes, so the wrong conversation's draft is never
  painted for even one frame.

### 9.7 Markdown and table rendering

**`src/lib/markdown/` is a fully hand-rolled parser** — no `marked`/`remark`/
`markdown-it` dependency, consistent with the vanilla-only constraint, and
justified by scope: the backend only ever emits prose, bold text, bullet lists,
`[n]` citation markers, and occasional pipe tables, so a general-purpose parser
would mostly add attack surface (HTML passthrough, reference-style links) for
constructs an LLM's output never actually needs.

- **`parse.js`** (block level) recognizes paragraphs, headings, ordered/
  unordered lists (with nested blocks), tables (requiring an explicit
  `|---|---|` separator row before anything is treated as a grid — a
  deliberately strict rule so ordinary prose like "the ratio is 2 | 1" is never
  mangled), fenced code blocks, quotes, and rules.
- **`inline.js`** (span level) is a hand-written character scanner rather than
  chained regexes — chosen to avoid precedence ambiguity between bold/italic/
  links — producing text, line-break, code, strong/em (with flanking rules so
  `2 * 3 * 4` isn't read as italics), link (restricted to `http(s)://`,
  blocking `javascript:`/`data:` schemes), and citation (`[3]`-style, matching
  the backend's own convention) tokens.
- **`Markdown.jsx`** renders the parsed tree as **React elements only** — never
  `dangerouslySetInnerHTML`, at any stage — which is the actual XSS mitigation:
  nothing the model outputs is ever interpreted as markup, so a `<script>` tag
  a model copied out of a scraped web page renders as inert literal text.
  Tables get a horizontal-scroll wrapper and auto-detect numeric columns (₹/Rs/
  %/comma/decimal patterns) for right-alignment even when the model gave no
  explicit column-alignment hint. Citation markers render as clickable buttons
  that scroll to and flash the citations block, but only when the turn
  actually has sources — otherwise they render as inert superscript text.

### 9.8 Design system

`src/styles/index.css` declares the cascade layer order exactly once —
`@layer reset, tokens, base, layout, components, utilities;` — and every later
layer beats every earlier one regardless of selector specificity, which is why
the codebase never needs `!important`. Component and feature stylesheets are
**not** imported centrally; each component imports its own `.css` file next to
it, keeping style and markup co-located and deletable together.

Token tiers, in `src/styles/tokens/`:

| File | Role |
|---|---|
| `palette.css` | Tier 1 raw color primitives (ported from the Arihant Flutter GoalPlanner app) — never referenced directly by components |
| `semantic.css` | Tier 2, the *only* color layer components may use — full light and hand-designed dark themes, surfaces/borders/text/brand/status colors, chat-specific tokens (bubble, activity-trace, citation colors), and gain/loss financial color semantics |
| `typography.css` | Jost variable font (falling back to Inter/system), a rem-based size ramp, fluid `clamp()` display sizes, weights, leading, tracking |
| `space.css` | 4px-grid spacing, radii, border widths, and named layout widths (rail, panel, conversation column) |
| `motion.css` | durations/easings ported from the Flutter app's motion spec, plus staggered-entrance tokens |
| `elevation.css` | brand-navy-tinted shadow ramps (not pure black), a separate dark-mode ramp, state-driven glow tokens, one shared focus ring |
| `gradients.css` | every gradient centrally named (brand CTA, AI "intelligence" gradient, ambient canvas, scroll fade masks) |
| `layers.css` | the z-index scale as named tokens, so stacking conflicts are fixed by adding a step rather than inventing a number |

**Theming** (`src/context/theme/`): three states — light / dark / system —
persisted to localStorage. `ThemeProvider` resolves `system` against
`matchMedia('(prefers-color-scheme: dark)')` and live-updates on OS changes,
writing `data-theme` onto `<html>`. A **blocking inline script in
`index.html`** duplicates this exact resolution logic so `data-theme` is set
before first paint — without it, a module script running after paint would
flash the light theme before flipping to dark. `ThemeToggle` is a 3-position
segmented control built on real native radio inputs (visually hidden, not
semantically), chosen specifically to get correct arrow-key/roving-tabindex
behavior for free from the browser instead of reimplementing `role="radiogroup"`.

### 9.9 Shared UI kit and account menu

`src/components/ui/` holds the primitives every feature is built from: `Button`
(variants, sizes, a loading state that swaps the icon for a `Spinner` while
holding the label's width steady — also doubling as double-submit protection),
`TextField`/`PasswordField` (full ARIA error wiring; `PasswordField` adds a
show/hide toggle and live Caps Lock detection), `Checkbox`, `Alert` (tone-based,
`role="alert"` only for danger/warning so success/info don't interrupt a screen
reader), `Avatar` (initials colored deterministically from the account id, so a
person's color is stable across sessions), `Icon` (a name→path sprite,
`aria-hidden` by default), `Spinner`, and `Tooltip` (pure CSS, explicitly not an
accessibility mechanism since it's unreachable by touch — the control beneath
it must already carry its own accessible name).

`src/features/account/`: `UserMenu` is a disclosure panel — deliberately *not*
ARIA `role="menu"`, because it embeds the `ThemeToggle` radio group, which
would be unreachable under strict menu-role keyboard rules — showing identity,
role badge, last-login time, and a sign-out action. `SignOutDialog` is built on
the native `<dialog>` element and rendered through a `createPortal` into
`document.body`, specifically because the account menu lives inside a
`backdrop-filter`-using top bar, whose filtered ancestor would otherwise become
the containing block for a `position: fixed` dialog and center it inside the
64px bar instead of the viewport.

---

## 10. Known fragility & operational notes

Carried forward from hard-won debugging history on this project — worth knowing
before touching either the backend or its database:

- **MongoDB has no backup here.** The reference dev setup runs a standalone
  `mongod` — no replica set, no oplog, no filesystem snapshots. A bad
  `delete_many` cannot be undone. Always read matching documents and confirm an
  expected count before any delete. (A real incident wiped 17 conversations and
  21 messages this way — see §6.3.)
- **The ownership field is `user_id`, never `owner`.** `owner` only ever appears
  as a Python keyword-argument name in `history.py`'s functions; querying the
  actual stored documents for `{"owner": ...}` matches nothing.
- **`cmots-ai` answers are non-deterministic across process runs** — both the
  planner and the writer are LLM calls, cached only in-process. A short or
  seemingly-wrong CMOTS answer is not necessarily a bug; check the stored
  `messages` document in MongoDB for what was actually generated before assuming
  the frontend mishandled it.
- **Two OpenMP runtimes crash the worker on macOS** (`torch`, `faiss`, and
  `scikit-learn` each ship their own copy). Run `python openmp_fix.py` once after
  creating the venv and again after any `pip install`. `api.py` checks for this at
  startup and prints a warning if the fix has been undone — but the check does not
  block startup, so the first real question can still crash the worker if the
  warning is ignored. Symptom if this happens: `uvicorn --reload`'s parent process
  keeps the port open even though its child worker died, so every subsequent
  request hangs until the client's own timeout gives up — there is no connection
  error to diagnose from, only a silent hang.
- **The frontend's ESLint config (`eslint-plugin-react-hooks` v7, React Compiler
  rules) rejects several patterns older React code uses freely**: a hook must not
  return a ref; no `setState` inside an effect body (initialize from
  `useState(initializer)` instead, and treat a fetch-on-mount as
  `promise.then(setState)`, never a synchronous setState call); a `useCallback`
  must not call itself recursively (declare a named inner function and recurse on
  that instead); and `ref.current` must never be read or written during render,
  even as a one-time initialization guard.
- **CSS cascade layers mean later layers win regardless of selector specificity.**
  Layer order in `src/styles/index.css` is `reset → tokens → base → layout →
  components → utilities`. A rule in any component's own `.css` file beats a rule
  in a layout sheet even if the layout rule is more specific — so a responsive
  `display` override for a component that already sets its own `display` has to
  live inside that component's own `@layer components` block. `!important` does
  not help here and can actively backfire: for `!important` declarations, layer
  precedence *reverses*, so `reset` would outrank every later layer.
