from __future__ import annotations

import bisect
import math
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence

import pandas as pd

__all__ = [
    "expand_file_sources",
    "format_parsed_summary",
    "print_parsed_summary",
    "reanchor_to_measure_offsets",
    "reject_unexpected_kwargs",
    "resolve_collapse_tied_pitch_events",
]


def reject_unexpected_kwargs(kwargs: Mapping[str, Any], function_name: str) -> None:
    """Raise a Python-style error for unsupported compatibility kwargs."""
    if not kwargs:
        return
    names = sorted(str(name) for name in kwargs)
    if len(names) == 1:
        raise TypeError(f"{function_name}() got an unexpected keyword argument {names[0]!r}")
    joined = ", ".join(repr(name) for name in names)
    raise TypeError(f"{function_name}() got unexpected keyword arguments: {joined}")


def resolve_collapse_tied_pitch_events(
    collapse_tied_pitch_events: Optional[bool],
    legacy_kwargs: Optional[dict[str, Any]] = None,
    *,
    default: bool = True,
) -> bool:
    """
    Resolve the explicit tied-pitch-row option and the deprecated strip_ties alias.

    Historically, ``strip_ties`` meant "collapse tied pitch rows" rather than
    "remove every tie annotation". The new name keeps that scope visible.
    """
    if legacy_kwargs is not None and "strip_ties" in legacy_kwargs:
        legacy_value = legacy_kwargs.pop("strip_ties")
        if collapse_tied_pitch_events is not None and bool(collapse_tied_pitch_events) != bool(legacy_value):
            raise ValueError(
                "Received both collapse_tied_pitch_events and deprecated strip_ties "
                "with conflicting values."
            )
        collapse_tied_pitch_events = bool(legacy_value)

    if collapse_tied_pitch_events is None:
        return bool(default)
    return bool(collapse_tied_pitch_events)


