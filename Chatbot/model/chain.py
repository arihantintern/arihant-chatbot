"""the chain. Every pattern, prompt and canned line it uses is in `config.py`.

    question
        |
    small_talk?  -- hit --> a greeting, answered from a table
        | miss
        v
       fix        a small model spellchecks. the original still does the
        |         searching; the correction is only a hint.
        v
    resolve      "and its rating?" -> "what is arihant's rating on bandhan bank?",
        |        from this session's last turns, read out of mongodb. Everything
        |        below here searches and answers the rewrite.
        v
    arihant?     -- hit --> TIER 1  the rating scale, parsed not read
        | miss
        v
    cmots-ai?    -- hit --> TIER 1b an ai planner decides what to fetch --
        | miss              cmots data, a web search, both or neither -- and a
        v                   writer turns it into one answer. One fact, several
                            facts, a report or a review are all this same tier.
    in_scope?    -- no  --> one line, then back to the subject
        | yes
        v
     +------------------ both lanes at once ------------------+
     |                                                        |
     v                                                        v
  retrieve                                                web.search
  similarity + a date filter + the literal rescue         duckduckgo
     |                                                        |
     v                                                        v
  doc_chain   reads the pdfs                          web_chain   reads the pages
     |                                                        |
     +-----------------------+--------------------------------+
                             v
                           route
                             |
        doc grounded?  --> TIER 2  the pdfs, cited, arihant's call leading
        web grounded?  --> TIER 3  duckduckgo, cited
        neither        --> TIER 4  general knowledge + a disclaimer

The two lanes touch nothing of each other's -- one reads FAISS, the other reads
duckduckgo, and both end in their own model call -- so the web lane goes to a
thread and starts at the same moment the index does. Both are I/O the whole way
down (an http call to ollama, an http call to the web), so the GIL is released for
nearly all of it and the parallelism is real.

Started together, not *joined* together. `route` prefers the documents, so when the
pdfs answer, the web lane's result was never going to be read -- waiting for it
would make the question the corpus can answer the slowest one there is. It is left
running and the answer returns; only a doc miss ever waits on it. So a web answer
now costs the slower lane instead of doc-then-web, and a doc answer costs the
documents alone.

Every step leaves `doc_source`/`web_source` behind, because RunnableBranch reads a
value, not a model's mind, and the two lanes cannot both write `source` while they
run side by side. `/graph` prints this; langchain's own graph draws the whole
router as one box called `Branch`, so this picture is kept by hand.
"""
from __future__ import annotations

import re
import threading
import time

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import (
    RunnableBranch, RunnableLambda, RunnableParallel, RunnablePassthrough,
)
from langchain_ollama import ChatOllama

import history
import web
from cmots_ai import cmots_ai_answer
from config import (
    BRIEF_PROMPT, CHAT_MODEL, CHAT_TEMPERATURE, DESCRIBE_Q, DISCLAIMER, DOC_PROMPT, FIRM_Q,
    FIX_TURNS, FOLLOWUP_Q, FOLLOWUP_TURNS,
    GENERAL_PROMPT, HEAD, HEDGES, HISTORY_ANSWER_CHARS, HISTORY_TURNS, METRIC_Q, NOT_IN_DOCS,
    NOT_ON_WEB, RATINGS, RATING_Q, REPLIES, SCOPE_TURNS, SMALL_MODEL, TAIL, TALK, WEB_PROMPT,
)
from retrieve import dates_in, format_docs, search
from store import get_index

small = ChatOllama(
    model="llama3.2:1b",
    base_url="http://localhost:11434",
    temperature=0
)

model = ChatOllama(
    model="llama3.2:1b",
    base_url="http://localhost:11434",
    temperature=CHAT_TEMPERATURE
)
parser = StrOutputParser()
prompt = PromptTemplate.from_template

store, chunks = get_index()
KNOWN_DATES = {d.metadata.get("date") for d in chunks} - {None}
SOURCES = sorted({d.metadata.get("source") for d in chunks} - {None})
DATED = sorted({d.metadata["date"] for d in chunks if d.metadata.get("date")})
MONTH = ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December")


