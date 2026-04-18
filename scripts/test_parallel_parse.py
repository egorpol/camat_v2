"""Standalone autotest for parse_files with n_jobs>1.

Run from repo root with:
    python scripts/test_parallel_parse.py

This script:
- Warms the remote download cache at n_jobs=1 (so network/cache is stable).
- Runs the same file list at n_jobs=1 and n_jobs=2, capturing stdout/stderr.
- Counts success/failure per run and prints a compact diagnostic.
- Adds instrumentation so we can see whether _VEROVIO_LOCK / _PARTITURA_LOAD_LOCK
  are actually held while Verovio / partitura importers run under n_jobs>1.
"""
from __future__ import annotations

import io
import os
import sys
import time
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout

# Make sure we import the repo-local camat, not a site-packages copy.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import camat  # noqa: E402
from camat import partitura_backend as pb  # noqa: E402
from camat import quiet_utils as qu  # noqa: E402
from camat.parser_registry import parse_files  # noqa: E402


FILE_SOURCES = [
    "https://raw.githubusercontent.com/trompamusic-encodings/Beethoven_Op31_No3_HenleUrtext/refs/heads/master/Beethoven_Op31_No3_3-HenleUrtext.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.0/Music/Complete_examples/Bach-JS_Ein_feste_Burg.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_3.0/Music/Complete_examples/Mozart_Fuge_G_minor.mei",
]