def expand_file_sources(
    sources: Iterable[str],
    *,
    base_dir: str | Path | None = None,
    verbose: bool = True,
    logger: Optional[Callable[[str], None]] = None,
) -> List[str]:
    """
    Expand a collection of file sources by loading any `.txt` entries.

    Rules
    -----
    - Entries ending with ``.txt`` (that are not URLs) are treated as files
      containing newline-separated sources.
    - Comment lines (starting with ``#``) and empty lines are ignored.
    - Relative paths are resolved against ``base_dir`` or the current working
      directory when ``base_dir`` is omitted.
    - All other entries are returned unchanged.

    Parameters
    ----------
    sources : Iterable[str]
        URLs or local paths to parse.
    base_dir : str | Path, optional
        Base directory for resolving relative `.txt` paths. Defaults to
        ``Path.cwd()`` when omitted.
    verbose : bool
        If True (default), log expansion progress and warnings.
    logger : callable, optional
        Custom logging function accepting a single string. Defaults to ``print``.

    Returns
    -------
    list[str]
        Flat list of expanded sources.
    """
    expanded: List[str] = []
    root = Path(base_dir).resolve() if base_dir is not None else Path.cwd()
    log = logger or print

    for raw_source in sources:
        source = str(raw_source).strip()
        if not source:
            continue

        is_txt = source.lower().endswith(".txt") and not source.startswith(
            ("http://", "https://")
        )
        if is_txt:
            txt_path = Path(source)
            if not txt_path.is_absolute():
                txt_path = root / txt_path
            txt_path = txt_path.resolve()

            if txt_path.exists():
                before = len(expanded)
                if verbose:
                    log(f"Expanding sources from: {txt_path}")
                with open(txt_path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            expanded.append(line)
                if verbose:
                    added = len(expanded) - before
                    log(f"  Added {added} source(s)")
            else:
                if verbose:
                    log(f"Warning: txt file not found: {txt_path}")
        else:
            expanded.append(source)

    return expanded


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def _regular_span_from_offsets(offsets: Sequence[float]) -> Optional[float]:
    spans = [
        round(float(b) - float(a), 9)
        for a, b in zip(offsets, offsets[1:])
        if math.isfinite(float(a)) and math.isfinite(float(b)) and float(b) > float(a)
    ]
    if not spans:
        return None
    counts: dict[float, int] = {}
    for span in spans:
        counts[span] = counts.get(span, 0) + 1
    return max(counts, key=lambda span: (counts[span], span))


def reanchor_to_measure_offsets(
    df: pd.DataFrame,
    measure_offsets: Sequence[Any],
    *,
    onset_col: str = "Global Onset",
    measure_col: str = "Measure",
    local_onset_col: str = "Local Onset",
    regular_span: Optional[float] = None,
    right_align_initial_pickup: bool = True,
    eps: float = 1e-9,
) -> pd.DataFrame:
    """
    Recompute measure number and local onset from a shared measure-offset grid.

    CAMAT treats ``measure_offsets`` as the authoritative encoded timeline for
    notebook analysis. This avoids leaking backend-specific measure labels into
    ``df_pitch`` when a source has pickup or repeated MEI measure numbers.
    Source labels such as MEI ``@n`` remain available in event metadata.
    """
    if not isinstance(df, pd.DataFrame) or df.empty or onset_col not in df.columns:
        return df

    offsets = sorted({
        round(number, 9)
        for value in measure_offsets
        for number in [_finite_float(value)]
        if number is not None
    })
    if not offsets:
        return df

    regular = _finite_float(regular_span)
    if regular is None or regular <= 0:
        regular = _regular_span_from_offsets(offsets)

    first_span: Optional[float] = None
    if len(offsets) > 1:
        first_span = offsets[1] - offsets[0]
    pickup_local_shift = 0.0
    if (
        right_align_initial_pickup
        and regular is not None
        and regular > 0
        and first_span is not None
        and first_span > 0
        and first_span < regular - eps
        and offsets[0] < 0
    ):
        pickup_local_shift = float(regular - first_span)

    out = df.copy()
    measures: list[Any] = []
    locals_: list[float] = []
    for raw_onset in out[onset_col].tolist():
        onset = _finite_float(raw_onset)
        if onset is None:
            measures.append(pd.NA)
            locals_.append(float("nan"))
            continue
        idx = bisect.bisect_right(offsets, onset + eps) - 1
        if idx < 0:
            idx = 0
        if idx >= len(offsets):
            idx = len(offsets) - 1
        local = float(onset - offsets[idx])
        if idx == 0 and pickup_local_shift:
            local += pickup_local_shift
        measures.append(idx + 1)
        locals_.append(local)

    out[measure_col] = pd.Series(measures, index=out.index, dtype="Int64")
    out[local_onset_col] = locals_
    return out


def format_parsed_summary(
    results: Iterable[Mapping[str, Any]],
    *,
    include_voice_names: bool = True,
    header: str = "Parsed DataFrames:",
) -> List[str]:
    """
    Build a human-readable summary of parsed results.

    Each result mapping should contain at least ``name`` and ``df`` keys where
    ``df`` is a pandas DataFrame. The summary reports row count, number of
    unique MIDI pitches, minimum positive duration, and optional voice details.

    Parameters
    ----------
    results : Iterable[Mapping[str, Any]]
        Collection of result dictionaries (e.g., from parser_registry.parse_files).
    include_voice_names : bool
        If True, list distinct voice names alongside the voice count.
    header : str
        Header line for the summary output.

    Returns
    -------
    list[str]
        Lines of text ready for printing.
    """
    lines: List[str] = []

    for item in results:
        name = str(item.get("name", "") or "<unnamed>")
        df = item.get("df")

        if df is None:
            lines.append(f"- {name}: no DataFrame attached")
            continue
        if not isinstance(df, pd.DataFrame):
            lines.append(f"- {name}: unsupported df type {type(df).__name__}")
            continue

        pos_dur = df.loc[df["Duration"] > 0, "Duration"] if "Duration" in df.columns else None
        min_dur = None
        if pos_dur is not None and len(pos_dur) > 0:
            try:
                min_dur = float(pos_dur.min())
            except Exception:
                min_dur = None
        min_dur_str = str(min_dur) if min_dur is not None else "n/a"

        unique_pitches = df["MIDI"].nunique() if "MIDI" in df.columns else 0
        voice_count: Optional[int] = None
        voice_names: Sequence[str] | tuple[Any, ...] = ()

        if "Voice" in df.columns:
            try:
                voice_count = int(df["Voice"].nunique())
            except Exception:
                voice_count = None

            if include_voice_names:
                try:
                    voice_names = tuple(sorted([v for v in df["Voice"].dropna().unique().tolist()]))
                except Exception:
                    voice_names = ()

        line = f"- {name}: rows={len(df)}, unique_pitches={unique_pitches}, min_duration={min_dur_str}"
        if voice_count is not None:
            voices_repr = str(voice_count)
            if include_voice_names:
                voices_repr += f" ({list(voice_names)})"
            line += f", voices={voices_repr}"
        lines.append(line)

    if not lines:
        lines.append("- none")

    return [header, *lines]


def print_parsed_summary(
    results: Iterable[Mapping[str, Any]],
    *,
    include_voice_names: bool = True,
    header: str = "Parsed DataFrames:",
    logger: Optional[Callable[[str], None]] = None,
) -> List[str]:
    """
    Print a quick summary of parsed results and return the rendered lines.

    Parameters mirror ``format_parsed_summary`` with an optional ``logger`` for
    custom output handling.
    """
    lines = format_parsed_summary(
        results,
        include_voice_names=include_voice_names,
        header=header,
    )
    log = logger or print
    for line in lines:
        log(line)
    return lines
