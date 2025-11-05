from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


def _ensure_pkg_resources_shim() -> None:
    """
    Provide the tiny subset of pkg_resources functionality that partitura needs
    without importing the real (deprecated) pkg_resources module.
    """
    if "pkg_resources" in sys.modules:
        return
    try:
        from importlib import metadata as _metadata
        from importlib import resources as _resources
    except Exception:  # pragma: no cover - fallback: real pkg_resources will be used
        return

    class _Distribution:
        __slots__ = ("_name",)

        def __init__(self, name: str) -> None:
            self._name = name

        @property
        def version(self) -> str:
            return _metadata.version(self._name)

    def _get_distribution(dist_name: str) -> _Distribution:
        return _Distribution(dist_name)

    def _resource_filename(package: str, resource: str) -> str:
        ref = _resources.files(package).joinpath(resource)
        with _resources.as_file(ref) as path:
            return str(path)

    shim = types.ModuleType("pkg_resources")
    shim.get_distribution = _get_distribution  # type: ignore[attr-defined]
    shim.resource_filename = _resource_filename  # type: ignore[attr-defined]
    shim.DistributionNotFound = _metadata.PackageNotFoundError  # type: ignore[attr-defined]
    shim.PackageNotFoundError = _metadata.PackageNotFoundError  # type: ignore[attr-defined]
    sys.modules["pkg_resources"] = shim


_ensure_pkg_resources_shim()

try:  # pragma: no cover - optional dependency
    import partitura as pt
    from partitura.io import importkern, importmusicxml
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise ImportError(
        "The 'partitura' package is required for the partitura backend. "
        "Install it with `pip install partitura`."
    ) from exc

from .music_utils import (  # type: ignore
    draw_piano_roll,
    filter_and_adjust_durations,
    get_file_path,
)

try:  # pragma: no cover - optional dependency
    from tqdm.auto import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None

__all__ = ["partitura_score_to_dataframe", "parse_files_partitura"]

_PITCH_CLASS_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_TEXTUAL_EXTENSIONS = {".xml", ".musicxml", ".mei", ".krn", ".kern", ".hum"}


def _midi_to_pitch_name(midi: int) -> str:
    """
    Convert MIDI pitch number to a textual pitch name (e.g., 60 -> C4).
    """
    octave = (midi // 12) - 1
    pc = _PITCH_CLASS_NAMES[midi % 12]
    return f"{pc}{octave}"


def _slugify_name(text: str) -> str:
    """
    Convert text to a filesystem-friendly slug: lowercase, alphanumeric and underscores.
    """
    import re

    base = text.strip().lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    base = re.sub(r"_+", "_", base)
    return base.strip("_")


def _source_to_name(file_source: str, index: int) -> str:
    """
    Build a stable name for a parsed file: 2-digit index + slugified basename without extension.
    Example: 00_wtc1f01
    """
    base = os.path.basename(file_source)
    if "/" in file_source or "\\" in file_source:
        base = base.split("?")[0].split("#")[0]
    stem, _ = os.path.splitext(base)
    return f"{index:02d}_" + _slugify_name(stem)


def _format_voice_label(part_label: str, voice: Union[int, str, None]) -> str:
    """
    Produce a human-readable voice label combining part information with voice index.
    """
    base = part_label.strip() if part_label else ""
    if voice is None or (isinstance(voice, (int, float)) and int(voice) < 0):
        return base or "Voice"
    try:
        voice_int = int(voice)
        if voice_int < 0:
            raise ValueError
        voice_suffix = f"Voice {voice_int}"
    except Exception:
        voice_suffix = str(voice).strip()
    if not base:
        return voice_suffix
    if not voice_suffix:
        return base
    return f"{base} - {voice_suffix}"


def _sanitize_source_for_partitura(source_path: str) -> Tuple[str, Optional[Callable[[], None]]]:
    """
    Clean up textual score files before feeding them into partitura to avoid parser warnings.

    Returns the path to use and an optional cleanup callback.
    """
    path = Path(source_path)
    suffix = path.suffix.lower()
    if suffix not in _TEXTUAL_EXTENSIONS or not path.exists():
        return source_path, None

    try:
        original_text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return source_path, None

    text = original_text.lstrip("\ufeff")

    # Drop leading empty lines to keep numpy/genfromtxt happy.
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)

    if suffix in {".krn", ".kern", ".hum"}:
        while lines and lines[0].lstrip().startswith("!"):
            lines.pop(0)
        cleaned: List[str] = []
        for line in lines:
            tokens = [tok for tok in line.split("\t") if tok]
            if tokens and all(tok.startswith("*part") for tok in tokens):
                continue
            cleaned.append(line)
        lines = cleaned

    if original_text.endswith(("\r", "\n")):
        trailing_newline = "\n"
    else:
        trailing_newline = ""

    sanitized = "\n".join(lines) + trailing_newline
    filtered = "".join(
        ch for ch in sanitized if not (0xF000 <= ord(ch) <= 0xF8FF)
    )
    if filtered != sanitized:
        sanitized = filtered

    if sanitized == original_text:
        return source_path, None

    tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=suffix)
    try:
        tmp.write(sanitized)
    finally:
        tmp.close()

    def _cleanup() -> None:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

    return tmp.name, _cleanup