def _instrument_locks():
    """Wrap key functions to record who holds which lock and when."""
    events = []
    events_lock = threading.Lock()

    def record(kind, detail):
        with events_lock:
            events.append((time.perf_counter(), threading.get_ident(), kind, detail))

    original_convert = pb._convert_mei_with_verovio_for_partitura

    def traced_convert(*args, **kwargs):
        record("verovio:enter", args[0] if args else kwargs.get("mei_path"))
        # Verify that _VEROVIO_LOCK is actually free before acquire and locked
        # inside. We can't inspect from outside, but we can time the wait.
        t0 = time.perf_counter()
        try:
            result = original_convert(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            record("verovio:exit", f"elapsed={dt:.3f}s")
        return result

    # Patch the INNER pt.load_score call to record enter/exit strictly inside
    # the critical section (the wrapper's own lock acquisition would otherwise
    # race with our tracing and produce false overlap reports).
    import partitura as _pt  # noqa: E402

    original_load = _pt.load_score

    def traced_load(path, *args, **kwargs):
        record("partitura_load:enter", path)
        t0 = time.perf_counter()
        try:
            result = original_load(path, *args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            record("partitura_load:exit", f"elapsed={dt:.3f}s")
        return result

    _pt.load_score = traced_load  # type: ignore[assignment]
    # partitura_backend imported `pt` at module import; patch that ref too.
    pb.pt.load_score = traced_load  # type: ignore[assignment]

    pb._convert_mei_with_verovio_for_partitura = traced_convert  # type: ignore[assignment]
    pb._load_partitura_score = traced_load  # type: ignore[assignment]

    return events


def run_once(n_jobs: int, events_sink):
    print(f"\n=== run: n_jobs={n_jobs} ===", flush=True)
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    t0 = time.perf_counter()
    error = None
    results = dfs_by_name = None
    try:
        # Capture only our own prints; Verovio C++ stderr goes to FD2 directly
        # and won't be captured here, which is exactly what we want so we can
        # see it on the real console during the test.
        with redirect_stdout(stdout_buf):
            results, dfs_by_name, _ = parse_files(
                FILE_SOURCES,
                parsing_backend="partitura",
                quiet_native_warnings=False,
                show_progress=False,
                display_preview_df_pitch=False,
                display_preview_df_events=False,
                cleanup_remote=False,  # keep cache hot for subsequent runs
                return_plots=False,
                backend="none",
                use_remote_cache=True,
                remote_cache_dir=None,
                n_jobs=n_jobs,
                print_parsed_summary=False,
                try_verovio_mei_conversion=True,
                allow_music21_fallback=False,
                include_xml_ids=True,
                parse_enharmonic=True,
            )
    except Exception as exc:  # noqa: BLE001
        error = exc

    elapsed = time.perf_counter() - t0
    out = stdout_buf.getvalue()
    err = stderr_buf.getvalue()

    print(f"elapsed: {elapsed:.2f}s", flush=True)
    if error is not None:
        print(f"FATAL error: {error!r}", flush=True)
        traceback.print_exc()
        return False

    names = list(dfs_by_name or {})
    # Each successfully parsed MEI yields 2 dataframes (pitch + events).
    successful_files = sorted({n.rsplit("_", 1)[0] for n in names if n.endswith("_pitch")})
    ok = len(successful_files)
    print(f"success: {ok}/{len(FILE_SOURCES)} files -> {successful_files}", flush=True)

    # Print the last few log lines so we can see per-file failure messages.
    tail = "\n".join(out.strip().splitlines()[-20:])
    if tail:
        print("--- tail of parser log ---", flush=True)
        print(tail, flush=True)
        print("--- end tail ---", flush=True)

    return ok == len(FILE_SOURCES)


def summarize_events(events):
    print("\n--- lock/native-call timeline (first 30 events) ---", flush=True)
    for t, tid, kind, detail in events[:30]:
        print(f"  t={t:.4f} thread={tid} {kind}: {detail}", flush=True)
    if len(events) > 30:
        print(f"  ... {len(events) - 30} more events ...", flush=True)


def check_lock_overlap(events):
    """Detect any two threads that were simultaneously inside the Verovio or
    partitura critical sections. If either happens, our lock is broken."""
    problems = []
    for kind_enter, kind_exit in [
        ("verovio:enter", "verovio:exit"),
        ("partitura_load:enter", "partitura_load:exit"),
    ]:
        active = {}
        spans = []
        for t, tid, kind, detail in sorted(events, key=lambda e: e[0]):
            if kind == kind_enter:
                active[tid] = t
            elif kind == kind_exit and tid in active:
                spans.append((active.pop(tid), t, tid))
        spans.sort()
        for i, (s, e, tid) in enumerate(spans):
            for s2, e2, tid2 in spans[i + 1:]:
                if tid2 == tid:
                    continue
                if s2 < e:
                    problems.append(
                        f"OVERLAP in {kind_enter[:-6]}: thread {tid} {s:.3f}-{e:.3f} vs thread {tid2} {s2:.3f}-{e2:.3f}"
                    )
    if problems:
        print("\n!!! LOCK OVERLAP DETECTED !!!", flush=True)
        for p in problems:
            print(p, flush=True)
    else:
        print("\nOK: no overlap inside Verovio or partitura importer critical sections.", flush=True)


def main():
    print(f"camat at: {camat.__file__}", flush=True)
    print(f"pb at:    {pb.__file__}", flush=True)
    print(f"qu at:    {qu.__file__}", flush=True)
    print(
        f"has _VEROVIO_LOCK={hasattr(pb, '_VEROVIO_LOCK')} "
        f"has _PARTITURA_LOAD_LOCK={hasattr(pb, '_PARTITURA_LOAD_LOCK')} "
        f"has _NATIVE_FD_LOCK={hasattr(qu, '_NATIVE_FD_LOCK')}",
        flush=True,
    )

    events = _instrument_locks()

    # Warm-up (serial): cache files and verify baseline works.
    ok_serial = run_once(n_jobs=1, events_sink=events)

    # Parallel: this is what the user reports failing.
    ok_parallel = run_once(n_jobs=2, events_sink=events)

    summarize_events(events)
    check_lock_overlap(events)

    print("\n=== SUMMARY ===", flush=True)
    print(f"serial   (n_jobs=1): {'OK' if ok_serial else 'FAIL'}", flush=True)
    print(f"parallel (n_jobs=2): {'OK' if ok_parallel else 'FAIL'}", flush=True)
    sys.exit(0 if (ok_serial and ok_parallel) else 1)


if __name__ == "__main__":
    main()
