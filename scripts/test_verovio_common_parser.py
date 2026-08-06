"""Compare the experimental Verovio common-notation backend to Partitura.

This is a parity harness, not a claim that the Verovio backend is already a
drop-in replacement. It fails on structural regressions and missing Partitura
pitch ids, while reporting the remaining value-level deltas that should drive
future backend work.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Set

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from camat.parser_registry import parse_files  # noqa: E402


FILE_SOURCES: List[str] = [
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.0/Music/Complete_examples/Bach-JS_Ein_feste_Burg.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_3.0/Music/Complete_examples/Mozart_Fuge_G_minor.mei",
    "https://raw.githubusercontent.com/trompamusic-encodings/Beethoven_Op31_No3_HenleUrtext/refs/heads/master/Beethoven_Op31_No3_3-HenleUrtext.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Bach-JS_BrandenburgConcert_No4_I_BWV1049.mei",
]

REQUIRED_PITCH_COLUMNS = {
    "Measure",
    "Local Onset",
    "Global Onset",
    "Duration",
    "Pitch",
    "MIDI",
    "Voice",
    "xml_id",
}
ATTACHMENT_COLUMNS = {
    "grace",
    "tied",
    "slurred",
    "tuplet",
    "fermata",
    "articulations",
    "ornaments",
    "technical",
}

# Reserved for source rows that Verovio's direct MEI walk sees and Partitura
# intentionally omits/collapses. Missing Partitura ids are hard failures.
KNOWN_EXTRA_IDS: Dict[str, Set[str]] = {}


def _parse(backend: str):
    kwargs = dict(
        parsing_backend=backend,
        quiet_native_warnings=True,
        dedupe_weaker_text_events=True,
        print_parsed_summary=False,
        filter_zero_duration=True,
        adjust_fractional_duration=True,
        parse_enharmonic=True,
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        cleanup_remote=False,
        return_plots=False,
        use_remote_cache=True,
        show_progress=False,
    )
    if backend == "partitura":
        kwargs.update(
            n_jobs=1,
            normalize_mensural_durations=False,
            inject_missing_meter_signature=False,
            prefer_verovio_for_mensural=False,
            use_verovio_mensural_timing=False,
            allow_music21_fallback=False,
        )
    return parse_files(FILE_SOURCES, **kwargs)


def main() -> int:
    partitura_results, partitura_dfs, _ = _parse("partitura")
    verovio_results, verovio_dfs, _ = _parse("verovio")

    issues: List[str] = []
    print("\n=== Verovio Common Parser Parity Report ===\n")

    for p_entry, v_entry in zip(partitura_results, verovio_results):
        name = str(p_entry["name"])
        p_pitch = p_entry["df_pitch"]
        v_pitch = v_entry["df_pitch"]
        p_events = p_entry["df_events"]
        v_events = v_entry["df_events"]

        print(f"--- {name} ---")
        print(f"pitch rows: partitura={len(p_pitch)} verovio={len(v_pitch)}")
        print(f"event rows: partitura={len(p_events)} verovio={len(v_events)}")

        for key in (f"{name}_pitch", f"{name}_events"):
            if key not in partitura_dfs:
                issues.append(f"{name}: missing Partitura dfs_by_name key {key}")
            if key not in verovio_dfs:
                issues.append(f"{name}: missing Verovio dfs_by_name key {key}")

        if p_pitch.empty:
            issues.append(f"{name}: Partitura df_pitch is empty")
        if v_pitch.empty:
            issues.append(f"{name}: Verovio df_pitch is empty")

        missing_cols = sorted((REQUIRED_PITCH_COLUMNS | ATTACHMENT_COLUMNS) - set(v_pitch.columns))
        if missing_cols:
            issues.append(f"{name}: Verovio df_pitch missing columns {missing_cols}")

        p_ids = set(p_pitch["xml_id"].dropna().astype(str))
        v_ids = set(v_pitch["xml_id"].dropna().astype(str))
        missing_ids = sorted(p_ids - v_ids)
        extra_ids = sorted(v_ids - p_ids)
        unexpected_extra = sorted(set(extra_ids) - KNOWN_EXTRA_IDS.get(name, set()))
        print(f"xml ids: partitura={len(p_ids)} verovio={len(v_ids)} missing={len(missing_ids)} extra={len(extra_ids)}")
        if missing_ids:
            issues.append(f"{name}: Verovio missing Partitura xml_id(s): {missing_ids[:20]}")
        if unexpected_extra:
            issues.append(f"{name}: Verovio has unexpected extra xml_id(s): {unexpected_extra[:20]}")
        if extra_ids:
            print(f"known/extra ids: {extra_ids[:20]}")

        p_event_types = set(p_events["type"].dropna().astype(str))
        v_event_types = set(v_events["type"].dropna().astype(str))
        missing_event_types = sorted(p_event_types - v_event_types)
        if missing_event_types:
            issues.append(f"{name}: Verovio missing event type(s): {missing_event_types}")

        common_ids = sorted(p_ids & v_ids)
        p_by_id = p_pitch.drop_duplicates("xml_id").set_index("xml_id")
        v_by_id = v_pitch.drop_duplicates("xml_id").set_index("xml_id")
        value_deltas = 0
        for xml_id in common_ids:
            p_row = p_by_id.loc[xml_id]
            v_row = v_by_id.loc[xml_id]
            try:
                onset_delta = abs(float(p_row["Global Onset"]) - float(v_row["Global Onset"]))
                dur_delta = abs(float(p_row["Duration"]) - float(v_row["Duration"]))
                midi_delta = int(p_row["MIDI"]) != int(v_row["MIDI"])
            except Exception:
                value_deltas += 1
                continue
            if onset_delta > 1e-6 or dur_delta > 1e-6 or midi_delta:
                value_deltas += 1
        print(f"value deltas among common ids: {value_deltas}")

    if issues:
        print("\nFAIL:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("\nOK: Verovio backend passes structural common-notation parity checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