def _load_partitura_score(file_path: str):
    suffix = Path(file_path).suffix.lower()
    if suffix in {".krn", ".kern"}:
        return importkern.load_kern(file_path, force_same_part=True)
    if suffix == ".xml":
        try:
            return importmusicxml.load_musicxml(file_path)
        except Exception:
            # Fallback to the generic loader if load_musicxml fails.
            return pt.load_score(file_path)
    return pt.load_score(file_path)


def _part_to_rows(part) -> List[Dict[str, Any]]:
    """
    Convert a single partitura Part into a list of row dictionaries compatible with CAMAT dataframes.
    """
    rows: List[Dict[str, Any]] = []
    note_array = part.note_array(
        include_metrical_position=True, include_divs_per_quarter=True
    )
    if note_array.size == 0:
        return rows

    measure_map = part.measure_map
    quarter_map = part.quarter_map
    measure_number_map = part.measure_number_map
    part_label = (
        getattr(part, "part_name", None)
        or getattr(part, "name", None)
        or getattr(part, "id", None)
        or ""
    )

    fields = set(note_array.dtype.names or ())
    has_divs = "divs_pq" in fields
    has_rel = "rel_onset_div" in fields
    has_voice = "voice" in fields

    for note_row in note_array:
        onset_q = float(note_row["onset_quarter"])
        duration_q = float(note_row["duration_quarter"])
        if not np.isfinite(onset_q) or not np.isfinite(duration_q):
            continue

        try:
            measure_bounds = measure_map(onset_q)
            measure_start_t = measure_bounds[0]
            measure_start_q = quarter_map(measure_start_t)
            if isinstance(measure_start_q, np.ndarray):
                measure_start_q = measure_start_q.item()
            measure_start_q = float(measure_start_q)
            if not np.isfinite(measure_start_q):
                raise ValueError
        except Exception:
            # Fallback: derive from relative onset if available
            divs_per_q = float(note_row["divs_pq"]) if has_divs else 0.0
            rel_div = float(note_row["rel_onset_div"]) if has_rel else 0.0
            rel_q = rel_div / divs_per_q if divs_per_q else 0.0
            measure_start_q = onset_q - rel_q

        local_onset = onset_q - measure_start_q
        try:
            measure_num_raw = measure_number_map(onset_q)
            if isinstance(measure_num_raw, np.ndarray):
                measure_num_raw = measure_num_raw.item()
            measure_num = int(measure_num_raw)
        except Exception:
            measure_num = 0

        midi_pitch = int(note_row["pitch"])
        voice_value = note_row["voice"] if has_voice else None
        voice_label = _format_voice_label(part_label, voice_value)

        rows.append(
            {
                "Measure": measure_num,
                "Local Onset": float(local_onset),
                "Global Onset": onset_q,
                "Duration": duration_q,
                "Pitch": _midi_to_pitch_name(midi_pitch),
                "MIDI": midi_pitch,
                "Voice": voice_label,
            }
        )

    return rows


def partitura_score_to_dataframe(score) -> pd.DataFrame:
    """
    Convert a partitura Score into a CAMAT-compatible dataframe.
    """
    all_rows: List[Dict[str, Any]] = []
    for part in getattr(score, "parts", []):
        all_rows.extend(_part_to_rows(part))

    df = pd.DataFrame(
        all_rows,
        columns=[
            "Measure",
            "Local Onset",
            "Global Onset",
            "Duration",
            "Pitch",
            "MIDI",
            "Voice",
        ],
    )
    if len(df):
        df = df.sort_values(["Global Onset", "MIDI"]).reset_index(drop=True)
    return df


