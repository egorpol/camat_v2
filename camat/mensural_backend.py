from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from .music_utils import (
    canonicalize_pitch_name,
    draw_piano_roll,
    filter_and_adjust_durations,
    get_file_path,
    is_cached_download,
)
from .partitura_backend import (
    _EVENT_DF_COLUMNS,
    _align_event_voices_to_pitch_df,
    _attach_barline_event_offsets,
    _attach_barline_event_onsets_from_pitch_df,
    _barline_events_to_dataframe,
    _dedupe_mei_events_prefer_anchored,
    _empty_event_dataframe,
    _extract_mei_events,
    _file_looks_mensural_mei,
    _format_voice_label,
    _midi_to_pitch_name,
    _mei_event_merge_key,
    _normalize_xml_ref,
    _other_mei_events_to_dataframe,
    _source_to_name,
)
from .quiet_utils import suppress_native_output
from .verovio_guard import guarded_load_into_verovio_toolkit

try:  # pragma: no cover - optional dependency
    from tqdm.auto import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None

__all__ = ["parse_files_mensural"]


def _qfrac_payload_to_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if np.isfinite(value) else None
    if isinstance(raw, (list, tuple)):
        if len(raw) == 2 and all(isinstance(x, (int, float)) for x in raw):
            num = float(raw[0])
            den = float(raw[1])
            if den == 0:
                return None
            value = num / den
            return value if np.isfinite(value) else None
        if len(raw) > 0:
            return _qfrac_payload_to_float(raw[0])
    return None


def _mei_accid_to_suffix(raw: Any) -> str:
    token = None if raw is None else str(raw).strip().lower()
    if not token:
        return ""
    mapping = {
        "s": "#",
        "ss": "##",
        "x": "##",
        "xs": "###",
        "ts": "###",
        "f": "b",
        "ff": "bb",
        "tf": "bbb",
        "n": "",
    }
    return mapping.get(token, "")


def _mensural_duration_signature(el: Any) -> Tuple[str, str, str, str]:
    if el is None:
        return ("", "", "", "")
    attrib = getattr(el, "attrib", {}) or {}
    return (
        str(attrib.get("dur", "") or "").strip().lower(),
        str(attrib.get("num", "") or "").strip(),
        str(attrib.get("numbase", "") or "").strip(),
        str(attrib.get("dur.quality", "") or "").strip().lower(),
    )