# ------------------------------------------------------------------ the gates
def corpus_line() -> str:
    """read off the chunks -- a written down list goes stale the first time a pdf
    lands in the folder. Dailies get a date range, titled reports get named."""
    if not SOURCES:
        return "i have no documents indexed right now"
    parts = []
    if DATED:
        e = [f"{int(d[8:])} {MONTH[int(d[5:7]) - 1]} {d[:4]}" for d in (DATED[0], DATED[-1])]
        parts.append(f"{len(DATED)} dated market reports ({e[0]} to {e[1]})")
    titled = [s.removesuffix(".pdf") for s in SOURCES
              if s not in {d.metadata["source"] for d in chunks if d.metadata.get("date")}]
    if titled:
        parts.append(", ".join(titled[:2])
                     + (f" and {len(titled) - 2} more" if len(titled) > 2 else ""))
    return f"i have {len(SOURCES)} pdfs indexed -- " + ", plus ".join(parts)


def small_talk(text: str) -> str | None:
    """a greeting has no answer to get wrong, so generating one can only lose."""
    line = text.strip().lower()
    if not line or len(line.split()) > 6:
        return None
    for pattern, kind in TALK:
        if re.fullmatch(rf"[\s,.!?~]*(?:{pattern})[\s,.!?~]*(?:there|bot|mate)?[\s,.!?~]*", line):
            return REPLIES[kind].format(corpus=corpus_line())
    return None


# the filenames are the one piece of scope that is data, not judgement -- they come
# off the folder and change when it does. Two must land: one generic hit ("note",
# "meet") is an accident.
NAMES = {w for s in SOURCES for w in re.findall(r"[a-z]{4,}", s.lower())} - {
    "2025", "2024", "2023", "2022", "note", "notes", "final", "copy", "draft"}
scope_chain = ChatPromptTemplate.from_messages(SCOPE_TURNS) | small | parser


def in_scope(question: str) -> bool:
    """finance or not -- the small model decides, because a keyword list never ends.

    The verdict counts only when it *is* a label. Told to classify "write me a
    haiku" a 3B model writes the haiku, and for "the capital of australia" it once
    replied "CANBERRA". So anything but the word FINANCE is a refusal: a model
    answering the question is not a vote that the question was in scope.
    """
    if len(NAMES & set(re.findall(r"[a-z]{4,}", question.lower()))) >= 2:
        return True                       # names a pdf that is actually on disk
    try:
        verdict = scope_chain.invoke({"question": question})
    except Exception as e:
        print("  [scope check failed]", type(e).__name__, e)
        return True                       # never refuse because ollama hiccuped
    return verdict.strip().strip('".').upper().startswith("FINANCE")


# Tier 1 is parsed, not retrieved -- OCR reads the rating labels as "3UY",
# "\CCUMULATE", "4OLD", so a model handed that chunk guesses at the exact words the
# question asks about. The bands survive intact in the document's own fixed order,
# so the labels come from that order rather than from the pixels.
def _scale() -> dict[str, str]:
    band = re.compile(r"(>\s*\d+%|<\s*-?\d+%|-?\d+%\s*to\s*-?\d+%)")
    for d in chunks:
        if "Rating Scale" in d.page_content:
            found = band.findall(d.page_content[d.page_content.find("Rating Scale"):])
            if len(found) >= len(RATINGS):
                return {r: re.sub(r"\s+", " ", b).replace("> ", ">").replace("< ", "<")
                        for r, b in zip(RATINGS, found)}
    return {}


def _firm() -> str:
    text = " ".join(d.page_content for d in chunks)
    bits = [f"research analyst registration {m.group(1)}" if key == "reg" else m.group(1)
            for key, pat in (("reg", r"\b(INH\d{6,})\b"),
                             ("web", r"\b(www\.[a-z0-9.\-]+\.[a-z]{2,})"),
                             ("mail", r"\b([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})"))
            if (m := re.search(pat, text, re.I))]
    return ("arihant capital markets ltd publishes these reports — " + ", ".join(bits)
            + ".") if bits else ""


