"""Test whether verovio thread-safety can be worked around by:

Strategy A: thread-local toolkit constructed under the lock, reused.
Strategy B: initializer that constructs a toolkit in the worker thread at pool
            startup (so font loading is first-touch per thread, not concurrent).
Strategy C: cache one toolkit and reuse it across threads under a lock.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import verovio

_CACHE = os.path.expanduser("~/.cache/camat/downloads")
_CANDIDATES = sorted(os.path.join(_CACHE, f) for f in os.listdir(_CACHE) if f.endswith(".mei"))
MEI_SAMPLES = [open(p, encoding="utf-8").read() for p in _CANDIDATES[:3]]
print(f"loaded {len(MEI_SAMPLES)} MEI samples")

LOCK = threading.Lock()

# ----- Strategy A: thread-local toolkit -----
_TLS = threading.local()

def tls_toolkit():
    tk = getattr(_TLS, "tk", None)
    if tk is None:
        print(f"[t={threading.get_ident()}] constructing thread-local toolkit")
        with LOCK:
            tk = verovio.toolkit(True)
        _TLS.tk = tk
    return tk

def run_A(idx):
    tk = tls_toolkit()
    with LOCK:
        tk.setOptions({"inputFrom": "mei"})
        ok = tk.loadData(MEI_SAMPLES[idx % len(MEI_SAMPLES)])
        pages = tk.getPageCount()
    return f"A idx={idx} ok={ok} pages={pages}"


# ----- Strategy B: initializer-based warmup -----
def init_worker():
    tid = threading.get_ident()
    print(f"[t={tid}] init_worker constructing toolkit")
    with LOCK:
        _TLS.tk = verovio.toolkit(True)
    print(f"[t={tid}] init_worker done")

def run_B(idx):
    tk = _TLS.tk
    with LOCK:
        tk.setOptions({"inputFrom": "mei"})
        ok = tk.loadData(MEI_SAMPLES[idx % len(MEI_SAMPLES)])
        pages = tk.getPageCount()
    return f"B idx={idx} ok={ok} pages={pages}"


# ----- Strategy C: single shared main-thread toolkit + global lock -----
_SHARED_TK = None

def run_C(idx):
    with LOCK:
        _SHARED_TK.setOptions({"inputFrom": "mei"})
        ok = _SHARED_TK.loadData(MEI_SAMPLES[idx % len(MEI_SAMPLES)])
        pages = _SHARED_TK.getPageCount()
    return f"C idx={idx} ok={ok} pages={pages}"


def main():
    print("\n--- Strategy A: thread-local toolkit ---")
    with ThreadPoolExecutor(max_workers=2) as ex:
        print(list(ex.map(run_A, range(4))))

    print("\n--- Strategy B: initializer-based warmup ---")
    with ThreadPoolExecutor(max_workers=2, initializer=init_worker) as ex:
        print(list(ex.map(run_B, range(4))))

    print("\n--- Strategy C: shared main-thread toolkit ---")
    global _SHARED_TK
    _SHARED_TK = verovio.toolkit(True)  # constructed on main thread
    with ThreadPoolExecutor(max_workers=2) as ex:
        print(list(ex.map(run_C, range(4))))


if __name__ == "__main__":
    main()
