from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional, Tuple, Sequence, Union

import pandas as pd

from .music_utils import (  # type: ignore
    draw_piano_roll,
    extract_voice_data,
    filter_and_adjust_durations,
    get_file_path,
    get_measure_offsets,
    canonicalize_pitch_name,
)

try:  # pragma: no cover - optional dependency (progress bar)
    from tqdm.auto import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None

__all__ = ["parse_files"]


_PITCH_CLASS_NAMES = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)


def _midi_to_pitch_name(midi: int) -> str:
    octave = (int(midi) // 12) - 1
    pc = _PITCH_CLASS_NAMES[int(midi) % 12]
    return f"{pc}{octave}"


def _source_to_name(file_source: str, index: int) -> str:
    """
    Build a stable name for a parsed file: 2-digit index + slugified basename without extension.
    Example: 00_wtc1f01
    """
    import re

    base = os.path.basename(file_source)
    if "/" in file_source or "\\" in file_source:
        base = base.split("?")[0].split("#")[0]
    stem, _ = os.path.splitext(base)
    # simple slugify: lowercase, alnum+underscore
    slug = re.sub(r"[^a-z0-9]+", "_", stem.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return f"{index:02d}_" + slug


def parse_files(
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
    strip_ties: bool = True,
    align_accident_schema: bool = False,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse multiple symbolic music files using music21, with optional tie merging.

    Parameters mirror py_scripts.music_utils.parse_files with an extra:
    - strip_ties: if True (default), merge tied notes via music21's Stream.stripTies
      before extracting note rows, so tied notes become single longer notes.
    - align_accident_schema: if True, normalize enharmonic spellings to a canonical
      accidentals schema (clamped to ±5 as a failsafe) and warn if any notes exceed
      that limit. No extra rank column is added.
    """
    results: List[Dict[str, Any]] = []
    dfs_by_name: Dict[str, pd.DataFrame] = {}
    last_df: Optional[pd.DataFrame] = None

    try:
        from IPython.display import display as ipy_display  # type: ignore
    except Exception:
        ipy_display = None  # not in a notebook

    sources: List[str] = list(file_sources)
    use_progress = bool(show_progress) and (_tqdm is not None) and (len(sources) > 1)
    pbar = _tqdm(total=len(sources), desc=(progress_desc or "Parsing files"), unit="file") if use_progress else None
    log = (_tqdm.write if use_progress else print)

    try:
        for idx, file_source in enumerate(sources):
            try:
                name = _source_to_name(file_source, idx)
                short_name = os.path.basename(file_source).split("?")[0].split("#")[0]
                log(f"Processing (music21): {short_name} -> {name}")
                if pbar is not None:
                    pbar.set_postfix_str(short_name)

                file_path = get_file_path(file_source)

                from music21 import converter as _converter  # lazy import
                score = _converter.parse(file_path)

                if strip_ties:
                    try:
                        score = score.stripTies(inPlace=False)
                    except Exception:
                        # If stripTies fails for any reason, continue with original score
                        pass

                voice_data = extract_voice_data(score)
                df = pd.DataFrame(
                    voice_data,
                    columns=["Measure", "Local Onset", "Global Onset", "Duration", "Pitch", "Voice"],
                )
                
                from music21 import pitch as pitch_module  # localize import
                df["MIDI"] = df["Pitch"].apply(lambda p: pitch_module.Pitch(p).midi)
                # Preserve original score spelling in Pitch Enharmonic when requested
                if parse_enharmonic:
                    df["Pitch Enharmonic"] = df["Pitch"]
                # Normalize Pitch strictly from MIDI (simple sharps, no double accidentals)
                df["Pitch"] = df["MIDI"].apply(_midi_to_pitch_name)
                # Optionally align accidental schema and compute rank
                excess_clamped = 0
                if align_accident_schema:
                    # Prefer enharmonic column when present; otherwise use real pitch
                    source_col = "Pitch Enharmonic" if parse_enharmonic else "Pitch"
                    if source_col in df.columns:
                        if parse_enharmonic:
                            # Canonicalize enharmonic spellings and clamp to ±5 accidentals
                            def _canon(v: Any) -> Tuple[str, bool]:
                                try:
                                    s = str(v)
                                except Exception:
                                    return str(v), False
                                # Only canonicalize plausible pitches that start with A-G
                                if not s or s[0].upper() not in "ABCDEFG":
                                    return s, False
                                return canonicalize_pitch_name(s, max_accidentals=5)
                            canon_series = df[source_col].apply(_canon)
                            df[source_col] = canon_series.map(lambda t: t[0])
                            try:
                                excess_clamped = int(canon_series.map(lambda t: 1 if t[1] else 0).sum())
                            except Exception:
                                excess_clamped = 0
                        if excess_clamped > 0:
                            log(f"Warning: {excess_clamped} note(s) exceeded ±5 accidentals; clamped to 5.")
                base_cols = ["Measure", "Local Onset", "Global Onset", "Duration", "Pitch"]
                if parse_enharmonic:
                    base_cols.append("Pitch Enharmonic")
                base_cols += ["MIDI", "Voice"]
                df = df[base_cols]
                df = df.sort_values("Global Onset").reset_index(drop=True)

                df_processed = filter_and_adjust_durations(
                    df,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values("Global Onset").reset_index(drop=True)

                measure_offsets = get_measure_offsets(score)

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
                    log(f"Rows: {len(df_processed)}, unique pitches: {df_processed['MIDI'].nunique()}")

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


