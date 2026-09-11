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
from .parser_utils import (
    reanchor_to_measure_offsets,
    reject_unexpected_kwargs,
    resolve_collapse_tied_pitch_events,
)
from .partitura_backend import (
    _EVENT_DF_COLUMNS,
    _align_event_voices_to_pitch_df,
    _apply_note_attachments_to_pitch_df,
    _attach_barline_event_offsets,
    _attach_barline_event_onsets_from_pitch_df,
    _barline_events_to_dataframe,
    _dedupe_mei_events_prefer_anchored,
    _empty_event_dataframe,
    _extract_mei_events,
    _extract_mei_note_attachments,
    _format_voice_label,
    _mei_event_merge_key,
    _mei_initial_meter_span,
    _mei_measure_meter_spans,
    _mei_music_measures,
    _midi_to_pitch_name,
    _normalize_xml_ref,
    _other_mei_events_to_dataframe,
    _source_staff_index_to_part_label_map_from_mei,
    _source_to_name,
)
from .quiet_utils import suppress_native_output
from .verovio_guard import guarded_load_into_verovio_toolkit

try:  # pragma: no cover - optional dependency
    from tqdm.auto import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None

__all__ = ["parse_files_verovio"]

_MIDI_MS_PER_QUARTER_FALLBACK = 500.0


def _local_name(tag: Any) -> str:
    raw = str(tag)
    return raw.rsplit("}", 1)[-1] if "}" in raw else raw


def _xml_id(el: Any) -> Optional[str]:
    if el is None:
        return None
    raw = el.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or el.attrib.get("xml:id")
    return _normalize_xml_ref(raw)


