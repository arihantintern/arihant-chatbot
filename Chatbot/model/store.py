"""build the index, load the index.

FAISS is a file on disk with no server to run, which is the only thing that matters
here -- the same embeddings over the same chunks give the same neighbours whatever
stores them. The loader is the expensive part of a rebuild, not the embedding, so
the cache sits in front of the loader.
"""
from __future__ import annotations

import pickle

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

from config import CACHE_FILE, DOCS_DIR, EMBED_MODEL, INDEX_DIR
from ingest import chunks_for, load_folder

embeddings = OllamaEmbeddings(model=EMBED_MODEL)


def _fingerprint() -> list[tuple[str, int, int]]:
    return sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                  for p in DOCS_DIR.rglob("*.pdf") if not p.name.startswith("."))


def load_elements(refresh: bool = False) -> dict[str, list[Document]]:
    """{filename: elements}, from cache when nothing in the folder has changed.

    All or nothing, because DirectoryLoader reads the folder in one go. Add a pdf
    and every pdf is read again -- fine at this size. The fingerprint watches file
    sizes and mtimes, so editing *this* file's parsing code does not invalidate it:
    that is what `--refresh` is for.
    """
    if not refresh and CACHE_FILE.exists():
        with CACHE_FILE.open("rb") as f:
            cached = pickle.load(f)
        if cached.get("fingerprint") == _fingerprint():
            print("elements from cache")
            return cached["elements"]

    elements = load_folder()
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("wb") as f:
        pickle.dump({"fingerprint": _fingerprint(), "elements": elements}, f)
    return elements


def build_index(refresh: bool = False) -> tuple[FAISS, list[Document]]:
    if not DOCS_DIR.exists() or not any(DOCS_DIR.rglob("*.pdf")):
        raise SystemExit(f"no pdfs in {DOCS_DIR} -- drop some in and run this again")

    chunks: list[Document] = []
    for name, elements in sorted(load_elements(refresh).items()):
        chunks += chunks_for(elements, name)

    print(f"embedding {len(chunks)} chunks on {EMBED_MODEL} ...", flush=True)
    store = FAISS.from_documents(chunks, embeddings)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    store.save_local(str(INDEX_DIR))
    with (INDEX_DIR / "chunks.pkl").open("wb") as f:
        pickle.dump(chunks, f)
    return store, chunks


_INDEX: tuple[FAISS, list[Document]] | None = None


def get_index() -> tuple[FAISS, list[Document]]:
    """the index, loaded once per process and shared by everything that wants it."""
    global _INDEX
    if _INDEX is None:
        if not (INDEX_DIR / "index.faiss").exists():
            raise SystemExit(f"no index at {INDEX_DIR} -- run:  python build.py")
        store = FAISS.load_local(str(INDEX_DIR), embeddings,
                                 allow_dangerous_deserialization=True)
        with (INDEX_DIR / "chunks.pkl").open("rb") as f:
            _INDEX = (store, pickle.load(f))
    return _INDEX
