"""Minimal Verovio threading reproducer.

This script isolates the thread-safety issue by calling verovio.toolkit()
directly from multiple threads under a lock, mimicking what partitura's
importmei._parse_mei does on MEI load.
"""
from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import verovio


import os

_CACHE = os.path.expanduser("~/.cache/camat/downloads")
_CANDIDATES = sorted(
    os.path.join(_CACHE, f)
    for f in os.listdir(_CACHE)
    if f.endswith(".mei")
) if os.path.isdir(_CACHE) else []
if not _CANDIDATES:
    raise SystemExit(
        "No cached .mei files under ~/.cache/camat/downloads; run test_parallel_parse.py first."
    )
MEI_SAMPLES = [open(p, encoding="utf-8").read() for p in _CANDIDATES[:3]]
print(f"loaded {len(MEI_SAMPLES)} MEI samples from cache")

LOCK = threading.Lock()


def load_once(idx: int, use_lock: bool) -> str:  # noqa: C901
    idx = idx % len(MEI_SAMPLES)
    tid = threading.get_ident()
    print(f"[t={tid} idx={idx}] entering", flush=True)
    t0 = time.perf_counter()
    try:
        if use_lock:
            with LOCK:
                tk = verovio.toolkit(True)
                tk.setOptions({"inputFrom": "mei"})
                ok = tk.loadData(MEI_SAMPLES[idx])
                pages = tk.getPageCount()
                status = f"ok={ok} pages={pages}"
                del tk  # force immediate cleanup inside the critical section
        else:
            tk = verovio.toolkit(True)
            tk.setOptions({"inputFrom": "mei"})
            ok = tk.loadData(MEI_SAMPLES[idx])
            pages = tk.getPageCount()
            status = f"ok={ok} pages={pages}"
            del tk
    except Exception as exc:  # noqa: BLE001
        status = f"EXC: {exc!r}"
    dt = time.perf_counter() - t0
    print(f"[t={tid} idx={idx}] exit {status} ({dt*1000:.1f}ms)", flush=True)
    return status


def run(mode: str, use_lock: bool, n_workers: int):
    print(f"\n=== mode={mode} use_lock={use_lock} n_workers={n_workers} ===", flush=True)
    if n_workers <= 1:
        results = [load_once(i, use_lock) for i in range(len(MEI_SAMPLES))]
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            results = list(ex.map(lambda i: load_once(i, use_lock), range(len(MEI_SAMPLES))))
    print(f"results: {results}", flush=True)


def main():
    print(f"verovio at: {verovio.__file__}", flush=True)
    print(f"python: {sys.version}", flush=True)
    print(f"has getResourcePath: {hasattr(verovio.toolkit, 'getResourcePath')}", flush=True)

    # Baseline: serial should always work.
    run("serial", use_lock=False, n_workers=1)

    # Parallel WITHOUT lock — expected to fail based on reported symptoms.
    run("parallel_nolock", use_lock=False, n_workers=2)

    # Parallel WITH lock (same pattern as _PARTITURA_LOAD_LOCK).
    run("parallel_locked", use_lock=True, n_workers=2)


if __name__ == "__main__":
    main()
