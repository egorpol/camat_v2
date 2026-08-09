"""Run isolated structural checks on CAMAT's Verovio parser.

Unlike ``compare_verovio_partitura.py``, this runner does not require a
Partitura result. Each source is parsed in a fresh subprocess so malformed MEI
or a native Verovio crash cannot terminate the rest of the batch.

Examples
--------
Test every locally converted MEI::

    conda run -n py311 python scripts/test_verovio_parser_robustness.py

Test explicit files or a newline-separated source list::

    conda run -n py311 python scripts/test_verovio_parser_robustness.py \
        --source score.mei --source test_corpus/mei_test_copora_links.txt
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/camat-matplotlib")

from camat.parser_registry import parse_files  # noqa: E402
from camat.parser_utils import expand_file_sources  # noqa: E402
from camat.partitura_backend import _mei_local_name, _mei_music_measures  # noqa: E402


DEFAULT_GLOB = "converted_mei/verovio_conversion_tests/*.mei"
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


def _source_stats(path: Path) -> Dict[str, int]:
    root = ET.parse(path).getroot()
    measures = _mei_music_measures(root)
    note_count = sum(
        1
        for measure in measures
        for element in measure.iter()
        if _mei_local_name(element.tag) == "note"
    )
    return {"source_measures": len(measures), "source_notes": note_count}


def _finite_problem_count(series: pd.Series) -> int:
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    return int((~np.isfinite(numeric)).sum())


def _validate_pitch_dataframe(df: pd.DataFrame, source_notes: int) -> List[str]:
    issues: List[str] = []
    missing_columns = sorted(REQUIRED_PITCH_COLUMNS - set(df.columns))
    if missing_columns:
        issues.append(f"missing pitch columns: {missing_columns}")
        return issues
    if source_notes > 0 and df.empty:
        issues.append("source contains notes but df_pitch is empty")
        return issues
    if source_notes > 0 and len(df) != source_notes:
        issues.append(
            f"source contains {source_notes} notes but df_pitch contains {len(df)} rows"
        )

    for column in ("Measure", "Local Onset", "Global Onset", "Duration", "MIDI"):
        count = _finite_problem_count(df[column])
        if count:
            issues.append(f"{column} contains {count} non-finite value(s)")
    if not df.empty:
        duration = pd.to_numeric(df["Duration"], errors="coerce")
        nonpositive = int((duration <= 0).sum())
        if nonpositive:
            issues.append(f"Duration contains {nonpositive} non-positive value(s)")
        midi = pd.to_numeric(df["MIDI"], errors="coerce")
        out_of_range = int(((midi < 0) | (midi > 127)).sum())
        if out_of_range:
            issues.append(f"MIDI contains {out_of_range} out-of-range value(s)")
        onsets = pd.to_numeric(df["Global Onset"], errors="coerce")
        if not onsets.is_monotonic_increasing:
            issues.append("Global Onset is not monotonically increasing")
    return issues


def _parse_one(source: str, *, probe_partitura: bool = False) -> Dict[str, Any]:
    source_path = Path(source)
    source_stats = _source_stats(source_path) if source_path.exists() else {}
    results, _, _ = parse_files(
        [source],
        parsing_backend="verovio",
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
        collapse_tied_pitch_events=False,
        align_accident_schema=True,
        include_xml_ids=True,
        use_remote_cache=True,
        show_progress=False,
    )
    if len(results) != 1:
        raise RuntimeError(f"Verovio returned {len(results)} results for one source")
    entry = results[0]
    pitch = entry["df_pitch"]
    events = entry["df_events"]
    issues = _validate_pitch_dataframe(pitch, int(source_stats.get("source_notes", 0)))
    offsets = [float(value) for value in entry.get("measure_offsets", [])]
    if any(not np.isfinite(value) for value in offsets):
        issues.append("measure_offsets contains non-finite values")
    if any(right <= left for left, right in zip(offsets, offsets[1:])):
        issues.append("measure_offsets is not strictly increasing")
    source_measures = int(source_stats.get("source_measures", 0))
    if source_measures > 0 and len(offsets) != source_measures:
        issues.append(
            f"source contains {source_measures} measures but parser returned "
            f"{len(offsets)} measure offsets"
        )

    record: Dict[str, Any] = {
        "source": source,
        "status": "ok" if not issues else "invalid",
        **source_stats,
        "pitch_rows": int(len(pitch)),
        "event_rows": int(len(events)),
        "measure_offsets": int(len(offsets)),
        "idless_pitch_rows": int(pitch["xml_id"].isna().sum()) if "xml_id" in pitch else None,
        "voices": int(pitch["Voice"].nunique(dropna=True)) if "Voice" in pitch else None,
        "issues": issues,
    }
    if probe_partitura:
        try:
            partitura_results, _, _ = parse_files(
                [source],
                parsing_backend="partitura",
                quiet_native_warnings=True,
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
                include_xml_ids=True,
                use_remote_cache=True,
                show_progress=False,
                n_jobs=1,
                normalize_mensural_durations=False,
                inject_missing_meter_signature=False,
                try_verovio_mei_conversion=False,
                prefer_verovio_for_mensural=False,
                use_verovio_mensural_timing=False,
                allow_music21_fallback=False,
            )
            record["partitura_status"] = "ok" if len(partitura_results) == 1 else "failed"
            record["partitura_pitch_rows"] = (
                int(len(partitura_results[0]["df_pitch"])) if partitura_results else None
            )
        except Exception as exc:
            record["partitura_status"] = "error"
            record["partitura_error"] = f"{type(exc).__name__}: {exc}"
    return record


def _worker(source: str, report_path: Path, *, probe_partitura: bool = False) -> int:
    try:
        record = _parse_one(source, probe_partitura=probe_partitura)
    except Exception as exc:
        record = {
            "source": source,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "issues": [],
        }
    report_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return 0 if record["status"] == "ok" else 1


def _resolve_sources(raw_sources: Sequence[str]) -> List[str]:
    if raw_sources:
        return expand_file_sources(raw_sources, base_dir=REPO_ROOT, verbose=False)
    return [str(path.resolve()) for path in sorted(REPO_ROOT.glob(DEFAULT_GLOB))]


def _run_isolated(
    sources: Sequence[str],
    timeout: int,
    *,
    probe_partitura: bool = False,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="camat-verovio-robustness-") as temp_dir:
        for index, source in enumerate(sources, start=1):
            report_path = Path(temp_dir) / f"source-{index:03d}.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                source,
                "--worker-report",
                str(report_path),
            ]
            if probe_partitura:
                command.append("--probe-partitura")
            try:
                completed = subprocess.run(command, check=False, timeout=timeout)
                if report_path.exists():
                    record = json.loads(report_path.read_text(encoding="utf-8"))
                else:
                    record = {
                        "source": source,
                        "status": "crash",
                        "returncode": completed.returncode,
                        "issues": [],
                    }
            except subprocess.TimeoutExpired:
                record = {
                    "source": source,
                    "status": "timeout",
                    "timeout_seconds": timeout,
                    "issues": [],
                }
            records.append(record)
    return records


def _print_summary(records: Sequence[Dict[str, Any]]) -> None:
    print("\n=== Verovio parser robustness ===\n")
    print(
        f"{'status':<8} {'part':<7} {'notes':>7} {'rows':>7} "
        f"{'events':>7} {'meas':>6}  source"
    )
    print("-" * 88)
    for record in records:
        print(
            f"{record.get('status', ''):<8} "
            f"{record.get('partitura_status', '-'):<7} "
            f"{str(record.get('source_notes', '')):>7} "
            f"{str(record.get('pitch_rows', '')):>7} "
            f"{str(record.get('event_rows', '')):>7} "
            f"{str(record.get('measure_offsets', '')):>6}  "
            f"{record.get('source', '')}"
        )
        for issue in record.get("issues", []):
            print(f"         issue: {issue}")
        if record.get("error"):
            print(f"         error: {record['error']}")
        if record.get("returncode") is not None:
            print(f"         returncode: {record['returncode']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="File, URL, or .txt source list.")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds allowed per source.")
    parser.add_argument(
        "--probe-partitura",
        action="store_true",
        help="Also report whether raw Partitura loading succeeds; never affects Verovio status.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("converted_mei/verovio_conversion_tests/parser_robustness_report.json"),
        help="Output JSON report path.",
    )
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--worker-report", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.worker:
        if args.worker_report is None:
            raise SystemExit("--worker-report is required with --worker")
        return _worker(
            args.worker,
            args.worker_report,
            probe_partitura=args.probe_partitura,
        )

    sources = _resolve_sources(args.source or [])
    records = _run_isolated(
        sources,
        args.timeout,
        probe_partitura=args.probe_partitura,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(records, indent=2), encoding="utf-8")
    _print_summary(records)
    print(f"\nReport: {args.json.resolve()}")
    return 0 if all(record.get("status") == "ok" for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