def _first_token(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    tokens = [tok for tok in str(raw).strip().split() if tok]
    return tokens[0] if tokens else None


def _mei_accid_to_suffix(raw: Any) -> str:
    token = None if raw is None else str(raw).strip().lower()
    if not token:
        return ""
    mapping = {
        "s": "#",
        "ns": "#",
        "ss": "##",
        "x": "##",
        "xs": "###",
        "ts": "###",
        "f": "b",
        "nf": "b",
        "ff": "bb",
        "tf": "bbb",
        "n": "",
        "sharp": "#",
        "double-sharp": "##",
        "flat": "b",
        "double-flat": "bb",
        "natural": "",
    }
    return mapping.get(token, "")


def _mei_accid_to_alter(raw: Any) -> Optional[int]:
    token = None if raw is None else str(raw).strip().lower()
    if not token:
        return None
    mapping = {
        "s": 1,
        "ns": 1,
        "ss": 2,
        "x": 2,
        "xs": 3,
        "ts": 3,
        "f": -1,
        "nf": -1,
        "ff": -2,
        "tf": -3,
        "n": 0,
        "sharp": 1,
        "double-sharp": 2,
        "flat": -1,
        "double-flat": -2,
        "natural": 0,
    }
    return mapping.get(token)


def _mei_note_accid_value(note_el: Any) -> Optional[Any]:
    attr_value = note_el.attrib.get("accid.ges") or note_el.attrib.get("accid")
    if attr_value is not None:
        return attr_value
    for child in list(note_el):
        if _local_name(child.tag) != "accid":
            continue
        child_value = child.attrib.get("accid.ges") or child.attrib.get("accid")
        if child_value is not None:
            return child_value
    return None


def _alter_to_suffix(alter: int) -> str:
    if alter > 0:
        return "#" * int(alter)
    if alter < 0:
        return "b" * int(abs(alter))
    return ""


def _extract_mei_note_explicit_alters(root: Any) -> Dict[str, int]:
    note_alters: Dict[str, int] = {}
    for el in root.iter():
        if _local_name(el.tag) != "note":
            continue
        note_id = _xml_id(el)
        explicit_alter = _mei_accid_to_alter(_mei_note_accid_value(el))
        if note_id and explicit_alter is not None:
            note_alters[note_id] = int(explicit_alter)

    return note_alters


def _extract_mei_note_effective_alters(root: Any) -> Dict[int, int]:
    """Resolve common-notation key signatures and measure accidentals.

    Verovio's MIDI accessor does not supply missing gestural accidentals from
    every MEI key-signature encoding. Resolve the source notation independently
    of playback timing. Explicit gestural values win; written accidentals carry
    by staff, pitch letter and octave until the barline, including across layers.
    The result uses element identities so source notes need not have xml:ids.
    """
    import itertools
    import re

    def signature(el):
        declaration = next((child for child in el if _local_name(child.tag) == "keySig"), el)
        raw = declaration.get("sig") if _local_name(declaration.tag) == "keySig" else None
        raw = raw if raw is not None else el.get("keysig", el.get("key.sig"))
        if raw is None:
            return None
        match = re.fullmatch(r"([0-7])([sf]?)", str(raw).strip())
        if not match or (match[1] != "0" and not match[2]):
            raise ValueError(f"Unsupported MEI key signature {raw!r} for implicit pitch resolution.")
        letters = "fcgdaeb" if match[2] == "s" else "beadgcf"
        return {letter: (1 if match[2] == "s" else -1) for letter in letters[:int(match[1])]}

    def written_accidental(note):
        value = note.get("accid")
        if value is None:
            value = next((child.get("accid") for child in note
                          if _local_name(child.tag) == "accid" and child.get("accid") is not None), None)
        return _mei_accid_to_alter(value)

    def layer_events(layer, multiplier=1.0):
        for child in layer:
            tag = _local_name(child.tag)
            if tag in {"note", "chord", "rest", "space", "mRest", "multiRest", "keySig"}:
                yield child, multiplier
            elif tag in {"beam", "tuplet", "bTrem", "fTrem"}:
                scale = _tuplet_multiplier(child) if tag == "tuplet" else 1.0
                yield from layer_events(child, multiplier * scale)

    effective = {}
    global_key, staff_keys = None, {}
    tied_alters = {}
    tie_next = _extract_mei_tie_next_map(root)
    tuplet_spans = _mei_tuplet_span_multipliers(root)
    meter_spans = _mei_measure_meter_spans(root)

    def process_staff(staff, measure):
        staff_n = staff.get("n", "1")
        active_key = staff_keys.get(staff_n, global_key)
        carried = {}
        events = []
        layers = [child for child in staff if _local_name(child.tag) == "layer"] or [staff]
        for layer in layers:
            cursor = 0.0
            for event, scale in layer_events(layer):
                tag = _local_name(event.tag)
                events.append((round(cursor, 12), event))
                if tag == "keySig":
                    continue
                duration = _mei_duration_quarters(event)
                if duration is None and tag == "chord":
                    duration = next((_mei_duration_quarters(note) for note in event
                                     if _local_name(note.tag) == "note" and _mei_duration_quarters(note) is not None), None)
                if duration is None and tag in {"mRest", "multiRest"}:
                    duration = meter_spans.get(id(measure), 4.0)
                cursor += (duration or 0.0) * scale * _timed_element_tuplet_span_multiplier(event, tuplet_spans)
        for _, group in itertools.groupby(sorted(events, key=lambda item: item[0]), key=lambda item: item[0]):
            simultaneous = [event for _, event in group]
            for event in simultaneous:
                if _local_name(event.tag) == "keySig":
                    key = signature(event)
                    if key is not None:
                        active_key = staff_keys[staff_n] = key
                        carried.clear()
            notes = [note for event in simultaneous for note in
                     ([event] if _local_name(event.tag) == "note" else
                      [child for child in event if _local_name(child.tag) == "note"]
                      if _local_name(event.tag) == "chord" else [])]
            updates = {}
            for note in notes:
                accidental = written_accidental(note)
                if accidental is not None:
                    pitch = (note.get("pname"), note.get("oct"))
                    updates.setdefault(pitch, set()).add(accidental)
            # Simultaneous conflicting accidentals are explicit on their notes;
            # they do not establish one unambiguous carry for other voices.
            for pitch, values in updates.items():
                if len(values) == 1:
                    carried[pitch] = next(iter(values))
            for note in notes:
                note_id = _xml_id(note)
                pitch = (note.get("pname"), note.get("oct"))
                alter = _mei_accid_to_alter(_mei_note_accid_value(note))
                if alter is None:
                    alter = tied_alters.get(note_id, carried.get(pitch))
                if alter is None and active_key is not None:
                    alter = active_key.get(str(pitch[0]).lower(), 0)
                if alter is not None:
                    effective[id(note)] = alter
                    if note_id in tie_next:
                        tied_alters[tie_next[note_id]] = alter

    def visit(el):
        nonlocal global_key
        tag = _local_name(el.tag)
        if tag == "score":
            global_key = None
            staff_keys.clear()
            tied_alters.clear()
        if tag == "scoreDef":
            key = signature(el)
            if key is not None:
                global_key = key
                staff_keys.clear()
        elif tag == "staffDef":
            key = signature(el)
            if key is not None:
                staff_keys[el.get("n", "1")] = key
        elif tag == "measure":
            for child in el:
                if _local_name(child.tag) in {"scoreDef", "staffDef"}:
                    visit(child)
                elif _local_name(child.tag) == "staff":
                    process_staff(child, el)
            return
        for child in el:
            visit(child)

    music = [el for el in root.iter() if _local_name(el.tag) == "music"]
    bodies = [el for node in music for el in node.iter() if _local_name(el.tag) == "body"]
    for search_root in bodies or music or [root]:
        visit(search_root)
    return effective


def _mei_written_pitch(note_el: Any, alter: Optional[int] = None) -> Optional[str]:
    pname = note_el.attrib.get("pname")
    octave = note_el.attrib.get("oct")
    if not pname or not octave:
        return None
    if alter is None:
        suffix = _mei_accid_to_suffix(_mei_note_accid_value(note_el))
    else:
        suffix = _alter_to_suffix(int(alter))
    return f"{str(pname).upper()}{suffix}{octave}"


def _midi_from_mei_pitch(note_el: Any, alter: Optional[int] = None) -> Optional[int]:
    pname = note_el.attrib.get("pname") or note_el.attrib.get("pname.ges")
    octave = note_el.attrib.get("oct") or note_el.attrib.get("oct.ges")
    if not pname or not octave:
        return None
    pc_map = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
    letter = str(pname).strip().lower()[:1]
    if letter not in pc_map:
        return None
    if alter is None:
        suffix = _mei_accid_to_suffix(_mei_note_accid_value(note_el))
        alter = suffix.count("#") - suffix.count("b")
    try:
        oct_int = int(float(str(octave).strip()))
    except Exception:
        return None
    return int((oct_int + 1) * 12 + pc_map[letter] + alter)


def _mei_duration_quarters(el: Any) -> Optional[float]:
    if str(getattr(el, "attrib", {}).get("grace", "")).strip():
        return 0.0
    dur_raw = getattr(el, "attrib", {}).get("dur")
    if dur_raw is None:
        return None
    token = str(dur_raw).strip().lower()
    duration_map = {
        "maxima": 32.0,
        "long": 16.0,
        "longa": 16.0,
        "breve": 8.0,
        "1": 4.0,
        "2": 2.0,
        "4": 1.0,
        "8": 0.5,
        "16": 0.25,
        "32": 0.125,
        "64": 0.0625,
        "128": 0.03125,
    }
    base = duration_map.get(token)
    if base is None:
        try:
            denom = float(token)
            if denom <= 0:
                return None
            base = 4.0 / denom
        except Exception:
            return None
    dots_raw = getattr(el, "attrib", {}).get("dots")
    try:
        dots = int(dots_raw) if dots_raw is not None else 0
    except Exception:
        dots = 0
    total = float(base)
    add = float(base)
    for _ in range(max(0, dots)):
        add /= 2.0
        total += add
    return total


def _midi_quarter_scale(root: Any, tk: Any) -> float:
    for el in root.iter():
        if _local_name(el.tag) not in {"note", "chord"}:
            continue
        xid = _xml_id(el)
        if not xid:
            continue
        dur_q = _mei_duration_quarters(el)
        if dur_q is None or dur_q <= 0:
            continue
        try:
            midi = tk.getMIDIValuesForElement(xid)
        except Exception:
            midi = {}
        if not isinstance(midi, dict):
            continue
        try:
            dur_ms = float(midi.get("duration"))
        except Exception:
            continue
        if np.isfinite(dur_ms) and dur_ms > 0:
            return dur_ms / dur_q
    return _MIDI_MS_PER_QUARTER_FALLBACK


def _verovio_timemap_timing(tk: Any) -> Dict[str, Tuple[float, Optional[float]]]:
    try:
        raw = tk.renderToTimemap()
    except Exception:
        raw = None
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            import json

            entries = json.loads(raw)
        except Exception:
            return {}
    else:
        entries = raw
    if not isinstance(entries, list):
        return {}

    onsets: Dict[str, float] = {}
    offsets: Dict[str, float] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        try:
            qstamp = float(entry.get("qstamp"))
        except Exception:
            continue
        if not np.isfinite(qstamp):
            continue
        for key, target in (("on", onsets), ("off", offsets)):
            raw_ids = entry.get(key)
            if not isinstance(raw_ids, list):
                continue
            for raw_id in raw_ids:
                norm = _normalize_xml_ref(raw_id)
                if not norm:
                    continue
                if key == "on":
                    target.setdefault(norm, qstamp)
                else:
                    target[norm] = qstamp

    timing: Dict[str, Tuple[float, Optional[float]]] = {}
    for xid, onset in onsets.items():
        off = offsets.get(xid)
        duration = None
        if off is not None and np.isfinite(off):
            duration = max(0.0, float(off - onset))
        timing[xid] = (float(onset), duration)
    return timing


def _midi_time_duration_quarters(
    tk: Any,
    xml_id: Optional[str],
    *,
    scale: float,
    fallback_duration: Optional[float] = None,
    timemap: Optional[Mapping[str, Tuple[float, Optional[float]]]] = None,
    quiet_native_warnings: bool = False,
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    if not xml_id:
        return None, fallback_duration, None
    norm_id = _normalize_xml_ref(xml_id)
    if timemap is not None and norm_id in timemap:
        onset, duration = timemap[norm_id]
        return onset, duration if duration is not None else fallback_duration, None
    with suppress_native_output(enabled=quiet_native_warnings):
        try:
            midi = tk.getMIDIValuesForElement(xml_id)
        except Exception:
            midi = {}
    if not isinstance(midi, dict):
        midi = {}

    onset_q: Optional[float] = None
    duration_q: Optional[float] = fallback_duration
    midi_pitch: Optional[int] = None
    try:
        onset_raw = midi.get("time")
        if onset_raw is not None:
            onset_q = float(onset_raw) / scale
    except Exception:
        onset_q = None
    try:
        duration_raw = midi.get("duration")
        if duration_raw is not None:
            duration_q = float(duration_raw) / scale
    except Exception:
        pass
    try:
        pitch_raw = midi.get("pitch")
        if pitch_raw is not None:
            midi_pitch = int(pitch_raw)
    except Exception:
        midi_pitch = None
    return onset_q, duration_q, midi_pitch


def _measure_number(measure_el: Any, fallback_index: int) -> int:
    del measure_el
    return int(fallback_index)


def _tuplet_multiplier(el: Any) -> float:
    try:
        num = float(el.attrib.get("num"))
        numbase = float(el.attrib.get("numbase"))
    except Exception:
        return 1.0
    if num <= 0 or numbase <= 0:
        return 1.0
    return float(numbase / num)


def _mei_tuplet_span_multipliers(root: Any) -> Dict[str, float]:
    """Return per-element metric multipliers for MEI ``tupletSpan`` ranges.

    Container ``<tuplet>`` ratios are handled while walking layers.  Elements
    already inside such a container are deliberately excluded here so an
    equivalent ``tupletSpan`` cannot apply the same ratio twice.
    """
    parent_by_element = {child: parent for parent in root.iter() for child in parent}
    element_by_id: Dict[str, Any] = {}
    ordered_ids: List[str] = []
    for el in root.iter():
        if _local_name(el.tag) not in {"note", "chord", "rest", "space"}:
            continue
        xml_id = _xml_id(el)
        if xml_id:
            element_by_id[xml_id] = el
            ordered_ids.append(xml_id)
    position_by_id = {xml_id: idx for idx, xml_id in enumerate(ordered_ids)}

    def _inside_tuplet_container(xml_id: str) -> bool:
        current = parent_by_element.get(element_by_id.get(xml_id))
        while current is not None:
            if _local_name(current.tag) == "tuplet":
                return True
            current = parent_by_element.get(current)
        return False

    multipliers: Dict[str, float] = {}
    for span in root.iter():
        if _local_name(span.tag) != "tupletSpan":
            continue
        multiplier = _tuplet_multiplier(span)
        if multiplier == 1.0:
            continue
        target_ids = {
            normalized
            for raw in str(span.attrib.get("plist", "")).split()
            if (normalized := _normalize_xml_ref(raw))
        }
        start_id = _normalize_xml_ref(span.attrib.get("startid"))
        end_id = _normalize_xml_ref(span.attrib.get("endid"))
        if start_id in position_by_id and end_id in position_by_id:
            start_idx = position_by_id[start_id]
            end_idx = position_by_id[end_id]
            if start_idx <= end_idx:
                target_ids.update(ordered_ids[start_idx : end_idx + 1])
        for target_id in target_ids:
            if target_id not in element_by_id or _inside_tuplet_container(target_id):
                continue
            multipliers[target_id] = multipliers.get(target_id, 1.0) * multiplier
    return multipliers


def _timed_element_tuplet_span_multiplier(
    timed_el: Any,
    multipliers: Mapping[str, float],
) -> float:
    timed_id = _xml_id(timed_el)
    if timed_id in multipliers:
        return float(multipliers[timed_id])
    if _local_name(timed_el.tag) != "chord":
        return 1.0
    child_values = {
        float(multipliers[child_id])
        for child in list(timed_el)
        if _local_name(child.tag) == "note"
        and (child_id := _xml_id(child)) in multipliers
    }
    return child_values.pop() if len(child_values) == 1 else 1.0


def _iter_layer_timed_children(layer_el: Any, multiplier: float = 1.0) -> Iterable[Tuple[Any, float]]:
    for child in list(layer_el):
        tag = _local_name(child.tag)
        if tag in {"note", "rest", "mRest", "multiRest", "space", "chord"}:
            yield child, multiplier
        elif tag in {"beam", "tuplet", "bTrem", "fTrem"}:
            child_multiplier = multiplier * (_tuplet_multiplier(child) if tag == "tuplet" else 1.0)
            yield from _iter_layer_timed_children(child, child_multiplier)


def _extract_mei_tie_next_map(root: Any) -> Dict[str, str]:
    tie_next: Dict[str, str] = {}
    for el in root.iter():
        if _local_name(el.tag) != "tie":
            continue
        start_id = _normalize_xml_ref(el.attrib.get("startid"))
        end_id = _normalize_xml_ref(el.attrib.get("endid"))
        if start_id and end_id:
            tie_next[start_id] = end_id

    # Also support compact note/chord @tie encodings.  Open chains are keyed
    # by staff/layer and written pitch so interleaved voices do not connect.
    parent_by_element = {child: parent for parent in root.iter() for child in parent}
    open_ties: Dict[Tuple[str, str, str, str], str] = {}

    def _ancestor_number(el: Any, tag_name: str) -> str:
        current = parent_by_element.get(el)
        while current is not None:
            if _local_name(current.tag) == tag_name:
                return str(current.attrib.get("n", ""))
            current = parent_by_element.get(current)
        return ""

    for note_el in root.iter():
        if _local_name(note_el.tag) != "note":
            continue
        parent = parent_by_element.get(note_el)
        raw_tie = note_el.attrib.get("tie")
        if raw_tie is None and parent is not None and _local_name(parent.tag) == "chord":
            raw_tie = parent.attrib.get("tie")
        tokens = _mei_tie_tokens(raw_tie)
        if not tokens:
            continue
        note_id = _xml_id(note_el)
        if not note_id:
            continue
        pitch_key = (
            str(note_el.attrib.get("pname") or note_el.attrib.get("pname.ges") or ""),
            str(note_el.attrib.get("oct") or note_el.attrib.get("oct.ges") or ""),
        )
        key = (
            _ancestor_number(note_el, "staff"),
            _ancestor_number(note_el, "layer"),
            pitch_key[0],
            pitch_key[1],
        )
        is_start = bool(tokens & {"i", "initial", "start"})
        is_middle = bool(tokens & {"m", "medial", "middle"})
        is_stop = bool(tokens & {"t", "terminal", "stop"})
        previous_id = open_ties.get(key)
        if (is_middle or is_stop) and previous_id:
            tie_next.setdefault(previous_id, note_id)
        if is_start or is_middle:
            open_ties[key] = note_id
        if is_stop:
            open_ties.pop(key, None)
    return tie_next


def _mei_tie_tokens(raw: Any) -> set[str]:
    value = str(raw or "").strip().lower()
    if not value:
        return set()
    return {tok for tok in value.replace(",", " ").split() if tok}


def _apply_tied_duration_semantics(
    df_pitch: pd.DataFrame,
    tie_next: Mapping[str, str],
    *,
    collapse: bool,
) -> pd.DataFrame:
    """Add logical/performed duration fields and optionally drop tie continuations.

    ``Duration`` always remains the encoded metric duration of the represented
    segment.  ``Logical Duration`` is populated once per logical note: on the
    chain head for ties, and on the row itself for untied notes.  No performed
    duration is inferred from notation attachments.
    """
    if df_pitch.empty or "Duration" not in df_pitch.columns:
        return df_pitch

    out = df_pitch.copy()
    out["Logical Duration"] = pd.to_numeric(out["Duration"], errors="coerce")
    out["Performed Duration"] = pd.Series(pd.NA, index=out.index, dtype="Float64")
    if not tie_next or "xml_id" not in out.columns:
        return out

    ids = out["xml_id"].dropna().astype(str)
    row_by_id = {xml_id: idx for idx, xml_id in zip(ids.index, ids.tolist())}
    duration_by_id: Dict[str, float] = {}
    for xml_id, idx in row_by_id.items():
        try:
            duration = float(out.at[idx, "Duration"])
        except Exception:
            continue
        if np.isfinite(duration):
            duration_by_id[xml_id] = duration

    continuation_ids = set(tie_next.values())
    drop_ids: set[str] = set()
    for continuation_id in continuation_ids:
        if continuation_id in row_by_id:
            out.at[row_by_id[continuation_id], "Logical Duration"] = pd.NA

    for start_id in tie_next:
        if start_id in continuation_ids:
            continue
        if start_id not in row_by_id:
            continue
        total = duration_by_id.get(start_id)
        if total is None:
            continue
        seen = {start_id}
        current = start_id
        while current in tie_next:
            next_id = tie_next[current]
            if next_id in seen:
                break
            seen.add(next_id)
            if next_id in duration_by_id:
                total += duration_by_id[next_id]
                if collapse:
                    drop_ids.add(next_id)
            current = next_id
        out.at[row_by_id[start_id], "Logical Duration"] = float(total)

    if drop_ids:
        out = out[~out["xml_id"].astype(str).isin(drop_ids)].reset_index(drop=True)
    return out


def _verovio_common_mei_dataframes(
    mei_path: str,
    *,
    parse_enharmonic: bool = False,
    include_xml_ids: bool = True,
    include_note_attachments: bool = True,
    collapse_tied_pitch_events: bool = True,
    quiet_native_warnings: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str], List[float], Dict[str, Any], int]:
    try:
        import xml.etree.ElementTree as ET
        import verovio  # type: ignore
    except Exception as exc:
        raise RuntimeError("verovio and XML support are required for the Verovio backend") from exc

    root = ET.parse(mei_path).getroot()
    tie_next = _extract_mei_tie_next_map(root)
    tuplet_span_multipliers = _mei_tuplet_span_multipliers(root)
    note_explicit_alters = _extract_mei_note_explicit_alters(root)
    note_effective_alters = _extract_mei_note_effective_alters(root)
    staff_to_part = _source_staff_index_to_part_label_map_from_mei(root)
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

    # Verovio timemaps expand playback constructs such as repeats, while CAMAT's
    # common-notation rows currently model the encoded source order. Keep the
    # timemap/MIDI accessors as fallback probes, but drive the first milestone
    # from the source MEI layer timeline below.
    scale = _MIDI_MS_PER_QUARTER_FALLBACK
    with suppress_native_output(enabled=quiet_native_warnings):
        timemap = _verovio_timemap_timing(tk)
    rows: List[Dict[str, Any]] = []
    timed_rows: List[Dict[str, Any]] = []
    missing_timed_ids = 0
    measure_onsets_unshifted: Dict[int, List[float]] = {}
    measure_ends_unshifted: Dict[int, List[float]] = {}

    measure_elements = _mei_music_measures(root)
    initial_meter_span = _mei_initial_meter_span(root)
    meter_spans = _mei_measure_meter_spans(
        root,
        measure_elements,
        fallback=initial_meter_span,
    )
    active_measure_index: Dict[int, int] = {}
    for pre_idx, pre_measure_el in enumerate(measure_elements, start=1):
        has_timed_content = False
        for pre_staff in [el for el in pre_measure_el.iter() if _local_name(el.tag) == "staff"]:
            pre_layers = [child for child in list(pre_staff) if _local_name(child.tag) == "layer"] or [pre_staff]
            for pre_layer in pre_layers:
                for _ in _iter_layer_timed_children(pre_layer):
                    has_timed_content = True
                    break
                if has_timed_content:
                    break
            if has_timed_content:
                break
        if has_timed_content:
            active_measure_index[pre_idx] = len(active_measure_index) + 1

    measure_start_unshifted = 0.0
    previous_meter_span: Optional[float] = None
    for measure_index, measure_el in enumerate(measure_elements, start=1):
        if measure_index not in active_measure_index:
            continue
        meter_span = meter_spans.get(id(measure_el), initial_meter_span)
        meter_changed = (
            previous_meter_span is not None
            and abs(float(meter_span) - float(previous_meter_span)) > 1e-6
        )
        measure_num = _measure_number(measure_el, active_measure_index[measure_index])
        layer_end_positions: List[float] = []
        staff_elements = [el for el in list(measure_el) if _local_name(el.tag) == "staff"]
        if not staff_elements:
            staff_elements = [el for el in measure_el.iter() if _local_name(el.tag) == "staff"]
        for staff_idx, staff_el in enumerate(staff_elements, start=1):
            staff_n = _first_token(staff_el.attrib.get("n")) or str(staff_idx)
            part_label = staff_to_part.get(str(staff_n), f"P{staff_n}")
            layer_elements = [child for child in list(staff_el) if _local_name(child.tag) == "layer"]
            if not layer_elements:
                layer_elements = [staff_el]
            for layer_idx, layer_el in enumerate(layer_elements, start=1):
                layer_n = _first_token(getattr(layer_el, "attrib", {}).get("n")) or str(layer_idx)
                voice_label = _format_voice_label(part_label, layer_n)
                cursor = 0.0
                for timed_el, duration_multiplier in _iter_layer_timed_children(layer_el):
                    tag = _local_name(timed_el.tag)
                    timed_xml_id = _xml_id(timed_el)
                    duration_multiplier *= _timed_element_tuplet_span_multiplier(
                        timed_el,
                        tuplet_span_multipliers,
                    )
                    fallback_duration = _mei_duration_quarters(timed_el)
                    if fallback_duration is None and tag == "chord":
                        for note_child in list(timed_el):
                            if _local_name(note_child.tag) == "note":
                                fallback_duration = _mei_duration_quarters(note_child)
                                if fallback_duration is not None:
                                    break
                    if fallback_duration is None and tag in {"mRest", "multiRest"}:
                        fallback_duration = meter_span
                    if fallback_duration is not None:
                        fallback_duration = float(fallback_duration) * float(duration_multiplier)

                    fallback_onset, fallback_duration_from_vrv, midi_pitch = _midi_time_duration_quarters(
                        tk,
                        timed_xml_id,
                        scale=scale,
                        fallback_duration=fallback_duration,
                        timemap=timemap,
                        quiet_native_warnings=quiet_native_warnings,
                    )
                    del fallback_onset
                    duration_q = fallback_duration if fallback_duration is not None else fallback_duration_from_vrv
                    onset_q = float(measure_start_unshifted + cursor)
                    if onset_q is None and timed_xml_id:
                        missing_timed_ids += 1
                    if onset_q is not None:
                        measure_onsets_unshifted.setdefault(measure_num, []).append(float(onset_q))
                        if duration_q is not None:
                            measure_ends_unshifted.setdefault(measure_num, []).append(float(onset_q + duration_q))

                    timed_row: Dict[str, Any] = {
                        "Measure": measure_num,
                        "Local Onset": np.nan,
                        "Global Onset": float(onset_q) if onset_q is not None else np.nan,
                        "Duration": float(duration_q) if duration_q is not None else np.nan,
                        "Voice": voice_label,
                        "xml_id": timed_xml_id if include_xml_ids else pd.NA,
                        "staff_n": staff_n,
                        "layer_n": layer_n,
                        "element_type": tag,
                    }
                    timed_rows.append(timed_row)

                    note_elements: List[Any]
                    if tag == "note":
                        note_elements = [timed_el]
                    elif tag == "chord":
                        note_elements = [ch for ch in list(timed_el) if _local_name(ch.tag) == "note"]
                    else:
                        note_elements = []

                    for note_el in note_elements:
                        note_id = _xml_id(note_el)
                        note_onset = onset_q
                        note_duration = duration_q
                        note_pitch = None
                        effective_alter = note_effective_alters.get(id(note_el), note_explicit_alters.get(note_id))
                        if effective_alter is not None:
                            note_pitch = _midi_from_mei_pitch(note_el, effective_alter)
                        if note_pitch is None:
                            note_pitch = midi_pitch
                        if tag == "chord":
                            child_duration_fallback = _mei_duration_quarters(note_el)
                            if str(timed_el.attrib.get("grace", "")).strip():
                                child_duration_fallback = 0.0
                            if child_duration_fallback is not None:
                                child_duration_fallback = float(child_duration_fallback) * float(duration_multiplier)
                            symbolic_child_duration = (
                                child_duration_fallback
                                if child_duration_fallback is not None
                                else duration_q
                            )
                            child_onset, child_duration, child_pitch = _midi_time_duration_quarters(
                                tk,
                                note_id,
                                scale=scale,
                                fallback_duration=symbolic_child_duration,
                                timemap=timemap,
                                quiet_native_warnings=quiet_native_warnings,
                            )
                            del child_onset
                            # Verovio playback timing can be approximate for
                            # tuplets. Prefer exact source-MEI symbolic values
                            # whenever the chord or note supplies them.
                            if symbolic_child_duration is not None:
                                note_duration = symbolic_child_duration
                            elif child_duration is not None:
                                note_duration = child_duration
                            if note_pitch is None and child_pitch is not None:
                                note_pitch = child_pitch
                        if note_pitch is None:
                            note_pitch = _midi_from_mei_pitch(note_el)
                        if note_onset is None or note_duration is None or note_pitch is None:
                            if note_id:
                                missing_timed_ids += 1
                            continue
                        row: Dict[str, Any] = {
                            "Measure": measure_num,
                            "Local Onset": np.nan,
                            "Global Onset": float(note_onset),
                            "Duration": float(note_duration),
                            "Pitch": _midi_to_pitch_name(int(note_pitch)),
                            "MIDI": int(note_pitch),
                            "Voice": voice_label,
                        }
                        if include_xml_ids:
                            row["xml_id"] = note_id
                        if parse_enharmonic:
                            row["Pitch Enharmonic"] = _mei_written_pitch(
                                note_el,
                                effective_alter,
                            )
                        rows.append(row)
                    if duration_q is not None and np.isfinite(float(duration_q)):
                        cursor += max(0.0, float(duration_q))
                layer_end_positions.append(cursor)
        actual_measure_span = max(layer_end_positions) if layer_end_positions else 0.0
        regular_measure_span = float(meter_span or 0.0)
        # Humdrum-to-MEI conversion uses an unnumbered measure for short
        # transition/anacrusis fragments even when it omits @metcon="false".
        is_irregular = (
            str(measure_el.attrib.get("metcon", "")).strip().lower() == "false"
            or not str(measure_el.attrib.get("n", "")).strip()
        )
        is_initial_pickup = (
            len(active_measure_index) > 0
            and active_measure_index[measure_index] == 1
            and regular_measure_span > 0
            and 0 < actual_measure_span < regular_measure_span
        )
        is_section_boundary = str(measure_el.attrib.get("right", "")).strip().lower() in {
            "dbl",
            "end",
        }
        content_defines_span = (
            is_irregular
            or is_initial_pickup
            or is_section_boundary
            or actual_measure_span > regular_measure_span + 1e-6
            or (
                meter_changed
                and 0 < actual_measure_span < regular_measure_span - 1e-6
            )
        )
        if content_defines_span and actual_measure_span > 0:
            measure_span = actual_measure_span
        else:
            measure_span = regular_measure_span or actual_measure_span
        if (not np.isfinite(measure_span)) or measure_span <= 0:
            measure_span = actual_measure_span
        measure_start_unshifted += max(0.0, float(measure_span))
        previous_meter_span = meter_span

    first_span = 0.0
    if measure_onsets_unshifted:
        first_idx = min(measure_onsets_unshifted)
        starts = measure_onsets_unshifted.get(first_idx, [])
        ends = measure_ends_unshifted.get(first_idx, [])
        if starts and ends:
            first_span = max(0.0, float(max(ends) - min(starts)))
    first_measure_el = next(
        (
            measure_el
            for idx, measure_el in enumerate(measure_elements, start=1)
            if active_measure_index.get(idx) == 1
        ),
        None,
    )
    first_meter_span = (
        meter_spans.get(id(first_measure_el), initial_meter_span)
        if first_measure_el is not None
        else initial_meter_span
    )
    pickup_shift = (
        -first_span
        if first_meter_span and first_span and first_span < (first_meter_span - 1e-6)
        else 0.0
    )

    measure_offsets: List[float] = []
    measure_start_by_index: Dict[int, float] = {}
    for idx in sorted(measure_onsets_unshifted):
        starts = measure_onsets_unshifted[idx]
        if not starts:
            continue
        start = float(min(starts) + pickup_shift)
        measure_start_by_index[idx] = start
        measure_offsets.append(start)

    def _local_for(measure_number_value: Any, global_onset: Any) -> float:
        try:
            onset_f = float(global_onset)
        except Exception:
            return np.nan
        if not np.isfinite(onset_f):
            return np.nan
        try:
            measure_idx = int(measure_number_value)
        except Exception:
            measure_idx = 0
        start = measure_start_by_index.get(measure_idx)
        if start is None:
            return np.nan
        local = onset_f - start
        if (
            measure_idx == min(measure_start_by_index.keys(), default=measure_idx)
            and pickup_shift < 0
            and first_meter_span
        ):
            return float(max(0.0, first_meter_span + local - first_span))
        return float(local)

    df_pitch = pd.DataFrame(rows)
    timed_df = pd.DataFrame(timed_rows)
    for df in (df_pitch, timed_df):
        if df.empty:
            continue
        df["Global Onset"] = df["Global Onset"].astype(float) + pickup_shift
        df["Local Onset"] = [
            _local_for(measure, onset)
            for measure, onset in zip(df["Measure"].tolist(), df["Global Onset"].tolist())
        ]

    expected = ["Measure", "Local Onset", "Global Onset", "Duration", "Pitch", "MIDI", "Voice"]
    if include_xml_ids:
        expected.insert(expected.index("Voice") + 1, "xml_id")
    if parse_enharmonic:
        expected.insert(5, "Pitch Enharmonic")
    for col in expected:
        if col not in df_pitch.columns:
            df_pitch[col] = pd.NA
    if not df_pitch.empty:
        df_pitch = df_pitch.sort_values(["Global Onset", "MIDI"], kind="stable").reset_index(drop=True)
        if include_xml_ids and "xml_id" in df_pitch.columns:
            duplicate_id = df_pitch["xml_id"].notna() & df_pitch["xml_id"].duplicated(keep="first")
            df_pitch = df_pitch[~duplicate_id].reset_index(drop=True)
    df_pitch = df_pitch[expected]

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
        if col not in timed_df.columns:
            timed_df[col] = pd.NA
    if not timed_df.empty:
        timed_df = timed_df.sort_values(["Global Onset", "Duration"], na_position="last").reset_index(drop=True)
    timed_df = timed_df[timed_expected]

    if include_note_attachments:
        df_pitch = _apply_note_attachments_to_pitch_df(
            df_pitch,
            _extract_mei_note_attachments(mei_path),
        )
    df_pitch = _apply_tied_duration_semantics(
        df_pitch,
        tie_next,
        collapse=collapse_tied_pitch_events,
    )

    return df_pitch, timed_df, staff_to_part, measure_offsets, load_info, missing_timed_ids


def _rest_events_to_dataframe(df_timed: pd.DataFrame) -> pd.DataFrame:
    if df_timed.empty or "element_type" not in df_timed.columns:
        return _empty_event_dataframe()
    rest_rows = df_timed[df_timed["element_type"].astype(str).str.lower().isin({"rest", "mrest", "multirest"})]
    if rest_rows.empty:
        return _empty_event_dataframe()
    rows: List[Dict[str, Any]] = []
    for _, row in rest_rows.iterrows():
        rows.append(
            {
                "type": "rest",
                "subtype": str(row.get("element_type", "rest")).lower(),
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
                "measure_type": pd.NA,
                "measure_metcon": pd.NA,
                "measure_join": pd.NA,
                "measure_n": pd.NA,
                "extra": pd.NA,
            }
        )
    df_events = pd.DataFrame(rows)
    for col in _EVENT_DF_COLUMNS:
        if col not in df_events.columns:
            df_events[col] = pd.NA
    return df_events[_EVENT_DF_COLUMNS].sort_values("Global Onset", na_position="last").reset_index(drop=True)


def parse_files_verovio(
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
    include_note_attachments: bool = True,
    normalize_mensural_durations: bool = True,
    inject_missing_meter_signature: bool = True,
    default_meter_count: int = 4,
    default_meter_unit: int = 4,
    try_verovio_mei_conversion: bool = True,
    prefer_verovio_for_mensural: bool = True,
    verovio_mensural_to_cmn: bool = True,
    verovio_duration_equivalence: Optional[float] = None,
    verovio_mensural_score_up: bool = False,
    use_verovio_mensural_timing: bool = False,
    allow_music21_fallback: bool = True,
    dedupe_weaker_text_events: bool = True,
    quiet_native_warnings: bool = False,
    use_remote_cache: bool = True,
    remote_cache_dir: Optional[str] = None,
    n_jobs: int = 1,
    **deprecated_kwargs: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Common-notation MEI parser backed by Verovio and source MEI.

    This backend intentionally supports MEI sources only. Convert other score
    formats to MEI before parsing. Partitura-like kwargs are accepted for
    notebook compatibility; options specific to other backends are ignored.
    """
    collapse_tied_pitch_events = resolve_collapse_tied_pitch_events(
        collapse_tied_pitch_events,
        deprecated_kwargs,
    )
    reject_unexpected_kwargs(deprecated_kwargs, "parse_files_verovio")

    del (
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

    sources = list(file_sources)
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
                log(f"Processing (verovio): {short_name} -> {name}")
                if pbar is not None:
                    pbar.set_postfix_str(short_name)

                file_path = get_file_path(
                    file_source,
                    use_cache=bool(use_remote_cache),
                    cache_dir=remote_cache_dir,
                )
                if Path(file_path).suffix.lower() != ".mei":
                    raise ValueError(
                        "parse_files_verovio currently supports common-notation MEI sources only"
                    )

                df_raw, df_timed_raw, staff_to_part, measure_offsets, load_info, missing_timed_ids = (
                    _verovio_common_mei_dataframes(
                        file_path,
                        parse_enharmonic=parse_enharmonic,
                        include_xml_ids=bool(include_xml_ids),
                        include_note_attachments=bool(include_note_attachments),
                        collapse_tied_pitch_events=collapse_tied_pitch_events,
                        quiet_native_warnings=quiet_native_warnings,
                    )
                )
                if load_info.get("sanitized") and load_info.get("message"):
                    log(f"Warning: {load_info['message']}")
                if missing_timed_ids:
                    log(f"Warning: {missing_timed_ids} MEI timed element id(s) had no Verovio timing.")

                if align_accident_schema:
                    source_col = "Pitch Enharmonic" if parse_enharmonic else "Pitch"
                    if source_col in df_raw.columns:
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
                            log(f"Warning: {excess_clamped} note(s) exceeded +/-5 accidentals; clamped to 5.")

                df_pitch = filter_and_adjust_durations(
                    df_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values(["Global Onset", "MIDI"], kind="stable").reset_index(drop=True)
                df_pitch = reanchor_to_measure_offsets(df_pitch, measure_offsets)
                df_timed = filter_and_adjust_durations(
                    df_timed_raw,
                    filter_zero_duration=filter_zero_duration,
                    adjust_fractional_duration=adjust_fractional_duration,
                ).sort_values("Global Onset", na_position="last").reset_index(drop=True)
                df_timed = reanchor_to_measure_offsets(df_timed, measure_offsets)
                if include_xml_ids and "xml_id" not in df_pitch.columns:
                    df_pitch["xml_id"] = pd.NA

                extracted_mei_events: List[Dict[str, Any]] = []
                seen_event_keys: set[Tuple[str, ...]] = set()
                for raw_event in _extract_mei_events(file_path):
                    event = dict(raw_event)
                    key = _mei_event_merge_key(event)
                    if key in seen_event_keys:
                        continue
                    seen_event_keys.add(key)
                    extracted_mei_events.append(event)

                if dedupe_weaker_text_events:
                    extracted_mei_events, weak_dupe_count = _dedupe_mei_events_prefer_anchored(
                        extracted_mei_events
                    )
                    if weak_dupe_count > 0:
                        log(
                            "Dropped weaker duplicate MEI text events: "
                            f"{weak_dupe_count} row(s) without usable anchors."
                        )

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
                    log(f"Extracted MEI barline events: {len(barline_events)} event(s), forms={forms}.")
                if other_events:
                    types = sorted({str(evt.get("event", "")).strip().lower() for evt in other_events})
                    log(f"Extracted non-barline MEI events: {len(other_events)} event(s), types={types}.")

                df_barlines = _barline_events_to_dataframe(
                    barline_events,
                    measure_offsets=measure_offsets,
                )
                df_rests = _rest_events_to_dataframe(df_timed)
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
                    log(f"Rows: {len(df_pitch)}, unique pitches: {df_pitch['MIDI'].nunique()}")
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
                    "parser_backend": "verovio",
                    "experimental": False,
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
