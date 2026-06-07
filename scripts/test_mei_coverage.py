"""MEI element coverage autotest for the partitura backend.

Run from repo root with:
    python scripts/test_mei_coverage.py

For each MEI test file the script:
  1. Parses the raw MEI XML and counts every music-relevant element.
  2. Runs ``parse_files`` with the same settings as ``testing_annot_stats.ipynb``.
  3. Compares df_events type counts against the raw element counts and reports
     any music-relevant element that failed to appear in df_events.
  4. Checks that df_pitch carries the new note-attachment columns and that at
     least one non-empty value shows up whenever the corresponding MEI element
     is present in the source.

The script exits with a non-zero status if any music-relevant element is
missing from df_events where it should have been captured. Elements classified
as structural / metadata are expected to be absent and are treated as skipped.
"""
from __future__ import annotations

import collections
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from camat.parser_registry import parse_files  # noqa: E402


# 3 MEI examples covering MEI 3.0, MEI 5.0 and a richly-annotated modern piano
# score from the trompa project.
FILE_SOURCES: List[str] = [
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.0/Music/Complete_examples/Bach-JS_Ein_feste_Burg.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_3.0/Music/Complete_examples/Mozart_Fuge_G_minor.mei",
    "https://raw.githubusercontent.com/trompamusic-encodings/Beethoven_Op31_No3_HenleUrtext/refs/heads/master/Beethoven_Op31_No3_3-HenleUrtext.mei",
]


# MEI tag -> expected event type in df_events. ``None`` means the element is
# expected to be represented through a different channel (e.g. rest rows come
# from partitura, not MEI). Tags not in this table are treated as structural
# metadata and ignored.
EXPECTED_EVENT_TYPE: Dict[str, str] = {
    # Already-handled core control / span / text elements.
    "annot": "annot",
    "arpeg": "arpeg",
    "barLine": "barline",
    "breath": "breath",
    "caesura": "caesura",
    "dir": "direction",
    "dynam": "dynamic",
    "fermata": "fermata",
    "gliss": "gliss",
    "hairpin": "hairpin",
    "harm": "harm",
    "harpPedal": "harp_pedal",
    "phrase": "phrase",
    "reh": "reh",
    "repeatMark": "repeat_mark",
    "slur": "slur",
    "syl": "lyric",
    "tempo": "tempo",
    "tie": "tie",
    # Newly-handled elements.
    "trill": "trill",
    "mordent": "mordent",
    "turn": "turn",
    "ornam": "ornament",
    "bTrem": "btrem",
    "fTrem": "ftrem",
    "artic": "artic",
    "fing": "fingering",
    "bend": "bend",
    "pedal": "pedal",
    "octave": "octave",
    "ending": "ending",
    "beamSpan": "beam_span",
    "tupletSpan": "tuplet_span",
    "clef": "clef",
    "keySig": "key_sig",
    "meterSig": "meter_sig",
    "mRest": "mrest",
    "multiRest": "multirest",
    "space": "space",
    "custos": "custos",
}

# MEI rests (both regular <rest> and <mRest>) come from partitura's rest_array
# in df_events with type=="rest". We still want explicit <mRest>/<multiRest>
# rows via the MEI path (handled above), but <rest> is intentionally only a
# "rest" row sourced from partitura.
EXPECTED_REST_TYPE = "rest"

# Elements that are note-internal (accid on a <note>) are deliberately not
# emitted as events; the pitch row already carries the accidental info.
NOTE_INTERNAL_TAGS: Set[str] = {"accid"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _raw_mei_tag_counts(mei_path: Path) -> collections.Counter:
    tree = ET.parse(mei_path)
    counts: collections.Counter = collections.Counter()
    for el in tree.iter():
        counts[_local_name(el.tag)] += 1
    return counts


def _raw_mei_note_feature_flags(mei_path: Path) -> Dict[str, bool]:
    """
    Detect whether the MEI has at least one grace note, one note inside a
    slur/tie, one note with an ornament/articulation child. Used to validate
    the df_pitch note-attachment columns.
    """
    flags: Dict[str, bool] = {
        "grace": False,
        "tied": False,
        "slurred": False,
        "articulations": False,
        "ornaments": False,
        "fermata": False,
        "tuplet": False,
    }
    tree = ET.parse(mei_path)
    root = tree.getroot()
    for el in root.iter():
        tag = _local_name(el.tag)
        if tag == "note":
            if el.attrib.get("grace"):
                flags["grace"] = True
            for child in el:
                ctag = _local_name(child.tag)
                if ctag == "artic":
                    flags["articulations"] = True
                elif ctag in {"trill", "mordent", "turn", "ornam"}:
                    flags["ornaments"] = True
        elif tag in {"slur"}:
            flags["slurred"] = True
        elif tag == "tie":
            flags["tied"] = True
        elif tag == "fermata":
            flags["fermata"] = True
        elif tag in {"tuplet", "tupletSpan"}:
            flags["tuplet"] = True
    return flags


def _resolve_local_mei(url: str) -> Path:
    """Best-effort: use /tmp/camat_mei_inventory cache first (offline-friendly),
    fall back to the CAMAT remote download cache used by parse_files."""
    name_map = {
        "Bach-JS_Ein_feste_Burg.mei": "bach.mei",
        "Mozart_Fuge_G_minor.mei": "mozart.mei",
        "Beethoven_Op31_No3_3-HenleUrtext.mei": "beethoven.mei",
    }
    stem = url.rsplit("/", 1)[-1]
    local = Path("/tmp/camat_mei_inventory") / name_map.get(stem, stem)
    if local.exists():
        return local
    # Fallback: CAMAT cache lives under ~/.cache/camat/downloads/<slug>.mei.
    from camat.music_utils import _cached_download_filename, get_download_cache_dir  # type: ignore

    cache_dir = Path(get_download_cache_dir())
    candidate = cache_dir / _cached_download_filename(url)
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"Cannot locate cached copy of {stem}; run the notebook once or download to /tmp/camat_mei_inventory first."
    )


