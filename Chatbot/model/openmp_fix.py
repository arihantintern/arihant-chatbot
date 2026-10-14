"""one OpenMP runtime per process, which is not what pip leaves you with.

THE CRASH THIS PREVENTS

    OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib already
    initialized.
    Abort trap: 6

The whole server process dies -- not the request, the process. Under
`uvicorn --reload` that is worse than it sounds: the reloader parent keeps the
listening socket open and only restarts a child when a *file* changes, never when
one dies. So the port stays open, connections are still accepted, and nothing ever
answers them. The browser sits there until its own timeout and reports "the
assistant took too long", which is the one explanation that is not true.

WHY THERE ARE TWO COPIES

Three wheels in this venv ship their own build of the same LLVM OpenMP runtime:

    torch/lib/libomp.dylib          <- loaded eagerly, at `import torch`
    faiss/.dylibs/libomp.dylib      <- loaded lazily, at the first faiss search
    sklearn/.dylibs/libomp.dylib    <- (harmless so far; sklearn is never used
                                       in a parallel region here)

Nothing in this project asks for torch. It arrives underneath us:

    chain -> langchain_community -> langchain_text_splitters/__init__
          -> .spacy -> spacy -> thinc.compat -> `import torch`

and `unstructured[pdf]` is what put spacy and torch in the venv in the first
place. Uninstalling torch is not an option either -- `STRATEGY = "hi_res"` in
config.py means ingest.py genuinely needs it, through unstructured_inference.

So torch loads its libomp at import and faiss loads a second one at the first
`IndexFlat.search`. libomp registers itself in a per-process slot on first use;
the second copy finds that slot taken and calls abort(). The first question after
a restart is what triggers it, because that is the first faiss search.

THE FIX

The error message says it: "ensure that only a single OpenMP runtime is linked
into the process". This points faiss's `@loader_path/.dylibs/libomp.dylib` at
torch's copy with a symlink, so dyld resolves both to one file and there is only
ever one runtime to register.

Checked before shipping it, because "they are both libomp" is an assumption and
not a fact:

  * every one of the 40 OpenMP symbols `libfaiss.dylib` and `_swigfaiss.abi3.so`
    import is exported by torch's build -- nothing goes unresolved. The 7 symbols
    only faiss's copy has (`omp_get_device_from_uid` and friends) are device-offload
    entry points faiss never calls.
  * faiss results are unchanged: exact agreement with a brute-force numpy top-10
    over 5000x128, distances within 4e-06, and identical output at 8 threads.

Not `KMP_DUPLICATE_LIB_OK=TRUE`, which is the answer everyone reaches for first.
That flag does not remove the second runtime, it only silences the check -- two
thread pools then fight over the same cores, and llvm's own wording for what
follows is "may cause crashes or silently produce incorrect results".

RUN IT AFTER EVERY pip install

A reinstall of faiss-cpu restores its bundled copy and the crash comes back:

    python openmp_fix.py

Idempotent, and it says which of the two it did.
"""
from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path


def _site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def dedupe(verbose: bool = True) -> str:
    """Point faiss's libomp at torch's. Returns what happened, for the caller."""
    sp = _site_packages()
    keep = sp / "torch" / "lib" / "libomp.dylib"      # loaded first, so it wins
    dupe = sp / "faiss" / ".dylibs" / "libomp.dylib"

    def say(msg: str) -> str:
        if verbose:
            print(f"  [openmp] {msg}")
        return msg

    if not dupe.exists() and not dupe.is_symlink():
        return say("no faiss libomp here -- nothing to do")
    if not keep.exists():
        # torch absent means faiss's copy is the only one; leave it alone.
        return say("no torch libomp here -- faiss's copy is already the only one")

    if dupe.is_symlink() and dupe.resolve() == keep.resolve():
        return say("already deduped -- faiss and torch share one runtime")

    backup = dupe.with_suffix(".dylib.orig")
    if not backup.exists():
        os.replace(dupe, backup)
    elif dupe.exists() and not dupe.is_symlink():
        dupe.unlink()

    dupe.symlink_to(keep)
    return say(f"deduped: {dupe.relative_to(sp)} -> {keep.relative_to(sp)}")


def duplicate_runtimes() -> list[Path]:
    """Distinct libomp *files* that could end up in one process. len() > 1 is the
    crash waiting to happen; used by api.py to warn at startup rather than let the
    first question take the server down."""
    sp = _site_packages()
    candidates = [sp / "torch" / "lib" / "libomp.dylib",
                  sp / "faiss" / ".dylibs" / "libomp.dylib"]
    return sorted({p.resolve() for p in candidates if p.exists()})


if __name__ == "__main__":
    if sys.platform != "darwin":
        print("  [openmp] not macOS -- the duplicate-libomp abort is a mac wheel "
              "problem; nothing to do")
        raise SystemExit(0)
    dedupe()
    left = duplicate_runtimes()
    print(f"  [openmp] {len(left)} OpenMP runtime(s) reachable: "
          + ", ".join(str(p) for p in left))
    raise SystemExit(0 if len(left) <= 1 else 1)