SCALE, FIRM = _scale(), _firm()


def arihant_answer(question: str) -> str | None:
    q = question.lower()
    if SCALE and re.search(RATING_Q, q, re.I):
        # \ball\b, not all\b -- the latter matches the "all" inside "call"
        named = [r for r in RATINGS if re.search(rf"\b{r}\b", q, re.I)]
        if named and not re.search(r"rating\s+scale|stock\s+rating|\ball\b|\beach\b", q):
            return "\n".join(f"on arihant's scale, {r} is a call for {SCALE[r]} "
                             f"absolute return." for r in named)
        return ("arihant's stock rating scale, by absolute return:\n"
                + "\n".join(f"  {r:<12} {SCALE[r]}" for r in RATINGS))
    return FIRM if FIRM and re.search(FIRM_Q, q, re.I) else None


# --------------------------------------------------- autocorrect, then search
# The correction never replaces the question: the original does the searching and
# the correction rides along as a hint, so a bad one costs a noisy prompt rather
# than a wrong search. Anything much longer is the model answering, and is dropped.
def keep(x: dict) -> str:
    fixed = x["fixed"].strip().strip('"')
    return fixed if fixed and abs(len(fixed.split()) - len(x["question"].split())) <= 2 \
        else x["question"]


fix = (RunnableParallel({"question": RunnablePassthrough(),
                        "fixed": ChatPromptTemplate.from_messages(FIX_TURNS) | small | parser})
       | RunnablePassthrough.assign(fixed=RunnableLambda(keep))
       | RunnablePassthrough.assign(asked=RunnableLambda(
           lambda x: x["question"] if x["fixed"].lower() == x["question"].lower()
           else f"{x['question']}    (possible typo correction: {x['fixed']})")))


# ------------------------------------------------- then the turn before it
# "and its rating?" is a question to a person and a bag of stopwords to FAISS. The
# session's last few turns come out of mongodb and a small model puts the missing
# words back, and it is the rewrite that gets searched, scoped and answered.
#
# `fixed` is left exactly as it was. Two rewrites of the same line, one for spelling
# and one for context, are two things that can go wrong, and keeping them apart is
# what makes the working notes readable when one of them does.
followup_chain = ChatPromptTemplate.from_messages(FOLLOWUP_TURNS) | small | parser


def needs_context(question: str) -> bool:
    """could this line be leaning on the one before it? Cheap, and deliberately
    generous -- a false hit costs one small model call that comes back unchanged."""
    return len(question.split()) <= 4 or bool(re.search(FOLLOWUP_Q, question.lower()))


def keep_standalone(rewritten: str, original: str) -> str:
    """the rewrite counts only when it is still a question.

    Same rule as `keep`: a small model handed a conversation and told to rewrite the
    last line will sometimes answer it instead, and an answer used as a search string
    retrieves the chunks that agree with it. Anything much longer than the question
    it replaced is that, so it is dropped and the original stands.
    """
    line = (rewritten or "").strip().strip('"').splitlines()
    first = line[0].strip() if line else ""
    return first if first and len(first.split()) <= max(25, len(original.split()) * 3) \
        else original


def standalone(x: dict) -> str:
    """the question with the conversation folded into it, or the question."""
    asked = x["fixed"] or x["question"]
    if not needs_context(asked):
        return asked
    turns = history.recent_turns(HISTORY_TURNS)
    if not turns:
        return asked                     # first question of the session, or no db
    try:
        rewritten = followup_chain.invoke(
            {"history": history.as_context(turns, HISTORY_ANSWER_CHARS),
             "question": asked})
    except Exception as e:
        print("  [follow-up failed]", type(e).__name__, e)
        return asked
    return keep_standalone(rewritten, asked)