def _partitura_measure_offsets(score) -> List[float]:
    """
    Compute measure start offsets (in quarter units) using the first part of the score.
    """
    parts = getattr(score, "parts", None)
    if not parts:
        return []

    primary_part = parts[0]
    quarter_map = primary_part.quarter_map
    offsets: List[float] = []
    seen: set[float] = set()
    for measure in getattr(primary_part, "measures", []):
        try:
            start_q = quarter_map(measure.start.t)
            if isinstance(start_q, np.ndarray):
                start_q = start_q.item()
            start_quarter = float(start_q)
        except Exception:
            continue
        key = round(start_quarter, 6)
        if not np.isfinite(start_quarter) or key in seen:
            continue
        seen.add(key)
        offsets.append(start_quarter)
    return sorted(offsets)


def parse_files_partitura(
    file_sources: Iterable[str],
    *,
    filter_zero_duration: bool = True,
    adjust_fractional_duration: bool = True,
    backend: str = "plt",
    show_measure_lines: bool = True,
    display_preview: bool = True,
    preview_rows: int = 20,
    cleanup_remote: bool = True,
    return_plots: bool = False,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
    show_progress: bool = True,
    progress_desc: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse multiple symbolic music files using partitura, producing CAMAT-ready dataframes.

    Parameters mirror py_scripts.music_utils.parse_files for drop-in compatibility.
    """
    results: List[Dict[str, Any]] = []
    dfs_by_name: Dict[str, pd.DataFrame] = {}
    last_df: Optional[pd.DataFrame] = None

    try:
        from IPython.display import display as ipy_display  # type: ignore
    except Exception:  # pragma: no cover - notebook only
        ipy_display = None

    sources: List[str] = list(file_sources)
    use_progress = bool(show_progress) and (_tqdm is not None) and (len(sources) > 1)
    pbar = (
        _tqdm(total=len(sources), desc=(progress_desc or "Parsing files"), unit="file")
        if use_progress
        else None
    )
    log = _tqdm.write if use_progress else print

    try:
        for idx, file_source in enumerate(sources):
            try:
                name = _source_to_name(file_source, idx)
                short_name = os.path.basename(file_source).split("?")[0].split("#")[0]
                log(f"Processing (partitura): {short_name} -> {name}")
                if pbar is not None:
                    pbar.set_postfix_str(short_name)

                file_path = get_file_path(file_source)
                sanitized_path, cleanup_fn = _sanitize_source_for_partitura(file_path)
                try:
                    score = _load_partitura_score(sanitized_path)
                finally:
                    if cleanup_fn:
                        cleanup_fn()

                df_raw = partitura_score_to_dataframe(score)
                df_processed = filter_and_adjust_durations(
                    df_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values("Global Onset").reset_index(drop=True)

                measure_offsets = _partitura_measure_offsets(score)

                plot_obj = None
                if return_plots or backend != "none":
                    plot_obj = draw_piano_roll(
                        df_processed,
                        measure_offsets=measure_offsets,
                        backend=backend,
                        show_measure_lines=show_measure_lines,
                        show=True,
                        plot_width=plot_width,
                        plot_height=plot_height,
                        zoom_drag_dim=zoom_drag_dim,
                        zoom_wheel_dim=zoom_wheel_dim,
                    )

                if display_preview and ipy_display is not None:
                    ipy_display(df_processed.head(preview_rows))
                    log(
                        f"Rows: {len(df_processed)}, unique pitches: {df_processed['MIDI'].nunique()}"
                    )

                result_entry: Dict[str, Any] = {
                    "name": name,
                    "source": file_source,
                    "df": df_processed,
                    "measure_offsets": measure_offsets,
                }
                if return_plots:
                    result_entry["plot"] = plot_obj
                results.append(result_entry)
                dfs_by_name[name] = df_processed
                last_df = df_processed

                if cleanup_remote and file_source.startswith(("http://", "https://")):
                    try:
                        os.remove(file_path)
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass

            except Exception as exc:
                log(f"An error occurred while processing {file_source}: {exc}")
            finally:
                if pbar is not None:
                    pbar.update(1)
    finally:
        if pbar is not None:
            pbar.close()

    return results, dfs_by_name, last_df
