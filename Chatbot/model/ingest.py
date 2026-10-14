"""the folder -> the chunks that get embedded.

    load_folder      every pdf under pdfs/, hi_res, elements regrouped per file
    prepare          drop headers/footers, render tables, stitch paragraphs a page
                     break cut in half
    sections         elements -> section sized documents, tables held out
    split_tables     cut a table over the embed limit by rows, caption kept
    splitter         1000/200 over the prose only -- tables are never split
    tag              chunk_id, source, date

Two things are done differently here to the obvious approach, and both are about
tables, because on a morning daily the tables *are* the document.

**Tables are rendered as rows of pipes, not left as html.** `infer_table_structure`
produces `<table><thead><tr><th rowspan="2">Company</th>...`, and a 3B model handed
that markup will say it cannot see a company that is plainly in it. The same table
as `Axis Bank | 29-Apr-22 | 780 | 659 | 927 | Accumulate` it reads. Nothing is
discarded -- the rows and their order are exactly the html's, only the markup goes.

**Every table gets a caption line.** A table embeds badly because it is mostly
digits, and an English question has nothing to match against. The caption states in
words what the table is a table *of* -- its row labels and its column headers -- so
"what was Axis Bank's research call" has something to be similar to.
"""
from __future__ import annotations

import copy
import html
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pymupdf
import tiktoken
from langchain_core.documents import Document

from config import (
    CHUNK_OVERLAP, CHUNK_SIZE, DOCS_DIR, EMBED_TOKEN_LIMIT, JUNK, STRATEGY, TOKENIZER,
)

ENC = tiktoken.get_encoding(TOKENIZER)
ENDINGS = ".?!:;\"')]"


@lru_cache(maxsize=1)
def splitter() -> RecursiveCharacterTextSplitter:
    """1000/200 over prose. Built on first use, and imported on first use with it.

    The same reason load_folder() hides its loaders: `langchain_text_splitters`
    imports its own spacy splitter eagerly, spacy imports thinc, thinc imports
    torch, and torch's libomp.dylib is the second OpenMP runtime that makes faiss
    abort the process on its first search. Only chunks_for() needs a splitter and
    only build.py needs chunks_for, so the answering path -- which imports this
    module for MONTHS and clean_text -- no longer pays for any of it.
    """
    from langchain_text_splitters import (  # noqa: PLC0415  -- see above
        RecursiveCharacterTextSplitter,
    )

    return RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE,
                                          chunk_overlap=CHUNK_OVERLAP,
                                          length_function=len)


# ---------------------------------------------------------------------- load

def load_folder(folder: Path = DOCS_DIR) -> dict[str, list[Document]]:
    """every pdf in the folder -> {filename: elements}.

    DirectoryLoader returns one flat list, so elements are split back up by
    filename first. That regrouping is not cosmetic: prepare() joins a paragraph to
    the one before it, and on a flat list the first paragraph of one pdf would get
    glued to the last of another.

    The two loaders are imported here and not at the top of the file, and that is
    load-bearing rather than tidy. `UnstructuredPDFLoader` pulls in unstructured,
    which pulls in spacy, which pulls in thinc, which imports torch -- and torch
    ships its own copy of libomp.dylib. faiss ships another. A process holding both
    survives right up until faiss runs its first search, at which point faiss's
    OpenMP tries to register, finds torch's already there, and calls abort():

        __kmp_register_library_startup -> __kmp_fatal -> abort   (OMP: Error #15)

    That killed the api's worker mid-question. Nothing on the answering path -- api,
    chain, retrieve, store -- reads a pdf; they import this module for MONTHS and
    clean_text. So the torch-shaped half of it stays behind this function, where
    only build.py goes, and the server process now loads exactly one OpenMP runtime.
    """
    from langchain_community.document_loaders import (  # noqa: PLC0415  -- see above
        DirectoryLoader, UnstructuredPDFLoader,
    )

    loader = DirectoryLoader(
        str(folder), glob="**/*.pdf", loader_cls=UnstructuredPDFLoader,
        loader_kwargs={"mode": "elements", "strategy": STRATEGY,
                       "infer_table_structure": True, "languages": ["eng"]},
        show_progress=True,
        silent_errors=True,      # one unreadable pdf must not stop the others
    )
    by_file: dict[str, list[Document]] = defaultdict(list)
    for element in loader.load():
        by_file[Path(element.metadata.get("source", "unknown")).name].append(element)
    return dict(by_file)


# --------------------------------------------------------------------- clean