resolve = RunnablePassthrough.assign(
    standalone=RunnableLambda(standalone)
) | RunnablePassthrough.assign(asked=RunnableLambda(
    # a resolved follow-up replaces `asked` outright: the prompt has to be told what
    # the question means, and "and its rating?" plus a typo hint tells it nothing.
    lambda x: x["standalone"] if x["standalone"].lower() != (x["fixed"] or "").lower()
    else x["asked"]))


def look_up(x: dict) -> list:
    try:
        return search(store, x["standalone"], date=x["date"])
    except Exception as e:
        print("  [retrieval failed]", type(e).__name__, e)
        return []


retrieve = RunnablePassthrough.assign(
    date=RunnableLambda(lambda x: dates_in(x["standalone"], KNOWN_DATES)
                        or dates_in(x["question"], KNOWN_DATES)
                        or dates_in(x["fixed"], KNOWN_DATES)),
) | RunnablePassthrough.assign(docs=RunnableLambda(look_up))


# --------------------------------------------------------------------- answer
def answered(text: str, sentinel: str) -> bool:
    """did that step answer, or is it a refusal wearing a paragraph?"""
    t = (text or "").strip()
    return bool(t) and sentinel.lower() not in t.lower() and len(t.split()) >= 4 \
        and not any(h in t[:160].lower() for h in HEDGES)


def grounded(answer: str, context: str, floor: float = 0.35) -> bool:
    """is this answer made of the context, or did the model just write?

    The sentinel rule holds for questions, not instructions: told to "write me a
    haiku" a 3B model writes it and never considers the sentinel, so `source` would
    say `documents` over text from nowhere near them. Grounded answers score
    0.58-0.83, that haiku 0.18. Gating only the doc branch would move the haiku to
    the web branch and cite it there, so both branches are gated.
    """
    context = context.lower()
    words = [w for w in (w.strip(".,") for w in re.findall(r"[a-z0-9,.]{4,}", answer.lower()))
             if w and not w.isdigit()]
    return bool(words) and sum(w in context for w in words) / len(words) >= floor


def wants_description(question: str) -> bool:
    """does this question want the company described, or a number off a table row?"""
    q = question.lower()
    return bool(re.search(DESCRIBE_Q, q)) and not re.search(METRIC_Q, q)


def cited(answer: str, docs: list) -> list:
    """the chunks the answer says it used -- all of them if it cited nothing."""
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    return [docs[i - 1] for i in sorted(numbers) if 0 < i <= len(docs)] or docs


def doc_verdict(x: dict) -> str:
    """grounded is necessary and, for one kind of question, not sufficient.

    `Bandhan Bank | Accumulate | 19% | -20%` is a row about Bandhan Bank, so every
    word of an answer built from it is in the context and `grounded` scores it high
    -- and the answer to "what is bandhan bank" comes back as "an Accumulate
    research call with a Potential Upside of 19%", which is a sentence about a
    table, not about a bank. Nothing in the text can catch that; what catches it is
    that the question asked what something IS and every chunk behind the answer was
    a table. The web lane is already running and it knows what Bandhan Bank is.
    """
    if not answered(x["doc_answer"], NOT_IN_DOCS) \
            or not grounded(x["doc_answer"], format_docs(x["docs"])):
        return "none"
    if (wants_description(x["standalone"]) or wants_description(x["question"])) and all(
            d.metadata.get("category") == "Table"
            for d in cited(x["doc_answer"], x["docs"])):
        return "none"
    return "documents"


doc_chain = RunnableLambda(lambda x: {
    "context": format_docs(x["docs"]), "asked": x["asked"], "sentinel": NOT_IN_DOCS,
}) | prompt(DOC_PROMPT) | model | parser

web_chain = RunnableLambda(lambda x: {
    "context": web.format_pages(x["pages"]), "asked": x["asked"], "sentinel": NOT_ON_WEB,
}) | prompt(WEB_PROMPT) | model | parser

from_docs = (retrieve
             | RunnablePassthrough.assign(doc_answer=doc_chain)
             | RunnablePassthrough.assign(doc_source=RunnableLambda(doc_verdict)))

