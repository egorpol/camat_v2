"""Resolve MEI sounding alterations and regenerate gestural accidentals.

This module intentionally uses only the standard library, including when loaded
as a sibling by the standalone consistency checker.
"""
from __future__ import annotations

import itertools
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = ["AccidGesReport", "resolve_mei_note_alters", "regenerate_accid_ges_text"]

XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ALTER_TO_GES = {1: "s", -1: "f", 2: "ss", -2: "ff", 3: "ts", -3: "tf"}


def _normalize_xml_ref(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    try:
        value = str(raw).strip()
    except Exception:
        return None
    if not value:
        return None
    return value.lstrip("#")


def _local_name(tag: Any) -> str:
    raw = str(tag)
    return raw.rsplit("}", 1)[-1] if "}" in raw else raw


def _xml_id(el: Any) -> Optional[str]:
    if el is None:
        return None
    raw = el.attrib.get("{http://www.w3.org/XML/1998/namespace}id") or el.attrib.get("xml:id")
    return _normalize_xml_ref(raw)


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


def _first_staff(value: Any, fallback: str) -> str:
    """Return the first number of an ``@staff`` value, which may list several."""
    tokens = str(value or "").split()
    return tokens[0] if tokens else fallback


def _extract_mei_note_effective_alters(root: Any) -> Dict[int, int]:
    """Resolve by printed staff, letter and octave, with zero-time grace order.

    Explicit gestural values win. Written accidentals carry to the barline,
    across layers and encoding staves; ties carry only to their destination.
    Element identities let callers also resolve notes without ``xml:id``.
    """
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

    def layer_events(layer, multiplier=1.0, grace=False, staff=None):
        for child in layer:
            tag = _local_name(child.tag)
            if tag in {"note", "chord", "rest", "space", "mRest", "multiRest", "keySig"}:
                yield child, multiplier, grace or child.get("grace") is not None, child.get("staff") or staff
            elif tag in {"beam", "tuplet", "bTrem", "fTrem", "graceGrp"}:
                scale = _tuplet_multiplier(child) if tag == "tuplet" else 1.0
                yield from layer_events(child, multiplier * scale, grace or tag == "graceGrp", child.get("staff") or staff)

    effective = {}
    global_key, staff_keys = None, {}
    tied_alters = {}
    tie_next = _extract_mei_tie_next_map(root)
    tuplet_spans = _mei_tuplet_span_multipliers(root)

    def process_measure(measure):
        events = []
        order = itertools.count()
        for staff in (child for child in measure if _local_name(child.tag) == "staff"):
            staff_n = staff.get("n", "1")
            layers = [child for child in staff if _local_name(child.tag) == "layer"] or [staff]
            for layer in layers:
                cursor = 0.0
                grace_order = 0
                for event, scale, grace, display in layer_events(layer):
                    tag = _local_name(event.tag)
                    if tag == "keySig":
                        events.append((round(cursor, 12), -1, next(order), event, staff_n, staff_n))
                        continue
                    display = _first_staff(display, staff_n)
                    # Graces have ordered slots before the simultaneous main
                    # notes. Their written duration never advances the cursor.
                    if grace:
                        events.append((round(cursor, 12), grace_order, next(order), event, staff_n, display))
                        grace_order += 1
                        continue
                    grace_order = 0
                    events.append((round(cursor, 12), float("inf"), next(order), event, staff_n, display))
                    if tag in {"mRest", "multiRest"}:
                        # Fills the layer: a keySig after it, for the next bar,
                        # still counts, after every other layer's notes.
                        cursor = float("inf")
                        continue
                    duration = _mei_duration_quarters(event)
                    if duration is None and tag == "chord":
                        duration = next((_mei_duration_quarters(note) for note in event
                                         if _local_name(note.tag) == "note" and _mei_duration_quarters(note) is not None), None)
                    cursor += (duration or 0.0) * scale * _timed_element_tuplet_span_multiplier(event, tuplet_spans)
        carried = {}
        for _, group in itertools.groupby(sorted(events, key=lambda item: item[:3]), key=lambda item: item[:2]):
            simultaneous = list(group)
            for _, _, _, event, staff_n, _ in simultaneous:
                if _local_name(event.tag) == "keySig":
                    key = signature(event)
                    if key is not None:
                        staff_keys[staff_n] = key
                        carried.pop(staff_n, None)
            notes = []
            for _, _, _, event, _, display in simultaneous:
                tag = _local_name(event.tag)
                if tag == "note":
                    notes.append((event, display))
                elif tag == "chord":
                    notes.extend((note, _first_staff(note.get("staff"), display))
                                 for note in event if _local_name(note.tag) == "note")
            updates = {}
            for note, display in notes:
                accidental = written_accidental(note)
                if accidental is not None:
                    pitch = (display, note.get("pname"), note.get("oct"))
                    updates.setdefault(pitch, set()).add(accidental)
            # Conflicting simultaneous accidentals establish no new carry.
            for (display, pname, octave), values in updates.items():
                if len(values) == 1:
                    carried.setdefault(display, {})[(pname, octave)] = next(iter(values))
            for note, display in notes:
                note_id = _xml_id(note)
                pitch = (note.get("pname"), note.get("oct"))
                alter = _mei_accid_to_alter(_mei_note_accid_value(note))
                if alter is None:
                    alter = tied_alters.get(note_id, carried.get(display, {}).get(pitch))
                key = staff_keys.get(display, global_key)
                if alter is None and key is not None:
                    alter = key.get(str(pitch[0]).lower(), 0)
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
            process_measure(el)
            return
        for child in el:
            visit(child)

    music = [el for el in root.iter() if _local_name(el.tag) == "music"]
    bodies = [el for node in music for el in node.iter() if _local_name(el.tag) == "body"]
    for search_root in bodies or music or [root]:
        visit(search_root)
    return effective


def _without_gestural_accidentals(root: ET.Element) -> None:
    for element in root.iter():
        element.attrib.pop("accid.ges", None)


def resolve_mei_note_alters(text: str, *, honor_accid_ges: bool = False) -> dict[str, int]:
    """Return sounding alterations keyed by ``xml:id``; omit unresolved notes.

    By default all ``accid.ges`` attributes are ignored before resolving keys,
    written accidentals and ties. Set ``honor_accid_ges`` to retain their explicit
    overrides. Notes without IDs are omitted. Unsupported keys raise ValueError.
    """
    root = ET.fromstring(text)
    if not honor_accid_ges:
        _without_gestural_accidentals(root)
    alters = _extract_mei_note_effective_alters(root)
    return {note_id: alters[id(note)] for note in root.iter()
            if _local_name(note.tag) == "note" and (note_id := _xml_id(note)) and id(note) in alters}


@dataclass
class AccidGesReport:
    """Attribute counts and per-note rows from gestural regeneration.

    ``kept``, ``added`` and ``removed`` count attributes on resolved notes.
    ``unresolved`` rows describe notes left untouched. ``changes`` has one row
    per changed note, including its zero-based document ``note_index``, ``id``,
    resolved ``alter``, and ``actual``/``expected`` location lists. Each location
    records ``location`` (note/child), ``child_index``, ``child_id`` and ``value``.
    """
    kept: int = 0
    added: int = 0
    removed: int = 0
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _StartTag:
    start: int
    end: int
    ges_span: tuple[int, int] | None
    insert_at: int


# Attribute tokens are matched only inside a lexically identified start tag.
_ATTRIBUTE = re.compile(r'''\s+([^\s=/>]+)\s*=\s*(?:"[^"]*"|'[^']*')''')
_NAME = re.compile(r"[^\s/>]+")


def _scan_note_tags(text: str) -> list[list[_StartTag]]:
    """Scan once, skipping XML literals and respecting quoted delimiters.

    Each entry holds a note start tag followed by its direct accid children.
    DTD entity expansion is deliberately not performed: the parsed tree is
    checked against this inventory before any replacement is returned.
    """
    notes: list[list[_StartTag]] = []
    stack: list[tuple[str, list[_StartTag] | None]] = []
    pos = 0
    while True:
        start = text.find("<", pos)
        if start < 0:
            break
        ending = None
        for opener, closer in (("<!--", "-->"), ("<![CDATA[", "]]>"), ("<?", "?>")):
            if text.startswith(opener, start):
                end = text.find(closer, start + len(opener))
                if end < 0:
                    raise ValueError("Unterminated XML literal during accidental scan.")
                pos = end + len(closer)
                ending = pos
                break
        if ending is not None:
            continue
        # This also skips complete DOCTYPE internal subsets, including quoted
        # entity markup and comments containing square brackets.
        quote = None
        depth = 0
        end = start + 1
        while end < len(text):
            char = text[end]
            if quote:
                if char == quote:
                    quote = None
            elif text.startswith("<!--", end):
                comment_end = text.find("-->", end + 4)
                if comment_end < 0:
                    raise ValueError("Unterminated DTD comment.")
                end = comment_end + 3
                continue
            elif char in "\"'":
                quote = char
            elif char == "[" and text.startswith("<!", start):
                depth += 1
            elif char == "]" and depth:
                depth -= 1
            elif char == ">" and depth == 0:
                break
            end += 1
        if end == len(text):
            raise ValueError("Unterminated XML tag during accidental scan.")
        pos = end + 1
        if text.startswith("<!", start):
            continue
        if text.startswith("</", start):
            if stack:
                stack.pop()
            continue
        name = _NAME.match(text, start + 1)
        if name is None:
            raise ValueError("Missing XML tag name during accidental scan.")
        local = name[0].rsplit(":", 1)[-1]
        entry = None
        if local == "note" or (local == "accid" and stack and stack[-1][1] is not None):
            attrs = list(_ATTRIBUTE.finditer(text, name.end(), end))
            span = next(((m.start(), m.end()) for m in attrs if m[1] == "accid.ges"), None)
            tag = _StartTag(start, pos, span, attrs[-1].end() if attrs else name.end())
            if local == "note":
                entry = [tag]
                notes.append(entry)
            else:
                stack[-1][1].append(tag)
        if text[end - 1] != "/":
            stack.append((local, entry))
    return notes


def regenerate_accid_ges_text(text: str) -> tuple[str, AccidGesReport]:
    """Regenerate note/accid ``accid.ges`` attributes, preserving all other text.

    Resolve with all gestural overrides removed so stale tie predecessors cannot
    affect successors. Written accidentals and naturals receive no value. Keep
    a correct value on an accid child; otherwise use the first child, or the note
    if it has none. Unresolved notes remain untouched and are reported.

    Raises ValueError on unsupported keys or a scanner/tree inventory mismatch.
    The input is a string; UTF-8 byte callers should decode/encode directly to
    preserve BOMs and line endings.
    """
    root = ET.fromstring(text)
    notes = [el for el in root.iter() if _local_name(el.tag) == "note"]
    tags = _scan_note_tags(text)
    if len(notes) != len(tags):
        raise ValueError(f"Accidental scan/parse note count differs: {len(tags)} scanned, {len(notes)} parsed.")
    locations = []
    written = []
    for note, note_tags in zip(notes, tags):
        children = [child for child in note if _local_name(child.tag) == "accid"]
        elements = [note, *children]
        if len(elements) != len(note_tags) or any(
            (el.get("accid.ges") is not None) != (tag.ges_span is not None)
            for el, tag in zip(elements, note_tags)
        ):
            raise ValueError("Accidental scan/parse child or attribute inventory differs.")
        locations.append([
            {"location": "note" if i == 0 else "child", "child_index": None if i == 0 else i - 1,
             "child_id": None if i == 0 else el.get(XML_ID), "value": el.get("accid.ges")}
            for i, el in enumerate(elements)
        ])
        written.append(any(el.get("accid") is not None for el in elements))
    _without_gestural_accidentals(root)
    alters = _extract_mei_note_effective_alters(root)
    report = AccidGesReport()
    edits = []
    for index, (note, note_tags, locs, has_written) in enumerate(zip(notes, tags, locations, written)):
        actual = [loc for loc in locs if loc["value"] is not None]
        alter = alters.get(id(note))
        row = {"note_index": index, "id": note.get(XML_ID), "alter": alter, "actual": actual}
        if alter is None:
            report.unresolved.append(row)
            continue
        target = None if has_written else ALTER_TO_GES.get(alter)
        keep_index = None
        target_index = None
        if target is not None:
            # Prefer an existing correct child, even when it is not the first.
            keep_index = next((i for i in range(1, len(locs)) if locs[i]["value"] == target), None)
            target_index = keep_index if keep_index is not None else (1 if len(locs) > 1 else 0)
            if locs[target_index]["value"] == target:
                keep_index = target_index
        expected = [{**locs[target_index], "value": target}] if target_index is not None else []
        row["expected"] = expected
        if actual != expected:
            report.changes.append(row)
        for i, tag in enumerate(note_tags):
            if i == keep_index:
                report.kept += 1
                continue
            if tag.ges_span is not None:
                edits.append((*tag.ges_span, ""))
                report.removed += 1
            if i == target_index:
                # When replacing the last attribute, insert before its removed
                # span, keeping the whitespace preceding the closing delimiter.
                insert_at = tag.insert_at
                if tag.ges_span is not None and tag.ges_span[1] == insert_at:
                    insert_at = tag.ges_span[0]
                edits.append((insert_at, insert_at, f' accid.ges="{target}"'))
                report.added += 1
    # Build once in source order; no per-note regexes or repeated file copying.
    chunks = []
    cursor = 0
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1])):
        chunks.extend((text[cursor:start], replacement))
        cursor = end
    chunks.append(text[cursor:])
    return "".join(chunks), report
