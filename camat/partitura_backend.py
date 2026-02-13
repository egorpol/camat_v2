from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union, Sequence

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
    canonicalize_pitch_name,
    accidental_rank_from_name,
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


def _part_to_rows(part, *, parse_enharmonic: bool = False, include_xml_ids: bool = False) -> List[Dict[str, Any]]:
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

    # Build lookup maps for enharmonic spelling
    id_to_spelling: Dict[Any, str] = {}
    spelled_sequence: List[str] = []

    if parse_enharmonic:
        try:
            # Collect all note info first
            note_info = []
            for n in getattr(part, "notes", []):
                step = getattr(n, "step", None)
                octave = getattr(n, "octave", None)
                alter = getattr(n, "alter", None)
                if alter is None:
                    acc_name = str(getattr(n, "accidental", "") or "").lower()
                    if acc_name:
                        if acc_name in {"sharp", "sharp1"}:
                            alter = 1
                        elif acc_name in {"flat", "flat1"}:
                            alter = -1
                        elif acc_name in {"double-sharp", "sharp2"}:
                            alter = 2
                        elif acc_name in {"double-flat", "flat2"}:
                            alter = -2
                        else:
                            alter = 0

                acc = ""
                try:
                    a = int(round(float(alter))) if alter is not None else 0
                except Exception:
                    a = 0
                if a > 0:
                    acc = "#" * a
                elif a < 0:
                    acc = "b" * (-a)

                spelled = None
                if step is not None and octave is not None:
                    spelled = f"{str(step).upper()}{acc}{int(octave)}"

                if spelled:
                    # ID lookup
                    nid = getattr(n, "id", None) or getattr(n, "xml_id", None)
                    if nid is not None:
                        id_to_spelling[nid] = spelled

                    # Sorting info
                    start_t = getattr(getattr(n, "start", None), "t", 0)
                    midi_p = getattr(n, "midi_pitch", 0)
                    note_info.append((start_t, midi_p, spelled))

            # Sort by onset then pitch to match note_array order
            note_info.sort(key=lambda x: (x[0], x[1]))
            spelled_sequence = [x[2] for x in note_info]

        except Exception:
            id_to_spelling = {}
            spelled_sequence = []

    spelled_idx = 0
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

        # Optional xml:id extraction (MEI)
        xml_id_value: Optional[str] = None
        if include_xml_ids:
            # Try a variety of common field names present in note_array dtypes
            for fid in ("xml_id", "xmlid", "id", "note_id", "noteid", "xml:id"):
                try:
                    candidate = note_row[fid]  # type: ignore[index]
                except Exception:
                    candidate = None
                if candidate is None:
                    continue
                try:
                    s = str(candidate).strip()
                except Exception:
                    s = ""
                if s:
                    if s.startswith("#"):
                        s = s[1:]
                    xml_id_value = s
                    break

        row: Dict[str, Any] = {
            "Measure": measure_num,
            "Local Onset": float(local_onset),
            "Global Onset": onset_q,
            "Duration": duration_q,
            "Pitch": _midi_to_pitch_name(midi_pitch),
            "MIDI": midi_pitch,
            "Voice": voice_label,
        }
        if include_xml_ids:
            row["xml_id"] = xml_id_value
        if parse_enharmonic:
            spelled: Optional[str] = None

            # Try ID lookup first
            nid = None
            for fid in ("id", "note_id", "xml_id", "xmlid"):
                try:
                    val = note_row[fid]  # type: ignore[index]
                    if val is not None:
                        nid = val
                        break
                except Exception:
                    pass

            if nid in id_to_spelling:
                spelled = id_to_spelling[nid]

            # Fallback to sequential if ID failed but sequence exists
            # (Advance index regardless to stay in sync if mixing methods)
            seq_spelled = None
            if spelled_sequence and spelled_idx < len(spelled_sequence):
                seq_spelled = spelled_sequence[spelled_idx]
                spelled_idx += 1

            if not spelled and seq_spelled:
                spelled = seq_spelled

            if spelled:
                row["Pitch Enharmonic"] = spelled
        rows.append(row)

    return rows


