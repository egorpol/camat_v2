"""Verify that monkey-patching verovio.toolkit to hand out a main-thread
singleton makes partitura's MEI import thread-safe.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import verovio

_CACHE = os.path.expanduser("~/.cache/camat/downloads")
_CANDIDATES = sorted(os.path.join(_CACHE, f) for f in os.listdir(_CACHE) if f.endswith(".mei"))
print(f"{len(_CANDIDATES)} cached MEI files")

# Step 1: construct a main-thread singleton BEFORE any worker thread touches verovio.
_SHARED_TK = verovio.toolkit(True)
_VEROVIO_LOCK = threading.RLock()  # reentrant so nested callers are OK

# Step 2: monkey-patch `verovio.toolkit` so partitura's `tk = verovio.toolkit(True)`
# hands back our singleton instead of creating a new (broken) one on the worker thread.
_ORIGINAL_TOOLKIT = verovio.toolkit

def _patched_toolkit(*args, **kwargs):
    return _SHARED_TK

verovio.toolkit = _patched_toolkit  # type: ignore[assignment]

# Step 3: import partitura AFTER the patch so its `from verovio import toolkit`
# style imports (if any) pick up our shim. In partitura's importmei.py it does
# `import verovio` + `verovio.toolkit(True)`, so attribute-level access sees our patch.
import partitura  # noqa: E402


def _load(path):
    tid = threading.get_ident()
    t0 = time.perf_counter()
    # Use the lock to serialize partitura's internal verovio use since multiple
    # workers would otherwise stomp on the shared toolkit's state mid-parse.
    with _VEROVIO_LOCK:
        score = partitura.load_score(path)
    dt = time.perf_counter() - t0
    parts = [p for p in score] if score else []
    n_notes = sum(len(p.notes_tied) for p in parts if hasattr(p, "notes_tied"))
    return f"t={tid} path={os.path.basename(path)} parts={len(parts)} notes_tied={n_notes} elapsed={dt*1000:.1f}ms"


def main():
    files = _CANDIDATES[:3]
    print("\n=== parallel load via patched verovio + lock ===")
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r in ex.map(_load, files):
            print(r)


if __name__ == "__main__":
    main()