def run() -> int:
    results, dfs_by_name, _df_processed = parse_files(
        FILE_SOURCES,
        parsing_backend="partitura",
        quiet_native_warnings=True,
        dedupe_weaker_text_events=True,
        print_parsed_summary=False,
        filter_zero_duration=True,
        adjust_fractional_duration=True,
        parse_enharmonic=False,
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        cleanup_remote=False,
        return_plots=False,
        use_remote_cache=True,
        n_jobs=2,
        normalize_mensural_durations=False,
        inject_missing_meter_signature=False,
        prefer_verovio_for_mensural=False,
        use_verovio_mensural_timing=False,
    )

    overall_issues: List[str] = []
    print("\n=== MEI Element Coverage Report ===\n")

    for url, entry in zip(FILE_SOURCES, results):
        label = entry.get("name", url.rsplit("/", 1)[-1])
        print(f"\n--- {label} ---")
        df_events = entry.get("df_events")
        df_pitch = entry.get("df_pitch")
        if df_events is None or df_pitch is None:
            overall_issues.append(f"{label}: missing df_events or df_pitch")
            print("  [FAIL] df_events or df_pitch missing in result entry")
            continue

        mei_path = _resolve_local_mei(url)
        tag_counts = _raw_mei_tag_counts(mei_path)
        event_type_counts = df_events["type"].value_counts().to_dict()

        # 1) Coverage: for every expected tag present in the file, assert at
        # least one matching event row.
        tag_rows: List[Tuple[str, int, str, int, str]] = []
        for tag, expected_type in EXPECTED_EVENT_TYPE.items():
            src_count = int(tag_counts.get(tag, 0))
            if src_count == 0:
                continue
            got = int(event_type_counts.get(expected_type, 0))
            status = "OK" if got > 0 else "MISSING"
            tag_rows.append((tag, src_count, expected_type, got, status))
            if got == 0:
                overall_issues.append(
                    f"{label}: MEI <{tag}> x{src_count} -> df_events type={expected_type!r} missing"
                )

        # 2) Rests: partitura must emit at least one rest row when <rest>,
        # <mRest> or <multiRest> occur.
        rest_source = sum(tag_counts.get(t, 0) for t in ("rest", "mRest", "multiRest"))
        rest_events = int(event_type_counts.get(EXPECTED_REST_TYPE, 0))
        if rest_source > 0 and rest_events == 0:
            overall_issues.append(
                f"{label}: MEI rests x{rest_source} -> no type=='rest' rows in df_events"
            )

        print(
            f"  {'MEI element':<14}{'src':>6}{'event_type':>18}{'got':>8}  status"
        )
        for row in tag_rows:
            tag, src, et, got, status = row
            marker = " " if status == "OK" else "!"
            print(f"  {marker} {tag:<12}{src:>6}{et:>18}{got:>8}  {status}")
        print(f"  rest(source={rest_source} got_type=rest:{rest_events})")

        # 3) df_pitch note attachments.
        source_flags = _raw_mei_note_feature_flags(mei_path)
        print("  note-attachment columns on df_pitch:")
        att_cols = [
            "grace",
            "tied",
            "slurred",
            "tuplet",
            "fermata",
            "articulations",
            "ornaments",
        ]
        missing_cols = [c for c in att_cols if c not in df_pitch.columns]
        if missing_cols:
            overall_issues.append(
                f"{label}: df_pitch missing note-attachment columns {missing_cols}"
            )
            print(f"    [FAIL] missing columns: {missing_cols}")
            continue

        for col in att_cols:
            col_series = df_pitch[col]
            try:
                non_null = int(col_series.notna().sum())
            except Exception:
                non_null = 0
            expected = source_flags.get(col, False)
            status = (
                "OK"
                if (non_null > 0) or (not expected)
                else "WARN"
            )
            print(f"    {col:<16}non_null={non_null:<6} expected={expected}  {status}")
            if expected and non_null == 0:
                overall_issues.append(
                    f"{label}: df_pitch.{col} expected non-null rows but got 0"
                )

    print("\n=== Summary ===")
    if overall_issues:
        print("FAIL: coverage issues detected:")
        for issue in overall_issues:
            print("  -", issue)
        return 1
    print("PASS: every music-relevant MEI element was captured in df_events/df_pitch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