def _infer_missing_timed_rows(timed_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not timed_rows:
        return []

    out = [dict(row) for row in timed_rows]

    duration_prototypes: Dict[Tuple[str, str, Tuple[str, str, str, str]], float] = {}
    global_duration_prototypes: Dict[Tuple[str, str, str, str], float] = {}
    for row in out:
        signature = row.get("duration_signature")
        if not isinstance(signature, tuple) or len(signature) != 4:
            continue
        duration = row.get("Duration")
        try:
            dur_val = float(duration)
        except Exception:
            continue
        if not np.isfinite(dur_val) or dur_val <= 0:
            continue
        staff_key = str(row.get("staff_n", "") or "").strip()
        layer_key = str(row.get("layer_n", "") or "").strip()
        scoped_key = (staff_key, layer_key, signature)
        if scoped_key not in duration_prototypes:
            duration_prototypes[scoped_key] = dur_val
        global_duration_prototypes.setdefault(signature, dur_val)

    for row in out:
        duration = row.get("Duration")
        try:
            dur_val = float(duration)
        except Exception:
            dur_val = np.nan
        if np.isfinite(dur_val) and dur_val > 0:
            continue
        signature = row.get("duration_signature")
        if not isinstance(signature, tuple) or len(signature) != 4:
            continue
        staff_key = str(row.get("staff_n", "") or "").strip()
        layer_key = str(row.get("layer_n", "") or "").strip()
        scoped_key = (staff_key, layer_key, signature)
        inferred_duration = duration_prototypes.get(scoped_key)
        if inferred_duration is None:
            inferred_duration = global_duration_prototypes.get(signature)
        if inferred_duration is None or not np.isfinite(inferred_duration) or inferred_duration <= 0:
            continue
        row["Duration"] = float(inferred_duration)

    changed = True
    max_passes = max(2, len(out) * 2)
    passes = 0
    while changed and passes < max_passes:
        passes += 1
        changed = False

        for idx, row in enumerate(out):
            onset = row.get("Global Onset")
            duration = row.get("Duration")
            try:
                onset_val = float(onset)
            except Exception:
                onset_val = np.nan
            try:
                dur_val = float(duration)
            except Exception:
                dur_val = np.nan
            if np.isfinite(onset_val) or not (np.isfinite(dur_val) and dur_val > 0):
                continue
            if idx <= 0:
                continue
            prev = out[idx - 1]
            try:
                prev_onset = float(prev.get("Global Onset"))
                prev_dur = float(prev.get("Duration"))
            except Exception:
                continue
            if np.isfinite(prev_onset) and np.isfinite(prev_dur) and prev_dur >= 0:
                row["Global Onset"] = float(prev_onset + prev_dur)
                changed = True

        for idx in range(len(out) - 1, -1, -1):
            row = out[idx]
            onset = row.get("Global Onset")
            duration = row.get("Duration")
            try:
                onset_val = float(onset)
            except Exception:
                onset_val = np.nan
            try:
                dur_val = float(duration)
            except Exception:
                dur_val = np.nan
            if np.isfinite(onset_val) or not (np.isfinite(dur_val) and dur_val > 0):
                continue
            if idx >= len(out) - 1:
                continue
            nxt = out[idx + 1]
            try:
                next_onset = float(nxt.get("Global Onset"))
            except Exception:
                continue
            if np.isfinite(next_onset):
                row["Global Onset"] = float(next_onset - dur_val)
                changed = True

    for row in out:
        row.pop("duration_signature", None)

    return out


def _source_staff_index_to_part_label_map_from_mei(mei_path: str) -> Dict[str, str]:
    try:
        import xml.etree.ElementTree as ET

        root = ET.parse(mei_path).getroot()
    except Exception:
        return {}

    def _local_name(tag: Any) -> str:
        raw = str(tag)
        return raw.rsplit("}", 1)[-1] if "}" in raw else raw

    def _first_token(raw: Any) -> Optional[str]:
        if raw is None:
            return None
        try:
            tokens = [tok for tok in str(raw).strip().split() if tok]
        except Exception:
            return None
        return tokens[0] if tokens else None

    mapping: Dict[str, str] = {}
    staff_defs = [el for el in root.iter() if _local_name(el.tag) == "staffDef"]
    xml_id_key = "{http://www.w3.org/XML/1998/namespace}id"
    for idx, staff_def in enumerate(staff_defs, start=1):
        staff_n = _first_token(staff_def.attrib.get("n")) or str(idx)
        label_text = None
        for child in list(staff_def):
            if _local_name(child.tag) != "label":
                continue
            try:
                label_text = " ".join(" ".join(child.itertext()).split())
            except Exception:
                label_text = None
            if label_text:
                break
        if not label_text:
            label_text = _normalize_xml_ref(staff_def.attrib.get(xml_id_key)) or f"Staff {staff_n}"
        mapping[str(staff_n)] = str(label_text).strip()
    return mapping


def _verovio_mensural_mei_note_dataframe(
    mei_path: str,
    *,
    parse_enharmonic: bool = False,
    include_xml_ids: bool = True,
    quiet_native_warnings: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str], Dict[str, Any]]:
    try:
        import xml.etree.ElementTree as ET
        import verovio  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "verovio and XML support are required for direct mensural timing extraction"
        ) from exc

    staff_to_part = _source_staff_index_to_part_label_map_from_mei(mei_path)
    tk = verovio.toolkit()
    mei_data = Path(mei_path).read_text(encoding="utf-8", errors="ignore")
    with suppress_native_output(enabled=quiet_native_warnings):
        load_info = guarded_load_into_verovio_toolkit(
            tk,
            mei_data,
            input_from="mei",
            options={"removeIds": False},
            source_hint=mei_path,
        )

    root = ET.parse(mei_path).getroot()
    xml_id_key = "{http://www.w3.org/XML/1998/namespace}id"

    def _local_name(tag: Any) -> str:
        raw = str(tag)
        return raw.rsplit("}", 1)[-1] if "}" in raw else raw

    def _get_xml_id(el: Any) -> Optional[str]:
        if el is None:
            return None
        return _normalize_xml_ref(el.attrib.get(xml_id_key) or el.attrib.get("xml:id"))

    def _first_token(raw: Any) -> Optional[str]:
        if raw is None:
            return None
        try:
            tokens = [tok for tok in str(raw).strip().split() if tok]
        except Exception:
            return None
        return tokens[0] if tokens else None

    rows: List[Dict[str, Any]] = []
    timed_rows: List[Dict[str, Any]] = []
    for staff_idx, staff_el in enumerate(
        [el for el in root.iter() if _local_name(el.tag) == "staff"],
        start=1,
    ):
        staff_n = _first_token(staff_el.attrib.get("n")) or str(staff_idx)
        part_label = staff_to_part.get(str(staff_n), f"Staff {staff_n}")
        layer_elements = [child for child in list(staff_el) if _local_name(child.tag) == "layer"]
        if not layer_elements:
            layer_elements = [staff_el]

        for layer_idx, layer_el in enumerate(layer_elements, start=1):
            layer_n = _first_token(getattr(layer_el, "attrib", {}).get("n")) or str(layer_idx)
            voice_label = _format_voice_label(part_label, layer_n)

            layer_timed_rows: List[Dict[str, Any]] = []
            for note_el in layer_el.iter():
                element_type = _local_name(note_el.tag)
                if element_type not in {"note", "rest", "chord"}:
                    continue
                xml_id = _get_xml_id(note_el)
                if not xml_id:
                    continue

                try:
                    times = tk.getTimesForElement(xml_id)
                except Exception:
                    times = {}
                if not isinstance(times, dict):
                    continue

                onset_q = _qfrac_payload_to_float(times.get("qfracOn"))
                duration_q = _qfrac_payload_to_float(times.get("qfracDuration"))

                timed_row: Dict[str, Any] = {
                    "Measure": pd.NA,
                    "Local Onset": np.nan,
                    "Global Onset": float(onset_q) if onset_q is not None else np.nan,
                    "Duration": float(duration_q) if duration_q is not None else np.nan,
                    "Voice": voice_label,
                    "staff_n": staff_n,
                    "layer_n": layer_n,
                    "element_type": element_type,
                    "duration_signature": _mensural_duration_signature(note_el),
                }
                if include_xml_ids:
                    timed_row["xml_id"] = xml_id
                layer_timed_rows.append(timed_row)

                if onset_q is None or duration_q is None or element_type != "note":
                    continue

                try:
                    midi_values = tk.getMIDIValuesForElement(xml_id)
                except Exception:
                    midi_values = {}
                if not isinstance(midi_values, dict):
                    continue
                midi_pitch = midi_values.get("pitch")
                if midi_pitch is None:
                    continue
                try:
                    midi_int = int(midi_pitch)
                except Exception:
                    continue

                row: Dict[str, Any] = {
                    "Measure": pd.NA,
                    "Local Onset": np.nan,
                    "Global Onset": float(onset_q),
                    "Duration": float(duration_q),
                    "Pitch": _midi_to_pitch_name(midi_int),
                    "MIDI": midi_int,
                    "Voice": voice_label,
                }
                if include_xml_ids:
                    row["xml_id"] = xml_id
                if parse_enharmonic:
                    pname = note_el.attrib.get("pname")
                    octave = note_el.attrib.get("oct")
                    if pname and octave:
                        suffix = _mei_accid_to_suffix(
                            note_el.attrib.get("accid") or note_el.attrib.get("accid.ges")
                        )
                        row["Pitch Enharmonic"] = f"{str(pname).upper()}{suffix}{octave}"
                rows.append(row)
            timed_rows.extend(_infer_missing_timed_rows(layer_timed_rows))

    df = pd.DataFrame(rows)
    df_timed = pd.DataFrame(timed_rows)
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
        expected.insert(expected.index("Voice") + 1, "xml_id")
    if parse_enharmonic and "Pitch Enharmonic" in df.columns:
        expected.insert(5, "Pitch Enharmonic")
    for col in expected:
        if col not in df.columns:
            df[col] = pd.NA
    if len(df):
        df = df.sort_values(["Global Onset", "MIDI"]).reset_index(drop=True)
    df = df[expected]
    timed_expected = [
        "Measure",
        "Local Onset",
        "Global Onset",
        "Duration",
        "Voice",
        "xml_id",
        "staff_n",
        "layer_n",
        "element_type",
    ]
    for col in timed_expected:
        if col not in df_timed.columns:
            df_timed[col] = pd.NA
    if len(df_timed):
        sort_columns = [col for col in ("Global Onset", "Duration") if col in df_timed.columns]
        if sort_columns:
            df_timed = df_timed.sort_values(sort_columns).reset_index(drop=True)
    df_timed = df_timed[timed_expected]
    return df, df_timed, staff_to_part, load_info


