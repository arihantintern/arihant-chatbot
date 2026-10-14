"""the web fallback, used only when the documents cannot answer.

Duckduckgo, because the one api key this project has is openai's and search is not
what it is for -- and because a key that costs nothing is one less thing to hold.

This is no longer a fallback: `chain.both()` starts it at the same moment as the
index, so it runs on the web-lane thread and its result is read only if the pdfs
missed. Every failure --
package missing, no network, a page that will not load -- returns [] rather than
raising, or the general-knowledge branch below it never gets a turn.
"""
from __future__ import annotations

import os

from config import WEB_CHARS, WEB_RESULTS
from ingest import clean_text

os.environ.setdefault("USER_AGENT", "arihantBot/2.0")   # WebBaseLoader warns without it


def search(query: str) -> list[dict]:
    """query -> a few {title, url, text}, or [] if the web is not available."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=WEB_RESULTS))
    except Exception:
        return []

    from langchain_community.document_loaders import WebBaseLoader

    pages = []
    for hit in hits:
        url = hit.get("href") or hit.get("url")
        if not url:
            continue
        try:
            loaded = WebBaseLoader(url).load()
        except Exception:
            continue
        text = clean_text("\n".join(d.page_content for d in loaded))[:WEB_CHARS]
        if text:
            pages.append({"title": hit.get("title", ""), "url": url, "text": text})
    return pages


def format_pages(pages: list[dict]) -> str:
    return "\n\n".join(f"[{i + 1}] {p['title']} ({p['url']})\n{p['text']}"
                       for i, p in enumerate(pages))