def clean_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return ""
    text = text.replace("\xa0", " ").replace("\t", " ")
    text = re.sub(r"[ ]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r" *\n *", "\n", text).strip()


# -------------------------------------------------------------------- tables

def table_rows(markup: str) -> list[list[str]]:
    """<table> -> one list of cells per row, in the html's own order."""
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", markup, re.S):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", c))).strip()
                 for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
        if any(cells):
            rows.append(cells)
    return rows


def header_like(row: list[str]) -> bool:
    """the reco table's column-name row, before or after its two halves are joined."""
    return any("Date" in c for c in row) and any("Price" in c for c in row)


def label_rows(rows: list[list[str]]) -> list[list[str]]:
    """data cells rewritten as `Column Name: value`.

    Even with one clean header line, answering "current price" from

        Axis Bank | 26-Jul-22 | 780 | 855 | 980 | Hold

    means counting columns and matching the count against a header printed rows
    earlier. `llama3.2:3b` miscounts: asked for the current price it answers 980,
    asked for the reco price it answers 855. Writing `Current Price: 855` inside the
    row deletes the counting step, and a value can no longer drift from its column.

    Costs tokens -- every label is repeated on every row -- which is why it is only
    done for tables that actually have column names to repeat.
    """
    head = next((i for i, r in enumerate(rows) if header_like(r)), None)
    if head is None:
        return rows
    names = rows[head]
    out = rows[: head + 1]
    for row in rows[head + 1:]:
        if len(row) < 3 or not any(c for c in row[1:]):
            out.append(row)              # a section heading like `Banking*`
            continue
        labelled = [row[0]] + [f"{names[i]}: {c}" for i, c in enumerate(row)
                               if i and c and i < len(names) and names[i]]
        out.append(labelled)
    return out


def merge_header(rows: list[list[str]]) -> list[list[str]]:
    """a header split over two rows -> one row of whole column names.

    These reports print `Current` and `Price` as two stacked header cells, so the
    table arrives with a header reading

        Company | Reco | Reco | Current | Target | Research | ...
        16-Nov-22 | Date | Price | Price | Price | Call | ...

    and `Current Price` is left as something the reader has to infer. `llama3.2:3b`
    infers it wrong in one direction every time -- asked for Axis Bank's current
    price it answers 980, which is the target, and asked for the target it answers
    855, which is the current. Not a reasoning failure: the columns genuinely are
    not labelled. Joined into `Current Price`, both questions answer correctly.

    The lower row is the one carrying `Date` and `Price`; the row above it is the
    upper header. A cell spanning several columns (`Valuation (*P/BV, P/E)` over
    FY22..FY25E) runs out of partners, so the last upper cell keeps prefixing.
    """
    for h, row in enumerate(rows[:6]):
        if h and header_like(row):
            upper, lower = rows[h - 1], row
            merged = []
            for i, low in enumerate(lower):
                up = upper[i] if i < len(upper) else (upper[-1] if upper else "")
                # the lower row leads with the report's date, not a column name
                merged.append(up if DATE_CELL.fullmatch(low) or not low
                              else f"{up} {low}".strip() if up and up != low else low)
            return rows[:h - 1] + [merged] + rows[h + 1:]
    return rows


def caption(rows: list[list[str]]) -> str:
    """one English line saying what the table is a table of.

    Row labels are the first cell of each row -- on these reports that is the
    company, the index or the line item, which is exactly the word a question
    names. Without this the chunk is digits, and digits embed near nothing.
    """
    if not rows:
        return ""
    headers = " ".join(c for row in rows[:2] for c in row if c)
    labels, seen = [], set()
    for row in rows[1:]:
        first = row[0].strip() if row else ""
        if 2 < len(first) < 40 and not re.fullmatch(r"[\d\s.,%()\-]+", first) \
                and first.lower() not in seen:
            seen.add(first.lower())
            labels.append(first)
    line = f"Table with columns: {headers}."
    return f"{line} Rows: {', '.join(labels[:14])}." if labels else line


@lru_cache(maxsize=None)
def pdf_tables(path: str) -> dict[int, list[list[list[str]]]]:
    """{page: [table, ...]} read from the pdf's own text layer.

    `hi_res` gets tables by rasterizing the page and running OCR over the picture,
    which on a morning daily destroys them: `Bandhan Bank | | | | | | ao | 20g` where
    the row reads `25-Jul-22 | 285 | 229 | 338 | Accumulate | 19% | -20%`. Five rows
    in 179 survived it. Every one of these pdfs is digital and carries that row as
    real text, so it is read rather than photographed.

    Layout detection is still unstructured's -- it is good at *finding* things and
    only bad at reading pictures of them. This replaces the cells, nothing else.
    """
    out: dict[int, list[list[list[str]]]] = defaultdict(list)
    with pymupdf.open(path) as pdf:
        for number, page in enumerate(pdf, start=1):
            for table in page.find_tables().tables:
                rows = [[(cell or "").replace("\n", " ").strip() for cell in row]
                        for row in table.extract()]
                rows = [r for r in rows if any(r)]
                if rows:
                    out[number].append(rows)
    return dict(out)


