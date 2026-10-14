"""which chunks come back: similarity, a date filter, and a literal rescue.

Three things, and the last two both exist because ten morning dailies are near
identical to an embedder -- they all say `BSE Sensex` beside a five digit number,
and only the number differs.

**The date filter needs `fetch_k`.** FAISS cannot search inside a metadata subset;
langchain fetches `fetch_k` neighbours over the whole index and drops the failures
afterwards, and the default is 20. So a date filter silently means "of the 20
nearest chunks in the corpus, keep the ones from that day" -- which on this corpus
returned 2 chunks from nine different days and left the right table out entirely.

**The literal rescue** finds what dense search structurally cannot. "axis bank
current price" has nothing to match in four columns of digits, but `Axis Bank` is
printed in the table and appears in 4 chunks out of 447. A phrase that rare is not
a coincidence, it is the answer.
"""
from __future__ import annotations

import re

from langchain_core.documents import Document

from config import RESCUE_K, TOP_K
from ingest import MONTHS
from store import get_index

# words that say nothing about which chunk to read. "current price" and "research
# call" appear in no chunk at all; "the" appears in every one.
NOISE = {"what", "was", "were", "the", "and", "for", "with", "how", "much", "did",
         "does", "are", "you", "your", "give", "tell", "show", "please", "about",
         "price", "current", "target", "call", "cell", "research", "close", "closing",
         "value", "data", "info", "information", "report", "reports", "that", "this",
         "from", "have", "has", "any", "all", "its", "who", "which", "when", "there"}


def dates_in(text: str, known: set[str]) -> str | None:
    """the day a question is about, if it names one AND the corpus has it.

    Strict on purpose: a filter firing on a date nothing was published on would
    search an empty corpus, so day, month and year all have to be present and the
    result has to match a document already indexed.
    """
    low = text.lower()
    months = "|".join(MONTHS)
    for pattern, order in (
        (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({months})[a-z]*\.?,?\s+(\d{{4}})", "dmy"),
        (rf"\b({months})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", "mdy"),
        # the format the reports themselves print, and so the one a reader types
        (rf"\b(\d{{1,2}})-({months})[a-z]*-(\d{{2,4}})\b", "dmy"),
    ):
        m = re.search(pattern, low)
        if not m:
            continue
        day, month, year = ((m.group(1), m.group(2), m.group(3)) if order == "dmy"
                            else (m.group(2), m.group(1), m.group(3)))
        iso = f"{year if len(year) == 4 else f'20{year}'}-{MONTHS[month[:3]]}-{int(day):02d}"
        if iso in known:
            return iso
    m = re.search(r"\b\d{4}-\d{2}-\d{2}\b", low)
    return m.group(0) if m and m.group(0) in known else None


def literal(pool: list[Document], question: str, want: int = RESCUE_K) -> list[Document]:
    """chunks containing a phrase from the question that almost nothing else has.

    The report's own date format is generated too, because a question saying "29
    april 2022" is looking for a cell printed `29-Apr-22`.

    This is not a bm25 hybrid -- that reweights every query. This adds at most
    `want` chunks, and only when a phrase is rare enough to be a name.
    """
    texts = [(d, d.page_content.lower()) for d in pool]
    words = [w for w in re.findall(r"[a-z][a-z&'.\-]+|\d[\d\-]*", question.lower())
             if w not in NOISE and len(w) > 2]
    grams = [" ".join(words[i:i + 2]) for i in range(len(words) - 1)] + words

    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({'|'.join(MONTHS)})[a-z]*\.?,?\s+(\d{{4}})",
                  question.lower())
    if m:
        grams.insert(0, f"{int(m.group(1)):02d}-{m.group(2)[:3]}-{m.group(3)[2:]}")

    scored: dict[str, tuple[int, Document]] = {}
    ceiling = max(3, len(pool) // 40)
    for gram in grams:
        if len(gram) < 5:
            continue
        hits = [d for d, t in texts if gram in t]
        if not hits or len(hits) > ceiling:
            continue                      # absent, or too common to mean anything
        for d in hits:
            key = d.metadata["chunk_id"]
            scored[key] = (scored.get(key, (0, d))[0] + 1, d)

    return [d for _, d in sorted(scored.values(), key=lambda nd: -nd[0])[:want]]


def search(store, question: str, date: str | None = None, k: int = TOP_K) -> list[Document]:
    kwargs: dict = {"k": k}
    if date:
        kwargs["filter"] = {"date": date}
        kwargs["fetch_k"] = store.index.ntotal      # or the filter is a lie, see above
    docs = store.similarity_search(question, **kwargs)

    # Confined to the same day when a date filter is on, or "bse sensex" -- rare
    # enough to pass, printed in every daily -- drags in the wrong day's table.
    pool = [d for d in get_index()[1] if not date or d.metadata.get("date") == date]
    seen = {d.metadata.get("chunk_id") for d in docs}
    rescued = [d for d in literal(pool, question) if d.metadata.get("chunk_id") not in seen]

    # rescued chunks lead. Handed the right table alone the 3B model reads it;
    # handed it sixth of six it replies that it cannot see the company.
    return rescued + docs


def format_docs(docs: list[Document]) -> str:
    """numbered, so the model can point at one and so can the reader."""
    return "\n\n".join(f"[{i + 1}] {d.page_content}" for i, d in enumerate(docs))