from_general = RunnablePassthrough.assign(
    general_answer=prompt(GENERAL_PROMPT) | model | parser
) | RunnablePassthrough.assign(
    source=RunnableLambda(lambda _: "general"),
    answer=RunnableLambda(lambda x: x["general_answer"].strip() + DISCLAIMER))


def from_web(x: dict) -> dict:
    """search first, pay for a model call only if something came back. The resolved
    question is the better search string -- the bracketed typo hint is noise to it,
    and duckduckgo can do nothing at all with "and its rating?"."""
    pages = web.search(x["standalone"] or x["fixed"] or x["question"])
    if not pages:
        return {**x, "pages": [], "web_answer": NOT_ON_WEB, "web_source": "none"}
    draft = web_chain.invoke({**x, "pages": pages})
    ok = answered(draft, NOT_ON_WEB) and grounded(draft, web.format_pages(pages))
    return {**x, "pages": pages, "web_answer": draft,
            "web_source": "web" if ok else "none"}


# ------------------------------------------------------------- the two lanes
NO_DOCS = {"docs": [], "date": None, "doc_answer": NOT_IN_DOCS, "doc_source": "none"}
NO_WEB = {"pages": [], "web_answer": NOT_ON_WEB, "web_source": "none"}


def start_web(x: dict):
    """hit the web now; read the answer later, or never.

    A daemon thread and not RunnableParallel, and not an executor either: both of
    those are barriers, and a barrier here would make every question cost the web
    even though the router prefers the documents and would throw that answer away.
    Non-daemon threads are joined at interpreter exit, so the cli would then hang
    on the search it just decided it did not want.
    """
    box: dict = {}

    def run() -> None:
        clock = time.perf_counter()
        try:
            box["out"] = from_web(x)
        except Exception as e:                 # a dead web must not cost the pdfs
            print("  [web lane failed]", type(e).__name__, e)
            box["out"] = {**x, **NO_WEB}
        box["out"]["web_ms"] = int((time.perf_counter() - clock) * 1000)

    thread = threading.Thread(target=run, daemon=True, name="web-lane")
    thread.start()

    def read() -> dict:
        thread.join()
        return box["out"]
    return read


def both(x: dict) -> dict:
    """the index and the web at the same moment -- the two touch nothing of each
    other's, one reading FAISS and one reading duckduckgo, and both spend nearly all
    of their time inside an http call with the GIL released.

    So a web answer now costs the slower lane rather than doc+web, and a document
    answer costs what it always did: the web is still running when we return."""
    read_web = start_web(x)

    clock = time.perf_counter()
    try:
        docs = from_docs.invoke(x)
    except Exception as e:
        print("  [doc lane failed]", type(e).__name__, e)
        docs = {**x, **NO_DOCS}
    docs["doc_ms"] = int((time.perf_counter() - clock) * 1000)

    if docs["doc_source"] == "documents":
        return {**docs, **NO_WEB, "web_source": "unread"}
    return {**docs, **read_web()}


def settled(x: dict, answer: str | None, source: str) -> dict:
    """a gate's answer in the shape every branch returns, so ask() needs no case for
    the branches that never retrieved anything."""
    return {**x, "docs": [], "pages": [], "answer": answer, "source": source}


def chitchat(question: str, reply: str | None = None) -> dict:
    return settled({"question": question, "fixed": question, "asked": question,
                    "date": None}, reply or small_talk(question), "small talk")


def soft_refuse(x: dict) -> dict:
    """out of scope, but not a wall -- a flat refusal reads as broken rather than
    focused. One line, then the subject is changed. Never cited."""
    try:
        line = " ".join((prompt(BRIEF_PROMPT) | model | parser)
                        .invoke({"asked": x["asked"]}).split())[:280]
    except Exception as e:
        print("  [brief answer failed]", type(e).__name__, e)
        line = ""
    return settled(x, f"{HEAD}\n\n{line}\n\n{TAIL}" if line else f"{HEAD}\n\n{TAIL}",
                   "out of scope")