def _mensural_rest_events_to_dataframe(df_timed: pd.DataFrame) -> pd.DataFrame:
    if df_timed.empty or "element_type" not in df_timed.columns:
        return _empty_event_dataframe()

    rest_rows = df_timed[df_timed["element_type"].astype(str).str.lower() == "rest"].copy()
    if rest_rows.empty:
        return _empty_event_dataframe()

    rows: List[Dict[str, Any]] = []
    for _, row in rest_rows.iterrows():
        rows.append(
            {
                "type": "rest",
                "subtype": "rest",
                "Measure": row.get("Measure", pd.NA),
                "Local Onset": row.get("Local Onset", np.nan),
                "Global Onset": row.get("Global Onset", np.nan),
                "Duration": row.get("Duration", 0.0),
                "Voice": row.get("Voice", pd.NA),
                "xml_id": row.get("xml_id", pd.NA),
                "start_xml_id": pd.NA,
                "end_xml_id": pd.NA,
                "staff_n": row.get("staff_n", pd.NA),
                "staff_raw": pd.NA,
                "layer_n": row.get("layer_n", pd.NA),
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
                "extra": pd.NA,
            }
        )

    df_events = pd.DataFrame(rows)
    for col in _EVENT_DF_COLUMNS:
        if col not in df_events.columns:
            df_events[col] = pd.NA
    df_events = df_events[_EVENT_DF_COLUMNS]
    return df_events.sort_values("Global Onset", na_position="last").reset_index(drop=True)


