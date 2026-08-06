from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from .music_utils import (  # type: ignore
    draw_piano_roll,
    filter_and_adjust_durations,
    get_file_path,
    get_measure_offsets,
    canonicalize_pitch_name,
)
from .parser_utils import (
    reject_unexpected_kwargs,
    resolve_collapse_tied_pitch_events,
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

_EVENT_DF_COLUMNS = [
    "type",
    "subtype",
    "Measure",
    "Local Onset",
    "Global Onset",
    "Duration",
    "Voice",
    "xml_id",
    "start_xml_id",
    "end_xml_id",
    "staff_n",
    "staff_raw",
    "layer_n",
    "layer_raw",
    "scope",
    "text",
    "text_role",
    "form",
    "place",
    "func",
    "plist",
    "tstamp_raw",
    "tstamp2_raw",
    "verse_n",
    "wordpos",
    "con",
    "mm",
    "mm_unit",
    "mm_dots",
    "measure_type",
    "measure_metcon",
    "measure_join",
    "measure_n",
    "extra",
]


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
    slug = re.sub(r"[^a-z0-9]+", "_", stem.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return f"{index:02d}_" + slug


def _empty_event_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=list(_EVENT_DF_COLUMNS))


def _clean_xml_id(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    try:
        value = str(raw).strip()
    except Exception:
        return None
    if not value:
        return None
    return value[1:] if value.startswith("#") else value


def _music21_part_label(part: Any, index: int) -> str:
    for candidate in (
        getattr(part, "partName", None),
        getattr(part, "partAbbreviation", None),
        getattr(part, "bestName", lambda: None)() if hasattr(part, "bestName") else None,
    ):
        if candidate is None:
            continue
        label = str(candidate).strip()
        if label:
            return label

    raw_id = getattr(part, "id", None)
    if isinstance(raw_id, str):
        label = raw_id.strip()
        if label:
            return label

    return f"P{index}"


def _music21_voice_label(element: Any, part_label: str) -> str:
    voice_ctx = element.getContextByClass("Voice")
    if voice_ctx is None:
        return f"{part_label} - Voice 1"

    raw_voice = getattr(voice_ctx, "id", None) or getattr(voice_ctx, "name", None)
    if raw_voice is None:
        raw_voice = getattr(voice_ctx, "index", None)
    if raw_voice is None:
        return f"{part_label} - Voice 1"

    voice_label = str(raw_voice).strip()
    if not voice_label:
        return f"{part_label} - Voice 1"
    if voice_label.isdigit():
        voice_label = f"Voice {voice_label}"
    elif not voice_label.lower().startswith("voice"):
        voice_label = f"Voice {voice_label}"
    return f"{part_label} - {voice_label}"


def _music21_score_to_rows(
    score: Any,
    *,
    include_xml_ids: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, str]]:
    note_rows: List[Dict[str, Any]] = []
    rest_rows: List[Dict[str, Any]] = []
    staff_to_part: Dict[str, str] = {}

    from music21 import chord as chord_module  # local import
    from music21 import note as note_module  # local import

    parts = list(getattr(score, "parts", []) or [])
    for part_index, part in enumerate(parts, start=1):
        part_label = _music21_part_label(part, part_index)
        staff_n = str(part_index)
        staff_to_part[staff_n] = part_label

        try:
            elements = part.flatten().notesAndRests.stream()
        except Exception:
            elements = []

        for element in elements:
            if not isinstance(element, (note_module.Note, chord_module.Chord, note_module.Rest)):
                continue

            measure = element.getContextByClass("Measure")
            if measure is not None:
                try:
                    measure_num = int(measure.number)
                except Exception:
                    measure_num = 0
                try:
                    measure_offset = float(measure.offset)
                except Exception:
                    measure_offset = 0.0
            else:
                measure_num = 0
                measure_offset = 0.0

            try:
                global_onset = float(element.offset)
            except Exception:
                continue
            try:
                duration = float(element.duration.quarterLength)
            except Exception:
                duration = 0.0

            local_onset = float(global_onset - measure_offset)
            voice_label = _music21_voice_label(element, part_label)
            xml_id_value = _clean_xml_id(getattr(element, "id", None)) if include_xml_ids else None

            base_row: Dict[str, Any] = {
                "Measure": measure_num,
                "Local Onset": local_onset,
                "Global Onset": global_onset,
                "Duration": duration,
                "Voice": voice_label,
                "staff_n": staff_n,
            }
            if include_xml_ids:
                base_row["xml_id"] = xml_id_value

            if isinstance(element, note_module.Rest):
                rest_rows.append(dict(base_row))
                continue

            if isinstance(element, note_module.Note):
                pitches = [str(element.pitch)]
            else:
                pitches = [str(pitch) for pitch in element.pitches]

            for pitch_name in pitches:
                row = dict(base_row)
                row["Pitch"] = pitch_name
                note_rows.append(row)

    return note_rows, rest_rows, staff_to_part


def _music21_rest_events_to_dataframe(df_rests: pd.DataFrame) -> pd.DataFrame:
    if df_rests.empty:
        return _empty_event_dataframe()

    rows: List[Dict[str, Any]] = []
    for _, row in df_rests.iterrows():
        rows.append(
            {
                "type": "rest",
                "subtype": "rest",
                "Measure": row.get("Measure", pd.NA),
                "Local Onset": row.get("Local Onset", pd.NA),
                "Global Onset": row.get("Global Onset", pd.NA),
                "Duration": row.get("Duration", 0.0),
                "Voice": row.get("Voice", pd.NA),
                "xml_id": row.get("xml_id", pd.NA),
                "start_xml_id": pd.NA,
                "end_xml_id": pd.NA,
                "staff_n": row.get("staff_n", pd.NA),
                "staff_raw": pd.NA,
                "layer_n": pd.NA,
                "layer_raw": pd.NA,
                "scope": "timeline",
                "text": pd.NA,
                "text_role": pd.NA,
                "form": pd.NA,
                "place": pd.NA,
                "func": pd.NA,
                "plist": pd.NA,
                "tstamp_raw": pd.NA,
                "tstamp2_raw": pd.NA,
                "verse_n": pd.NA,
                "wordpos": pd.NA,
                "con": pd.NA,
                "mm": pd.NA,
                "mm_unit": pd.NA,
                "mm_dots": pd.NA,
                "measure_type": row.get("measure_type", pd.NA),
                "measure_metcon": row.get("measure_metcon", pd.NA),
                "measure_join": row.get("measure_join", pd.NA),
                "measure_n": row.get("measure_n", pd.NA),
                "extra": pd.NA,
            }
        )

    df_events = pd.DataFrame(rows)
    for col in _EVENT_DF_COLUMNS:
        if col not in df_events.columns:
            df_events[col] = pd.NA
    return df_events[_EVENT_DF_COLUMNS].sort_values("Global Onset", na_position="last").reset_index(drop=True)


def _music21_anchor_timeline(df_pitch: pd.DataFrame, df_rests: pd.DataFrame) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    if not df_pitch.empty:
        pitch_cols = [col for col in ("xml_id", "Global Onset", "Duration", "Voice", "MIDI") if col in df_pitch.columns]
        if pitch_cols:
            frames.append(df_pitch[pitch_cols].copy())

    if not df_rests.empty:
        rest_anchor = df_rests.copy()
        if "MIDI" not in rest_anchor.columns:
            rest_anchor["MIDI"] = pd.NA
        rest_cols = [col for col in ("xml_id", "Global Onset", "Duration", "Voice", "MIDI") if col in rest_anchor.columns]
        if rest_cols:
            frames.append(rest_anchor[rest_cols].copy())

    if not frames:
        return pd.DataFrame(columns=["xml_id", "Global Onset", "Duration", "Voice", "MIDI"])

    return pd.concat(frames, ignore_index=True, sort=False).sort_values(
        ["Global Onset", "Duration"],
        na_position="last",
    ).reset_index(drop=True)


def _load_mei_event_helpers() -> Optional[Mapping[str, Any]]:
    try:
        from .partitura_backend import (  # type: ignore
            _align_event_voices_to_pitch_df,
            _attach_barline_event_offsets,
            _attach_barline_event_onsets_from_pitch_df,
            _barline_events_to_dataframe,
            _dedupe_mei_events_prefer_anchored,
            _extract_mei_events,
            _other_mei_events_to_dataframe,
        )
    except Exception:
        return None

    return {
        "align_event_voices_to_pitch_df": _align_event_voices_to_pitch_df,
        "attach_barline_event_offsets": _attach_barline_event_offsets,
        "attach_barline_event_onsets_from_pitch_df": _attach_barline_event_onsets_from_pitch_df,
        "barline_events_to_dataframe": _barline_events_to_dataframe,
        "dedupe_mei_events_prefer_anchored": _dedupe_mei_events_prefer_anchored,
        "extract_mei_events": _extract_mei_events,
        "other_mei_events_to_dataframe": _other_mei_events_to_dataframe,
    }


def parse_files(
    file_sources: Iterable[str],
    *,
    filter_zero_duration: bool = True,
    adjust_fractional_duration: bool = True,
    parse_enharmonic: bool = False,
    backend: str = "plt",
    show_measure_lines: bool = True,
    measure_line_color: str = "red",
    plot_parsed_barlines_with_voice_coloring: bool = False,
    show_hover: bool = True,
    hover_fields: Optional[List[str]] = None,
    display_preview_df_pitch: bool = True,
    display_preview_df_events: bool = True,
    preview_rows: int = 20,
    cleanup_remote: bool = True,
    return_plots: bool = False,
    plot_width: Optional[int] = None,
    plot_height: Optional[int] = None,
    zoom_drag_dim: Optional[str] = None,
    zoom_wheel_dim: Optional[str] = None,
    show_progress: bool = True,
    progress_desc: Optional[str] = None,
    collapse_tied_pitch_events: Optional[bool] = None,
    align_accident_schema: bool = False,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
    include_xml_ids: bool = True,
    try_verovio_mei_conversion: bool = True,
    allow_music21_fallback: bool = True,
    dedupe_weaker_text_events: bool = True,
    quiet_native_warnings: bool = False,
    **deprecated_kwargs: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse multiple symbolic music files using music21.

    This backend remains a legacy parser, but it now mirrors the partitura
    result schema more closely:
    - extracts note xml ids from music21 element ids when available
    - emits rest rows in df_events
    - exposes df_pitch/df_events and matching dfs_by_name entries
    - reuses the MEI XML event extraction helpers when partitura is installed

    Parameters accepted for backend parity but not used directly here:
    - try_verovio_mei_conversion
    - allow_music21_fallback
    - quiet_native_warnings
    """
    collapse_tied_pitch_events = resolve_collapse_tied_pitch_events(
        collapse_tied_pitch_events,
        deprecated_kwargs,
    )
    reject_unexpected_kwargs(deprecated_kwargs, "parse_files")
    del try_verovio_mei_conversion, allow_music21_fallback, quiet_native_warnings

    results: List[Dict[str, Any]] = []
    dfs_by_name: Dict[str, pd.DataFrame] = {}
    last_df: Optional[pd.DataFrame] = None

    try:
        from IPython.display import display as ipy_display  # type: ignore
    except Exception:
        ipy_display = None

    sources: List[str] = list(file_sources)
    use_progress = bool(show_progress) and (_tqdm is not None) and (len(sources) > 1)
    pbar = _tqdm(total=len(sources), desc=(progress_desc or "Parsing files"), unit="file") if use_progress else None
    log = _tqdm.write if use_progress else print

    try:
        for idx, file_source in enumerate(sources):
            file_path: Optional[str] = None
            try:
                name = _source_to_name(file_source, idx)
                short_name = os.path.basename(file_source).split("?")[0].split("#")[0]
                log(f"Processing (music21): {short_name} -> {name}")
                if pbar is not None:
                    pbar.set_postfix_str(short_name)

                file_path = get_file_path(file_source)

                from music21 import converter as _converter  # lazy import
                from music21 import pitch as pitch_module  # lazy import

                score = _converter.parse(file_path)
                if collapse_tied_pitch_events:
                    try:
                        score = score.stripTies(inPlace=False)
                    except Exception:
                        pass

                note_rows, rest_rows, staff_to_part = _music21_score_to_rows(
                    score,
                    include_xml_ids=include_xml_ids,
                )

                df_raw = pd.DataFrame(note_rows)
                if df_raw.empty:
                    df_raw = pd.DataFrame(columns=["Measure", "Local Onset", "Global Onset", "Duration", "Pitch", "Voice"])
                if include_xml_ids and "xml_id" not in df_raw.columns:
                    df_raw["xml_id"] = pd.NA

                if not df_raw.empty and "Pitch" in df_raw.columns:
                    df_raw["MIDI"] = df_raw["Pitch"].apply(lambda value: pitch_module.Pitch(value).midi)
                    if parse_enharmonic:
                        df_raw["Pitch Enharmonic"] = df_raw["Pitch"]
                    df_raw["Pitch"] = df_raw["MIDI"].apply(_midi_to_pitch_name)
                else:
                    df_raw["MIDI"] = pd.Series(dtype="Int64")
                    if parse_enharmonic and "Pitch Enharmonic" not in df_raw.columns:
                        df_raw["Pitch Enharmonic"] = pd.Series(dtype="object")

                excess_clamped = 0
                if align_accident_schema:
                    source_col = "Pitch Enharmonic" if parse_enharmonic else "Pitch"
                    if source_col in df_raw.columns:
                        if parse_enharmonic:
                            def _canon(value: Any) -> Tuple[str, bool]:
                                try:
                                    text = str(value)
                                except Exception:
                                    return str(value), False
                                if not text or text[0].upper() not in "ABCDEFG":
                                    return text, False
                                return canonicalize_pitch_name(text, max_accidentals=5)

                            canon_series = df_raw[source_col].apply(_canon)
                            df_raw[source_col] = canon_series.map(lambda item: item[0])
                            try:
                                excess_clamped = int(canon_series.map(lambda item: 1 if item[1] else 0).sum())
                            except Exception:
                                excess_clamped = 0
                        if excess_clamped > 0:
                            log(f"Warning: {excess_clamped} note(s) exceeded ±5 accidentals; clamped to 5.")

                pitch_cols = ["Measure", "Local Onset", "Global Onset", "Duration", "Pitch"]
                if parse_enharmonic:
                    pitch_cols.append("Pitch Enharmonic")
                pitch_cols += ["MIDI", "Voice"]
                if include_xml_ids:
                    pitch_cols.append("xml_id")
                for col in pitch_cols:
                    if col not in df_raw.columns:
                        df_raw[col] = pd.NA
                df_raw = df_raw[pitch_cols].sort_values(["Global Onset", "MIDI"], na_position="last").reset_index(drop=True)

                df_pitch = filter_and_adjust_durations(
                    df_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values(["Global Onset", "MIDI"], na_position="last").reset_index(drop=True)

                if include_xml_ids and "xml_id" not in df_pitch.columns:
                    df_pitch["xml_id"] = pd.NA

                df_rests_raw = pd.DataFrame(rest_rows)
                if df_rests_raw.empty:
                    df_rests_timed = pd.DataFrame(columns=["Measure", "Local Onset", "Global Onset", "Duration", "Voice", "xml_id", "staff_n"])
                else:
                    if include_xml_ids and "xml_id" not in df_rests_raw.columns:
                        df_rests_raw["xml_id"] = pd.NA
                    if "staff_n" not in df_rests_raw.columns:
                        df_rests_raw["staff_n"] = pd.NA
                    rest_cols = ["Measure", "Local Onset", "Global Onset", "Duration", "Voice", "xml_id", "staff_n"]
                    for col in rest_cols:
                        if col not in df_rests_raw.columns:
                            df_rests_raw[col] = pd.NA
                    df_rests_raw = df_rests_raw[rest_cols]
                    df_rests_timed = filter_and_adjust_durations(
                        df_rests_raw,
                        filter_zero_duration=filter_zero_duration,
                        adjust_fractional_duration=adjust_fractional_duration,
                    ).sort_values("Global Onset", na_position="last").reset_index(drop=True)

                measure_offsets = get_measure_offsets(score)
                df_anchor = _music21_anchor_timeline(df_pitch, df_rests_timed)
                df_rests = _music21_rest_events_to_dataframe(df_rests_timed)
                if not df_rests.empty:
                    log(f"Extracted rest timing events: {len(df_rests)} event(s).")

                barline_events: List[Dict[str, Any]] = []
                df_barlines = _empty_event_dataframe()
                df_other_events = _empty_event_dataframe()
                mei_helpers = _load_mei_event_helpers() if Path(file_path).suffix.lower() == ".mei" else None

                if Path(file_path).suffix.lower() == ".mei":
                    if mei_helpers is None:
                        log("Warning: MEI event extraction helpers unavailable; skipping non-rest MEI events.")
                    else:
                        extracted_mei_events = list(mei_helpers["extract_mei_events"](file_path))
                        if dedupe_weaker_text_events:
                            extracted_mei_events, weak_dupe_count = mei_helpers["dedupe_mei_events_prefer_anchored"](
                                extracted_mei_events
                            )
                            if weak_dupe_count > 0:
                                log(
                                    "Dropped weaker duplicate MEI text events: "
                                    f"{weak_dupe_count} row(s) without usable anchors."
                                )

                        barline_events = [
                            dict(event) for event in extracted_mei_events
                            if str(event.get("event", "")).strip().lower() == "barline"
                        ]
                        other_events = [
                            dict(event) for event in extracted_mei_events
                            if str(event.get("event", "")).strip().lower() != "barline"
                        ]

                        barline_events = mei_helpers["attach_barline_event_onsets_from_pitch_df"](
                            barline_events,
                            df_anchor,
                            staff_to_part_label=staff_to_part,
                        )
                        barline_events = mei_helpers["attach_barline_event_offsets"](
                            barline_events,
                            measure_offsets,
                        )

                        if barline_events:
                            forms = sorted({str(event.get("form", "single")) for event in barline_events})
                            log(
                                "Extracted MEI barline events: "
                                f"{len(barline_events)} event(s), forms={forms}."
                            )
                        if other_events:
                            types = sorted({str(event.get("event", "")).strip().lower() for event in other_events})
                            log(
                                "Extracted non-barline MEI events: "
                                f"{len(other_events)} event(s), types={types}."
                            )

                        df_barlines = mei_helpers["barline_events_to_dataframe"](
                            barline_events,
                            measure_offsets=measure_offsets,
                        )
                        df_other_events = mei_helpers["other_mei_events_to_dataframe"](
                            other_events,
                            df_anchor,
                            measure_offsets=measure_offsets,
                        )

                event_frames = [frame for frame in (df_barlines, df_rests, df_other_events) if not frame.empty]
                if not event_frames:
                    df_events = _empty_event_dataframe()
                elif len(event_frames) == 1:
                    df_events = event_frames[0].copy()
                else:
                    df_events = pd.concat(event_frames, ignore_index=True, sort=False)
                    for col in _EVENT_DF_COLUMNS:
                        if col not in df_events.columns:
                            df_events[col] = pd.NA
                    df_events = df_events[_EVENT_DF_COLUMNS]
                    df_events = df_events.sort_values("Global Onset", na_position="last").reset_index(drop=True)

                if mei_helpers is not None:
                    df_events = mei_helpers["align_event_voices_to_pitch_df"](
                        df_events,
                        df_pitch,
                        staff_to_part_label=staff_to_part,
                    )

                pitch_name = f"{name}_pitch"
                events_name = f"{name}_events"

                plot_obj = None
                if return_plots or backend != "none":
                    plot_obj = draw_piano_roll(
                        df_pitch,
                        measure_offsets=measure_offsets,
                        backend=backend,
                        barline_events=df_events,
                        plot_parsed_barlines_with_voice_coloring=plot_parsed_barlines_with_voice_coloring,
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

                if display_preview_df_pitch and ipy_display is not None:
                    ipy_display(df_pitch.head(preview_rows))
                    log(f"Rows: {len(df_pitch)}, unique pitches: {df_pitch['MIDI'].nunique() if 'MIDI' in df_pitch.columns else 0}")
                if display_preview_df_events and ipy_display is not None:
                    ipy_display(df_events.head(preview_rows))
                    log(f"Event rows: {len(df_events)}")

                result_entry: Dict[str, Any] = {
                    "name": name,
                    "source": file_source,
                    "df": df_pitch,
                    "df_pitch": df_pitch,
                    "df_events": df_events,
                    "df_name_pitch": pitch_name,
                    "df_name_events": events_name,
                    "measure_offsets": measure_offsets,
                    "barline_events": barline_events,
                }
                if return_plots:
                    result_entry["plot"] = plot_obj

                results.append(result_entry)
                dfs_by_name[pitch_name] = df_pitch
                dfs_by_name[events_name] = df_events
                last_df = df_pitch

                if cleanup_remote and file_source.startswith(("http://", "https://")) and file_path:
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