# --------------------------------------------------------------------- router
def take(key: str, source: str):
    return RunnablePassthrough.assign(
        answer=RunnableLambda(lambda x: x[key]),
        source=RunnableLambda(lambda _: source))


# both answers are already written by the time this runs, so this is a choice and
# not a fallback: the documents win when they are grounded, whatever the web found.
route = RunnableBranch(
    (lambda x: x["doc_source"] == "documents", take("doc_answer", "documents")),
    (lambda x: x["web_source"] == "web", take("web_answer", "web")),
    from_general)

# The gates sit outside the pipeline, not inside route -- by the time route runs,
# four model calls and a web search have happened on a line that was never a
# question. small_talk is checked twice: before `fix` is what makes "hi" free, but
# "what are you hellping with" is only a greeting once corrected.
#
# `resolve` sits below the greetings and above everything else. Below, because
# "thanks" is four words and would trip the follow-up gate into a model call to
# rewrite a pleasantry. Above, because the gates underneath it all read the question
# -- scope, the rating scale, the date filter, both searches -- and a follow-up is
# not a question yet when they get it.
chain = RunnableBranch(
    (lambda q: small_talk(q) is not None, RunnableLambda(chitchat)),
    fix | RunnableBranch(
        (lambda x: small_talk(x["fixed"]) is not None,
         RunnableLambda(lambda x: chitchat(x["question"], small_talk(x["fixed"])))),
        resolve | RunnableBranch(
            (lambda x: arihant_answer(x["standalone"]) or arihant_answer(x["question"]),
             RunnableLambda(lambda x: settled(x, arihant_answer(x["standalone"])
                                              or arihant_answer(x["question"]),
                                              "arihant"))),
            (lambda x: cmots_ai_answer(x["standalone"]) or cmots_ai_answer(x["question"]),
             RunnableLambda(lambda x: settled(x, cmots_ai_answer(x["standalone"])
                                              or cmots_ai_answer(x["question"]),
                                              "cmots-ai"))),
            (lambda x: not in_scope(x["standalone"]), RunnableLambda(soft_refuse)),
            RunnableLambda(both) | route)))


def show_graph() -> None:
    print(__doc__)


def ask(question: str, show_working: bool = True, session=None) -> dict:
    """one call, plus everything the chain did on the way there.

    The turn is written to mongodb after the answer is printed, never before: the
    person waiting gets their answer at the same moment they always did, and a slow
    or missing database costs the log rather than the reply. A turn that raised is
    saved too -- the questions that break the chain are the ones worth having.
    """
    session = history.use(session) if session else history.default_session()
    start = time.perf_counter()
    try:
        out = chain.invoke(question)
    except Exception as e:
        session.save(question, total_ms=int((time.perf_counter() - start) * 1000),
                     error=f"{type(e).__name__}: {e}")
        raise
    wall = int((time.perf_counter() - start) * 1000)
    print("\nBot:", out["answer"])
    if show_working:
        print("\n  [autocorrect] ->", out["fixed"])
        if (out.get("standalone") or "").lower() != (out.get("fixed") or "").lower():
            print("  [follow-up]   ->", out.get("standalone"))
        print("  [date filter] ->", out.get("date") or "none")
        print("  [source]      ->", out["source"])
        print("  [chunks]      ->", [d.metadata.get("chunk_id") for d in out.get("docs", [])])
        if out.get("pages"):
            print("  [urls]        ->", [p["url"] for p in out["pages"]])
        if "doc_ms" in out:
            # sequentially the two lanes were doc + web; side by side they are max()
            docs_ms, web_ms = out["doc_ms"], out.get("web_ms")
            print(f"  [lanes]       -> docs {docs_ms}ms, web "
                  + (f"{web_ms}ms, side by side {max(docs_ms, web_ms)}ms "
                     f"(saved {min(docs_ms, web_ms)}ms)" if web_ms is not None
                     else "started, left running unread"))
        print(f"  [total]       -> {wall}ms")
    session.save(question, out, wall)
    return out