def text_layer_rows(doc: Document) -> list[list[str]] | None:
    """the loader's table, re-read from the text layer. None if it cannot be."""
    directory = doc.metadata.get("file_directory")
    filename = doc.metadata.get("filename")
    page = doc.metadata.get("page_number")
    if not (directory and filename and page):
        return None
    path = Path(directory) / filename
    if not path.is_file():
        return None

    tables = pdf_tables(str(path)).get(page)
    if not tables:
        return None                      # scanned page, or no table where one was seen

    # a page can hold more than one table and the two readers need not agree on
    # their order, so pair them by the row labels they share instead of by position.
    ocr = doc.page_content.lower()
    overlap = lambda rows: sum(1 for r in rows
                               if r and len(r[0]) > 3 and r[0].lower()[:8] in ocr)
    return max(tables, key=overlap)


DATE_CELL = re.compile(r"\b(\d{1,2})-([A-Za-z]{3})[A-Za-z]*-(\d{2,4})\b")


def table_date(rows: list[list[str]]) -> str | None:
    """the date printed in the table's own header row, if it has one.

    A reco table is as of the previous *trading* day, not the previous day: `17th
    Nov 2022.pdf` carries the table headed `16-Nov-22`, and `12th_September_2022`
    carries `09-SEP-2022`, three days back over a weekend. Meanwhile the market data
    tables in those same files are same day.

    So the date belongs to the table and not to the pdf it arrived in, which is why
    this is read per table rather than shifted by a fixed offset from the filename.
    """
    for row in rows[:6]:
        if header_like(row):
            for cell in row:
                m = DATE_CELL.fullmatch(cell)
                if m and (month := MONTHS.get(m.group(2)[:3].lower())):
                    day, year = m.group(1), m.group(3)
                    return f"{year if len(year) == 4 else f'20{year}'}-{month}-{int(day):02d}"
    return None


def render_table(doc: Document) -> tuple[str, str | None]:
    """the table as pipe rows, and the date printed on it.

    The date is read before the header rows are merged, because merging consumes the
    cell it is printed in. It is stated in words at the top of the chunk as well as
    kept in the metadata -- a row of prices means nothing without the day it is from,
    and the model can only say the day if it can see it.
    """
    rows = text_layer_rows(doc) or table_rows(doc.metadata.get("text_as_html") or "")
    if not rows:
        # no structure inferred -- keep the loader's text rather than lose the table
        return clean_text(doc.page_content), None

    date = table_date(rows)
    rows = label_rows(merge_header(rows))
    lines = [line for line in (" | ".join(r).strip(" |") for r in rows) if line.strip(" |")]
    head = caption(rows) + (f" All figures are as of {date}." if date else "")
    return head + "\n" + "\n".join(lines), date


def split_tables(docs: list[Document]) -> list[Document]:
    """a table over the embedding limit, cut by rows, each piece captioned with
    only the rows it actually holds.

    Past the limit nomic truncates without a word -- a vector built from half a
    table, and no error anywhere.

    The caption used to be copied verbatim from the whole table onto every piece.
    caption()'s own row list is capped at 14, and on the Company Reco table (70+
    rows across banking, IT, auto, cement...) the first 14 labels are always the
    banking section -- so every non-banking piece embedded, and matched the
    literal rescue, under a caption naming Axis Bank and HDFC Bank while its own
    rows were Mindtree or Hero MotoCorp. Rebuilding the caption per piece from
    that piece's own first column (the same rule caption() uses) fixes both: the
    embedding reflects what the chunk actually says, and "axis bank" only matches
    the pieces that carry Axis Bank's row.
    """
    budget = int(EMBED_TOKEN_LIMIT * 0.9)
    out: list[Document] = []
    for doc in docs:
        if doc.metadata.get("category") != "Table" or len(ENC.encode(doc.page_content)) <= budget:
            out.append(doc)
            continue

        head, *rows = doc.page_content.split("\n")
        # split the pre-split caption into its column-names sentence and its date
        # suffix, dropping the stale "Rows: ..." list -- each piece gets its own
        columns_part, date_suffix = head, ""
        marker = " All figures are as of "
        if marker in head:
            columns_part, _, tail = head.partition(marker)
            date_suffix = marker + tail
        columns_part = columns_part.split(" Rows:")[0]

        head_cost = len(ENC.encode(head))     # budgeting estimate only, see above
        pieces, group, cost = [], [], head_cost
        for row in rows:
            row_cost = len(ENC.encode(row))
            if group and cost + row_cost > budget:
                pieces.append(group)
                group, cost = [], head_cost
            group.append(row)
            cost += row_cost
        if group:
            pieces.append(group)

        for i, piece in enumerate(pieces):
            part = copy.deepcopy(doc)
            labels, seen = [], set()
            for line in piece:
                first = line.split(" | ", 1)[0].strip()
                if 2 < len(first) < 40 and not re.fullmatch(r"[\d\s.,%()\-]+", first) \
                        and first.lower() not in seen:
                    seen.add(first.lower())
                    labels.append(first)
            rows_part = f" Rows: {', '.join(labels[:14])}." if labels else ""
            part.page_content = columns_part + rows_part + date_suffix + "\n" + "\n".join(piece)
            part.metadata["table_part"] = f"{i + 1}/{len(pieces)}"
            out.append(part)
    return out


