"""Verify testing_annot_stats.ipynb's common-notation-only configuration.

Replays the notebook's parse_files(...) call with the same kwargs, captures
every log line, and asserts that none of them mention 'mensural' (other than
the guardrail warning that specifically routes misplaced mensural MEI to the
dedicated notebook).
"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from camat.parser_registry import parse_files  # noqa: E402


FILE_SOURCES = [
    "https://raw.githubusercontent.com/trompamusic-encodings/Beethoven_Op31_No3_HenleUrtext/refs/heads/master/Beethoven_Op31_No3_3-HenleUrtext.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.0/Music/Complete_examples/Bach-JS_Ein_feste_Burg.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_3.0/Music/Complete_examples/Mozart_Fuge_G_minor.mei",
]


def main() -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        results, dfs_by_name, _ = parse_files(
            FILE_SOURCES,
            parsing_backend="partitura",
            quiet_native_warnings=False,
            show_progress=False,
            display_preview_df_pitch=False,
            display_preview_df_events=False,
            cleanup_remote=False,
            return_plots=False,
            backend="none",
            use_remote_cache=True,
            n_jobs=2,
            print_parsed_summary=False,
            try_verovio_mei_conversion=True,
            allow_music21_fallback=False,
            include_xml_ids=True,
            parse_enharmonic=True,
            # common-notation only: explicitly disable mensural paths
            normalize_mensural_durations=False,
            inject_missing_meter_signature=False,
            prefer_verovio_for_mensural=False,
            use_verovio_mensural_timing=False,
        )

    log_text = buf.getvalue()
    ok_files = sorted({k.rsplit("_", 1)[0] for k in dfs_by_name if k.endswith("_pitch")})

    print("=== captured parser log ===")
    print(log_text or "(empty)")
    print("=== end log ===\n")

    print(f"parsed {len(ok_files)}/{len(FILE_SOURCES)} files: {ok_files}")

    mensural_hits = [
        line for line in log_text.splitlines()
        if "mensural" in line.lower()
    ]
    if mensural_hits:
        print("\nFAIL: mensural-related log lines detected:")
        for line in mensural_hits:
            print(f"  - {line}")
        return 1

    if len(ok_files) != len(FILE_SOURCES):
        print("\nFAIL: not all files parsed successfully")
        return 1

    print("\nOK: common-notation run emitted no mensural log lines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