def partitura_score_to_dataframe(score, *, parse_enharmonic: bool = False, include_xml_ids: bool = False) -> pd.DataFrame:
    """
    Convert a partitura Score into a CAMAT-compatible dataframe.
    """
    all_rows: List[Dict[str, Any]] = []
    for part in getattr(score, "parts", []):
        all_rows.extend(_part_to_rows(part, parse_enharmonic=parse_enharmonic, include_xml_ids=include_xml_ids))

    # Build DataFrame; include optional column when present
    df = pd.DataFrame(all_rows)
    if parse_enharmonic and "Pitch Enharmonic" not in df.columns:
        # Ensure column exists (left as None) to reflect requested output schema
        df["Pitch Enharmonic"] = None
    expected = [
        "Measure",
        "Local Onset",
        "Global Onset",
        "Duration",
        "Pitch",
        "MIDI",
        "Voice",
    ]
    if include_xml_ids and "xml_id" in df.columns:
        # Place xml_id immediately after 'Voice'
        try:
            expected.insert(expected.index("Voice") + 1, "xml_id")
        except Exception:
            expected.append("xml_id")
    if parse_enharmonic and "Pitch Enharmonic" in df.columns:
        expected.insert(5, "Pitch Enharmonic")
    # Reorder if all present; otherwise let pandas keep available columns
    if set(expected).issubset(df.columns):
        df = df[expected]
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
    parse_enharmonic: bool = False,
    backend: str = "plt",
    show_measure_lines: bool = True,
    measure_line_color: str = "red",
    show_hover: bool = True,
    hover_fields: Optional[List[str]] = None,
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
    strip_ties: Optional[bool] = None,
    align_accident_schema: bool = False,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
    include_xml_ids: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse multiple symbolic music files using partitura, producing CAMAT-ready dataframes.

    Parameters mirror camat.music_utils.parse_files for drop-in compatibility.
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

                # Only include xml_id when MEI source detected and option enabled
                is_mei = str(sanitized_path).lower().endswith(".mei")
                want_xml_ids = bool(include_xml_ids)
                include_ids_this_score = want_xml_ids and is_mei
                df_raw = partitura_score_to_dataframe(
                    score,
                    parse_enharmonic=parse_enharmonic,
                    include_xml_ids=include_ids_this_score,
                )
                # Optionally align accidental schema prior to duration filtering (no extra rank column)
                excess_clamped = 0
                if align_accident_schema:
                    source_col = "Pitch Enharmonic" if parse_enharmonic else "Pitch"
                    if source_col in df_raw.columns:
                        if parse_enharmonic:
                            def _canon(v: Any) -> Tuple[Any, bool]:
                                # Keep None/NaN untouched
                                if v is None or (isinstance(v, float) and np.isnan(v)):
                                    return v, False
                                if not isinstance(v, str):
                                    try:
                                        v = str(v)
                                    except Exception:
                                        return v, False
                                # Only canonicalize plausible pitch names
                                if not v or v[0].upper() not in "ABCDEFG":
                                    return v, False
                                return canonicalize_pitch_name(v, max_accidentals=5)
                            canon_series = df_raw[source_col].apply(_canon)
                            df_raw[source_col] = canon_series.map(lambda t: t[0])
                            try:
                                excess_clamped = int(canon_series.map(lambda t: 1 if t[1] else 0).sum())
                            except Exception:
                                excess_clamped = 0
                        if excess_clamped > 0:
                            log(f"Warning: {excess_clamped} note(s) exceeded ±5 accidentals; clamped to 5.")
                df_processed = filter_and_adjust_durations(
                    df_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values("Global Onset").reset_index(drop=True)

                if want_xml_ids and not include_ids_this_score and "xml_id" not in df_processed.columns:
                    df_processed["xml_id"] = pd.NA

                measure_offsets = _partitura_measure_offsets(score)

                plot_obj = None
                if return_plots or backend != "none":
                    plot_obj = draw_piano_roll(
                        df_processed,
                        measure_offsets=measure_offsets,
                        backend=backend,
                        show_measure_lines=show_measure_lines,
                        measure_line_color=measure_line_color,
                        show_hover=show_hover,
                        hover_fields=hover_fields,
                        show=True,
                        plot_width=plot_width,
                        plot_height=plot_height,
                        zoom_drag_dim=zoom_drag_dim,
                        zoom_wheel_dim=zoom_wheel_dim,
                        colorize_voices=colorize_voices,
                        palette=palette,
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
