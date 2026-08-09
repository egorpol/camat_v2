"""Diagnose CAMAT Verovio parser parity against Partitura.

This is the command-line counterpart to ``verovio_partitura_parsing.ipynb``.
It parses each source once per backend, joins pitch rows by MEI ``xml:id``, and
groups differences by field so that parser work can be driven by concrete
mismatch classes instead of manually scanning two dataframes.

Examples
--------
Run the four fast regression sources::

    conda run -n py311 python scripts/compare_verovio_partitura.py

Run every source listed in the notebook and show example mismatch rows::

    conda run -n py311 python scripts/compare_verovio_partitura.py \
        --suite notebook --details 3

Inspect a local or remote MEI file with strict field comparison::

    conda run -n py311 python scripts/compare_verovio_partitura.py \
        --source score.mei --mode strict --details 10
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/camat-matplotlib")

from camat.parser_registry import parse_files  # noqa: E402
from camat.parser_utils import expand_file_sources  # noqa: E402


SMOKE_SOURCES = [
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.0/Music/Complete_examples/Bach-JS_Ein_feste_Burg.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_3.0/Music/Complete_examples/Mozart_Fuge_G_minor.mei",
    "https://raw.githubusercontent.com/trompamusic-encodings/Beethoven_Op31_No3_HenleUrtext/refs/heads/master/Beethoven_Op31_No3_3-HenleUrtext.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Bach-JS_BrandenburgConcert_No4_I_BWV1049.mei",
]

NOTEBOOK_SOURCES = SMOKE_SOURCES + [
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Beethoven_StringQuartet_Op18_No1.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Brahms_StringQuartet_Op51_No1.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Chopin_Etude_Op10_No9.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Chopin_Mazurka_Op6_No1.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Haydn_StringQuartet_Op1_No1.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Joplin_Maple_leaf_Rag.mei",
    "https://raw.githubusercontent.com/music-encoding/sample-encodings/main/MEI_5.1/Music/Complete_examples/Schumann_Song_Op48_No1.mei",
]

PITCH_COLUMNS = [
    "MIDI",
    "Global Onset",
    "Local Onset",
    "Duration",
    "Pitch",
    "Pitch Enharmonic",
    "Voice",
    "Measure",
]
NUMERIC_COLUMNS = {"MIDI", "Global Onset", "Local Onset", "Duration", "Measure"}
COMPARE_MODES: Mapping[str, Sequence[str]] = {
    "core": ("MIDI", "Global Onset", "Duration", "Pitch"),
    "timing": ("Global Onset", "Duration"),
    "location": ("Measure", "Local Onset"),
    "spelling": ("Pitch Enharmonic",),
    "voices": ("Voice",),
    "strict": tuple(PITCH_COLUMNS),
}


@dataclass(frozen=True)
class ComparisonSummary:
    source: str
    mode: str
    partitura_rows: int
    verovio_rows: int
    matches: int
    value_mismatches: int
    missing_in_verovio: int
    extra_in_verovio: int
    duplicate_partitura_ids: int
    duplicate_verovio_ids: int


def _normalise_id_column(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "xml_id" not in out.columns:
        out["xml_id"] = pd.NA
    out["xml_id"] = out["xml_id"].astype("string")
    return out


def _values_differ(left: Any, right: Any, *, numeric: bool, tolerance: float) -> bool:
    if pd.isna(left) and pd.isna(right):
        return False
    if numeric:
        left_num = pd.to_numeric(pd.Series([left]), errors="coerce").iloc[0]
        right_num = pd.to_numeric(pd.Series([right]), errors="coerce").iloc[0]
        if pd.isna(left_num) or pd.isna(right_num):
            return bool(pd.isna(left_num) != pd.isna(right_num))
        return abs(float(left_num) - float(right_num)) > tolerance
    if pd.isna(left) or pd.isna(right):
        return True
    return str(left) != str(right)


def compare_pitch_dataframes(
    partitura_df: pd.DataFrame,
    verovio_df: pd.DataFrame,
    *,
    columns: Sequence[str],
    tolerance: float = 1e-6,
) -> pd.DataFrame:
    """Outer-join pitch rows by ``xml_id`` and label field-level differences."""
    part = _normalise_id_column(partitura_df)
    vrv = _normalise_id_column(verovio_df)
    keep = ["xml_id", *[col for col in PITCH_COLUMNS if col in part.columns or col in vrv.columns]]
    for frame in (part, vrv):
        for col in keep:
            if col not in frame.columns:
                frame[col] = pd.NA

    # Occurrence makes diagnostics deterministic even for malformed or generated
    # sources that repeat an xml:id. Duplicate counts remain visible in summary.
    for frame in (part, vrv):
        frame["_occurrence"] = frame.groupby("xml_id", dropna=False).cumcount()
    merged = part[keep + ["_occurrence"]].merge(
        vrv[keep + ["_occurrence"]],
        on=["xml_id", "_occurrence"],
        how="outer",
        suffixes=("_partitura", "_verovio"),
        indicator=True,
    )

    statuses: List[str] = []
    mismatch_fields: List[str] = []
    for _, row in merged.iterrows():
        if row["_merge"] == "left_only":
            statuses.append("missing_in_verovio")
            mismatch_fields.append("xml_id")
            continue
        if row["_merge"] == "right_only":
            statuses.append("extra_in_verovio")
            mismatch_fields.append("xml_id")
            continue
        differences = [
            col
            for col in columns
            if _values_differ(
                row.get(f"{col}_partitura", pd.NA),
                row.get(f"{col}_verovio", pd.NA),
                numeric=col in NUMERIC_COLUMNS,
                tolerance=tolerance,
            )
        ]
        statuses.append("match" if not differences else "value_mismatch")
        mismatch_fields.append(", ".join(differences))

    merged["status"] = statuses
    merged["mismatch_fields"] = mismatch_fields
    order = {"missing_in_verovio": 0, "extra_in_verovio": 1, "value_mismatch": 2, "match": 3}
    merged["_status_order"] = merged["status"].map(order)
    onset_cols = [col for col in ("Global Onset_partitura", "Global Onset_verovio") if col in merged]
    return (
        merged.sort_values(["_status_order", *onset_cols, "xml_id"], na_position="last", kind="stable")
        .drop(columns=["_status_order"])
        .reset_index(drop=True)
    )


def summarise_comparison(
    source: str,
    mode: str,
    partitura_df: pd.DataFrame,
    verovio_df: pd.DataFrame,
    comparison: pd.DataFrame,
) -> ComparisonSummary:
    counts = comparison["status"].value_counts().to_dict()
    part_ids = _normalise_id_column(partitura_df)["xml_id"]
    vrv_ids = _normalise_id_column(verovio_df)["xml_id"]
    return ComparisonSummary(
        source=source,
        mode=mode,
        partitura_rows=len(partitura_df),
        verovio_rows=len(verovio_df),
        matches=int(counts.get("match", 0)),
        value_mismatches=int(counts.get("value_mismatch", 0)),
        missing_in_verovio=int(counts.get("missing_in_verovio", 0)),
        extra_in_verovio=int(counts.get("extra_in_verovio", 0)),
        # Multiple source notes may legitimately have no xml:id. Missing ids
        # are paired by occurrence for diagnostics but are not duplicate IDs.
        duplicate_partitura_ids=int(part_ids.dropna().duplicated().sum()),
        duplicate_verovio_ids=int(vrv_ids.dropna().duplicated().sum()),
    )


def _parse_sources(sources: Sequence[str], backend: str, *, use_cache: bool) -> List[Dict[str, Any]]:
    results, _, _ = parse_files(
        list(sources),
        parsing_backend=backend,
        quiet_native_warnings=True,
        dedupe_weaker_text_events=False,
        print_parsed_summary=False,
        filter_zero_duration=True,
        adjust_fractional_duration=True,
        parse_enharmonic=True,
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        cleanup_remote=False,
        return_plots=False,
        collapse_tied_pitch_events=False,
        align_accident_schema=True,
        include_xml_ids=True,
        allow_music21_fallback=False,
        use_remote_cache=use_cache,
        n_jobs=1,
        normalize_mensural_durations=False,
        inject_missing_meter_signature=False,
        prefer_verovio_for_mensural=False,
        use_verovio_mensural_timing=False,
        show_progress=False,
    )
    if len(results) != len(sources):
        raise RuntimeError(
            f"{backend} parsed {len(results)} of {len(sources)} source(s); "
            "see the parser diagnostics above for the rejected source."
        )
    return results


def _profile_text(comparison: pd.DataFrame) -> str:
    mismatches = comparison[comparison["status"] != "match"]
    if mismatches.empty:
        return "none"
    counts = mismatches["mismatch_fields"].value_counts()
    return "; ".join(f"{name}={int(count)}" for name, count in counts.items())


def _detail_columns(comparison: pd.DataFrame) -> List[str]:
    preferred = [
        "xml_id",
        "status",
        "mismatch_fields",
        "Measure_partitura",
        "Measure_verovio",
        "Global Onset_partitura",
        "Global Onset_verovio",
        "Duration_partitura",
        "Duration_verovio",
        "MIDI_partitura",
        "MIDI_verovio",
        "Pitch Enharmonic_partitura",
        "Pitch Enharmonic_verovio",
        "Voice_partitura",
        "Voice_verovio",
    ]
    return [col for col in preferred if col in comparison.columns]


def _resolve_sources(args: argparse.Namespace) -> List[str]:
    raw_sources = (
        list(args.source)
        if args.source
        else list(NOTEBOOK_SOURCES if args.suite == "notebook" else SMOKE_SOURCES)
    )
    return expand_file_sources(raw_sources, base_dir=REPO_ROOT, verbose=False)


def _resolve_modes(raw_modes: Iterable[str]) -> List[str]:
    modes: List[str] = []
    for raw in raw_modes:
        for mode in raw.split(","):
            mode = mode.strip().lower()
            if mode and mode not in modes:
                modes.append(mode)
    unknown = sorted(set(modes) - set(COMPARE_MODES))
    if unknown:
        raise ValueError(f"Unknown comparison mode(s): {', '.join(unknown)}")
    return modes or ["core", "strict"]


def _should_fail(summaries: Sequence[ComparisonSummary], fail_on: str) -> bool:
    if fail_on == "none":
        return False
    relevant = summaries
    if fail_on in COMPARE_MODES:
        relevant = [summary for summary in summaries if summary.mode == fail_on]
    for summary in relevant:
        if summary.missing_in_verovio or summary.extra_in_verovio:
            return True
        if fail_on != "structural" and summary.value_mismatches:
            return True
        if summary.duplicate_partitura_ids or summary.duplicate_verovio_ids:
            return True
    return False


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("smoke", "notebook"), default="smoke")
    parser.add_argument(
        "--source",
        action="append",
        help="Local path or URL; repeat to compare several sources (overrides --suite).",
    )
    parser.add_argument(
        "--mode",
        action="append",
        default=[],
        help="Comparison mode, repeatable or comma-separated (default: core,strict).",
    )
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument("--details", type=int, default=0, help="Example mismatch rows per source/mode.")
    parser.add_argument("--no-cache", action="store_true", help="Disable CAMAT's remote download cache.")
    parser.add_argument(
        "--fail-on",
        choices=("none", "structural", *COMPARE_MODES.keys()),
        default="none",
        help="Return exit status 1 for this class of mismatch.",
    )
    parser.add_argument("--json", type=Path, dest="json_path", help="Write machine-readable summary JSON.")
    parser.add_argument(
        "--no-isolation",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def _compare_sources(
    args: argparse.Namespace,
    sources: Sequence[str],
    modes: Sequence[str],
) -> Tuple[List[ComparisonSummary], Dict[str, Dict[str, List[Dict[str, Any]]]]]:
    print(f"Parsing {len(sources)} source(s) with Partitura...")
    partitura_results = _parse_sources(sources, "partitura", use_cache=not args.no_cache)
    print(f"Parsing {len(sources)} source(s) with Verovio...")
    verovio_results = _parse_sources(sources, "verovio", use_cache=not args.no_cache)

    summaries: List[ComparisonSummary] = []
    json_details: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    print("\n=== Verovio / Partitura pitch parity ===")
    for source, part_entry, vrv_entry in zip(sources, partitura_results, verovio_results):
        name = str(part_entry["name"])
        part_df = part_entry["df_pitch"]
        vrv_df = vrv_entry["df_pitch"]
        print(f"\n{name}: partitura={len(part_df)} verovio={len(vrv_df)}")
        json_details[name] = {}
        for mode in modes:
            comparison = compare_pitch_dataframes(
                part_df,
                vrv_df,
                columns=COMPARE_MODES[mode],
                tolerance=args.tolerance,
            )
            summary = summarise_comparison(source, mode, part_df, vrv_df, comparison)
            summaries.append(summary)
            print(
                f"  {mode:8s} matches={summary.matches} values={summary.value_mismatches} "
                f"missing={summary.missing_in_verovio} extra={summary.extra_in_verovio} "
                f"profile=[{_profile_text(comparison)}]"
            )
            mismatch_rows = comparison[comparison["status"] != "match"]
            if args.details > 0 and not mismatch_rows.empty:
                print(
                    mismatch_rows[_detail_columns(comparison)]
                    .head(args.details)
                    .to_string(index=False)
                )
            json_details[name][mode] = (
                mismatch_rows[_detail_columns(comparison)]
                .head(max(0, args.details))
                .replace({np.nan: None, pd.NA: None})
                .to_dict(orient="records")
                if args.details > 0
                else []
            )

    return summaries, json_details


def _write_json_report(
    path: Path,
    *,
    sources: Sequence[str],
    modes: Sequence[str],
    tolerance: float,
    summaries: Sequence[ComparisonSummary],
    details: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]],
    failures: Sequence[Mapping[str, Any]] = (),
) -> None:
    payload = {
        "sources": list(sources),
        "modes": list(modes),
        "tolerance": tolerance,
        "summaries": [asdict(summary) for summary in summaries],
        "details": details,
        "failures": list(failures),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {path}")


def _compare_sources_isolated(
    args: argparse.Namespace,
    sources: Sequence[str],
    modes: Sequence[str],
) -> Tuple[
    List[ComparisonSummary],
    Dict[str, Dict[str, List[Dict[str, Any]]]],
    List[Dict[str, Any]],
]:
    """Run each source in a fresh interpreter to contain Verovio native crashes."""
    summaries: List[ComparisonSummary] = []
    details: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    failures: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="camat-parity-") as tmp_dir:
        for index, source in enumerate(sources, start=1):
            report_path = Path(tmp_dir) / f"source-{index:02d}.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--source",
                source,
                "--mode",
                ",".join(modes),
                "--tolerance",
                str(args.tolerance),
                "--details",
                str(args.details),
                "--fail-on",
                "none",
                "--json",
                str(report_path),
                "--no-isolation",
            ]
            if args.no_cache:
                command.append("--no-cache")
            print(f"\n##### Isolated source {index}/{len(sources)} #####", flush=True)
            completed = subprocess.run(command, check=False)
            if completed.returncode != 0 or not report_path.exists():
                failure = {
                    "source": source,
                    "returncode": int(completed.returncode),
                    "reason": "worker crashed" if completed.returncode < 0 else "worker failed",
                }
                failures.append(failure)
                print(
                    f"FAILED source {index}: returncode={completed.returncode} {source}",
                    file=sys.stderr,
                )
                continue
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            summaries.extend(ComparisonSummary(**item) for item in payload.get("summaries", []))
            details.update(payload.get("details", {}))
    return summaries, details, failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        modes = _resolve_modes(args.mode)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    sources = _resolve_sources(args)

    if len(sources) > 1 and not args.no_isolation:
        summaries, json_details, failures = _compare_sources_isolated(args, sources, modes)
    else:
        summaries, json_details = _compare_sources(args, sources, modes)
        failures = []

    if args.json_path:
        _write_json_report(
            args.json_path,
            sources=sources,
            modes=modes,
            tolerance=args.tolerance,
            summaries=summaries,
            details=json_details,
            failures=failures,
        )

    return 1 if failures or _should_fail(summaries, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
