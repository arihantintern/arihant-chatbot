"""read every pdf in pdfs/ and write the index.

    python build.py             cached elements when nothing changed
    python build.py --refresh   re-read the pdfs even so

Run it once, and again after adding a pdf. `--refresh` is also what you want after
editing ingest.py, because the cache watches the pdfs, not the parsing code.

This is also the one command that genuinely wants both libomp.dylib copies in one
process -- reading pdfs pulls unstructured -> spacy -> thinc -> torch, writing the
index pulls faiss. openmp_fix.py is what makes that survivable, and `pip install`
is what undoes it; run it again after one. Elsewhere the question does not arise,
because ingest.py now keeps the torch-shaped half behind load_folder() and
splitter(), so the answering path never imports either.

If a build does die on "OMP: Error #15", it died on the faiss half and
load_elements() has already written the parsed pdfs to .cache/elements.pkl. Re-run
without --refresh: that reads the cache, never touches unstructured, and finishes
the index in a process that only ever loads faiss.
"""
import sys
from collections import Counter

from config import DOCS_DIR
from store import build_index

if __name__ == "__main__":
    print(f"reading {DOCS_DIR}\n")
    store, chunks = build_index(refresh="--refresh" in sys.argv)

    print(f"\nchunks -> {len(chunks)}")
    for source, n in sorted(Counter(d.metadata["source"] for d in chunks).items()):
        mine = [d for d in chunks if d.metadata["source"] == source]
        tables = sum(1 for d in mine if d.metadata.get("category") == "Table")
        print(f"  {source:<46} {n:>4} chunks  {tables:>2} tables  date={mine[0].metadata['date']}")

    print("\nask it something:  python cli.py")