# ------------------------------------------------------------------- prepare

def prepare(docs: list[Document]) -> list[Document]:
    """drop the junk, render tables, glue paragraphs back across pages."""
    out: list[Document] = []
    for doc in docs:
        category = doc.metadata.get("category")
        if category in JUNK:
            continue
        printed = None
        if category == "Table":
            text, printed = render_table(doc)
        else:
            text = clean_text(doc.page_content)
        if not text:
            continue

        doc = copy.deepcopy(doc)          # do not scribble on the loader's objects
        doc.page_content = text
        doc.metadata["pages"] = [doc.metadata.get("page_number")]
        if printed:
            doc.metadata["printed_date"] = printed

        # layout detection runs a page at a time, so a paragraph running over the
        # bottom of a page comes back as two elements. put it back together.
        if out:
            prev = out[-1]
            if (prev.metadata.get("category") == category == "NarrativeText"
                    and prev.metadata["pages"][-1] != doc.metadata["pages"][0]
                    and prev.page_content[-1] not in ENDINGS):
                prev.page_content += " " + doc.page_content
                prev.metadata["pages"] += doc.metadata["pages"]
                continue
        out.append(doc)
    return out


def sections(docs: list[Document]) -> list[Document]:
    """a Title starts a section, everything after it is glued on until the next.

    Without this the index fills with 40 character fragments that carry no context
    and match everything weakly. Tables never join a section.
    """
    built: list[Document] = []
    current: Document | None = None
    for doc in docs:
        category = doc.metadata.get("category")
        if category == "Table":
            built.append(doc)
            current = None
        elif category == "Title" or current is None:
            current = copy.deepcopy(doc)
            current.metadata["pages"] = list(doc.metadata["pages"])
            built.append(current)
        else:
            current.page_content += "\n\n" + doc.page_content
            current.metadata["pages"] += doc.metadata["pages"]

    for section in built:
        section.metadata["pages"] = sorted({p for p in section.metadata["pages"] if p})
    return built


# ----------------------------------------------------------------------- tag

MONTHS = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
          "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}


def date_from_filename(name: str) -> str | None:
    """the publication date, if the filename carries one.

    It is nowhere in the pdf metadata -- for a dated report it exists only in the
    filename and in the printed header, and prepare() drops headers. None is a
    normal answer: a management meet note is not a dated daily.
    """
    m = re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?[ _-]({'|'.join(MONTHS)})[a-z]*[ _-](\d{{4}})",
                  name, re.I)
    if m:
        return f"{m.group(3)}-{MONTHS[m.group(2)[:3].lower()]}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})", name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def tag(docs: list[Document], source: str) -> list[Document]:
    """a stable id and a readable source -- the loader's metadata has neither, and
    the citations, the date filter and the answer all key on them.

    `date` is what the chunk is *about* and is what the filter searches: the date
    printed on the table when it prints one, the publication date otherwise.
    `published` is always the filename's, so a chunk can still say where it came
    from -- the 16-Nov reco table and the 17-Nov commentary that shipped with it are
    both findable, by different dates, which is the point.
    """
    published = date_from_filename(source)
    for i, doc in enumerate(docs):
        doc.metadata.update(chunk_id=f"{source}#{i}", source=source, published=published,
                            date=doc.metadata.get("printed_date") or published)
        doc.metadata["pages"] = doc.metadata.get("pages") or [doc.metadata.get("page_number")]
    return docs


def chunks_for(elements: list[Document], source: str) -> list[Document]:
    """one document's elements -> its tagged chunks."""
    built = split_tables(sections(prepare(elements)))
    tables = [d for d in built if d.metadata.get("category") == "Table"]
    prose = [d for d in built if d.metadata.get("category") != "Table"]
    return tag(splitter().split_documents(prose) + tables, source)