def parse_files_mensural(
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
    strip_ties: Optional[bool] = None,
    align_accident_schema: bool = False,
    colorize_voices: bool = False,
    palette: Optional[Union[str, Sequence[str]]] = None,
    include_xml_ids: bool = True,
    normalize_mensural_durations: bool = True,
    inject_missing_meter_signature: bool = True,
    default_meter_count: int = 4,
    default_meter_unit: int = 4,
    try_verovio_mei_conversion: bool = True,
    prefer_verovio_for_mensural: bool = True,
    verovio_mensural_to_cmn: bool = True,
    verovio_duration_equivalence: Optional[float] = None,
    verovio_mensural_score_up: bool = False,
    use_verovio_mensural_timing: bool = True,
    allow_music21_fallback: bool = True,
    dedupe_weaker_text_events: bool = True,
    quiet_native_warnings: bool = False,
    use_remote_cache: bool = True,
    remote_cache_dir: Optional[str] = None,
    n_jobs: int = 1,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Parse mensural MEI directly on the original Verovio/source timeline.

    Extra keyword arguments shared with other backends are accepted for
    notebook/API compatibility; options related to partitura conversion are
    intentionally ignored here.
    """
    del (
        strip_ties,
        normalize_mensural_durations,
        inject_missing_meter_signature,
        default_meter_count,
        default_meter_unit,
        try_verovio_mei_conversion,
        prefer_verovio_for_mensural,
        verovio_mensural_to_cmn,
        verovio_duration_equivalence,
        verovio_mensural_score_up,
        use_verovio_mensural_timing,
        allow_music21_fallback,
        n_jobs,
    )

    results: List[Dict[str, Any]] = []
    dfs_by_name: Dict[str, pd.DataFrame] = {}
    last_df: Optional[pd.DataFrame] = None

    try:
        from IPython.display import display as ipy_display  # type: ignore
    except Exception:  # pragma: no cover
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
            file_path: Optional[str] = None
            try:
                if idx > 0 and len(sources) > 1:
                    log("")
                name = _source_to_name(str(file_source), idx)
                short_name = os.path.basename(str(file_source)).split("?")[0].split("#")[0]
                log(f"Processing (mensural): {short_name} -> {name}")
                if pbar is not None:
                    pbar.set_postfix_str(short_name)

                file_path = get_file_path(
                    file_source,
                    use_cache=bool(use_remote_cache),
                    cache_dir=remote_cache_dir,
                )
                is_mei_source = Path(file_path).suffix.lower() == ".mei"
                if not is_mei_source:
                    raise ValueError("parse_files_mensural currently supports MEI sources only")
                if not _file_looks_mensural_mei(file_path):
                    log("Warning: no explicit mensural markers detected; continuing on original Verovio timing.")

                df_raw, df_timed_raw, staff_to_part, verovio_load_info = _verovio_mensural_mei_note_dataframe(
                    file_path,
                    parse_enharmonic=parse_enharmonic,
                    include_xml_ids=True,
                    quiet_native_warnings=quiet_native_warnings,
                )
                if verovio_load_info.get("sanitized") and verovio_load_info.get("message"):
                    log(f"Warning: {verovio_load_info['message']}")
                extracted_mei_events = _extract_mei_events(file_path)
                measure_offsets: List[float] = []

                excess_clamped = 0
                if align_accident_schema:
                    source_col = "Pitch Enharmonic" if parse_enharmonic else "Pitch"
                    if source_col in df_raw.columns:
                        if parse_enharmonic:
                            def _canon(v: Any) -> Tuple[Any, bool]:
                                if v is None or (isinstance(v, float) and np.isnan(v)):
                                    return v, False
                                if not isinstance(v, str):
                                    try:
                                        v = str(v)
                                    except Exception:
                                        return v, False
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
                df_timed = filter_and_adjust_durations(
                    df_timed_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values("Global Onset").reset_index(drop=True)
                if bool(include_xml_ids) and "xml_id" not in df_processed.columns:
                    df_processed["xml_id"] = pd.NA
                if bool(include_xml_ids) and "xml_id" not in df_timed.columns:
                    df_timed["xml_id"] = pd.NA

                merged_events: List[Dict[str, Any]] = []
                seen_event_keys: set[Tuple[str, ...]] = set()
                for raw_event in extracted_mei_events:
                    event = dict(raw_event)
                    key = _mei_event_merge_key(event)
                    if key in seen_event_keys:
                        continue
                    seen_event_keys.add(key)
                    merged_events.append(event)
                extracted_mei_events = merged_events

                if dedupe_weaker_text_events:
                    extracted_mei_events, weak_dupe_count = _dedupe_mei_events_prefer_anchored(
                        extracted_mei_events
                    )
                    if weak_dupe_count > 0:
                        log(
                            "Dropped weaker duplicate MEI text events: "
                            f"{weak_dupe_count} row(s) without usable anchors."
                        )

                df_pitch = df_processed
                barline_events = [
                    dict(evt) for evt in extracted_mei_events
                    if str(evt.get("event", "")).strip().lower() == "barline"
                ]
                other_events = [
                    dict(evt) for evt in extracted_mei_events
                    if str(evt.get("event", "")).strip().lower() != "barline"
                ]
                barline_events = _attach_barline_event_onsets_from_pitch_df(
                    barline_events,
                    df_timed,
                    staff_to_part_label=staff_to_part,
                )
                barline_events = _attach_barline_event_offsets(barline_events, measure_offsets)

                if barline_events:
                    forms = sorted({str(evt.get("form", "single")) for evt in barline_events})
                    log(
                        "Extracted MEI barline events: "
                        f"{len(barline_events)} event(s), forms={forms}."
                    )
                if other_events:
                    types = sorted({str(evt.get("event", "")).strip().lower() for evt in other_events})
                    log(
                        "Extracted non-barline MEI events: "
                        f"{len(other_events)} event(s), types={types}."
                    )
                rest_count = int(
                    df_timed["element_type"].astype(str).str.lower().eq("rest").sum()
                ) if ("element_type" in df_timed.columns and not df_timed.empty) else 0
                if rest_count > 0:
                    log(f"Extracted rest timing events: {rest_count} event(s).")

                df_barlines = _barline_events_to_dataframe(
                    barline_events,
                    measure_offsets=measure_offsets,
                )
                df_rests = _mensural_rest_events_to_dataframe(df_timed)
                df_other_events = _other_mei_events_to_dataframe(
                    other_events,
                    df_pitch,
                    measure_offsets=measure_offsets,
                )
                event_frames = [frame for frame in (df_barlines, df_rests, df_other_events) if not frame.empty]
                if not event_frames:
                    df_events = _empty_event_dataframe()
                elif len(event_frames) == 1:
                    df_events = event_frames[0].copy()
                else:
                    df_events = pd.concat(event_frames, ignore_index=True, sort=False)
                if df_events.empty:
                    df_events = _empty_event_dataframe()
                else:
                    for col in _EVENT_DF_COLUMNS:
                        if col not in df_events.columns:
                            df_events[col] = pd.NA
                    df_events = df_events[_EVENT_DF_COLUMNS]
                    df_events = df_events.sort_values("Global Onset", na_position="last").reset_index(drop=True)
                df_events = _align_event_voices_to_pitch_df(
                    df_events,
                    df_pitch,
                    staff_to_part_label=staff_to_part,
                )

                pitch_name = f"{name}_pitch"
                events_name = f"{name}_events"
                plot_obj = None
                if return_plots or backend != "none":
                    plot_obj = draw_piano_roll(
                        df_processed,
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
                    ipy_display(df_processed.head(preview_rows))
                    log(f"Rows: {len(df_processed)}, unique pitches: {df_processed['MIDI'].nunique()}")
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

            finally:
                if (
                    cleanup_remote
                    and file_path is not None
                    and str(file_source).startswith(("http://", "https://"))
                    and os.path.exists(file_path)
                    and not is_cached_download(file_path, remote_cache_dir)
                ):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                if pbar is not None:
                    pbar.update(1)
    finally:
        if pbar is not None:
            pbar.close()

    return results, dfs_by_name, last_df
