from __future__ import annotations

import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

MEI_NS = "http://www.music-encoding.org/ns/mei"

__all__ = [
    "TimelineParseResult",
    "humdrum_rap_to_timeline",
    "parse_rap_humdrum_file",
    "parse_rap_humdrum_source",
    "parse_files_timeline",
    "timeline_to_mei",
    "save_timeline_mei",
    "load_timeline_mei_with_verovio",
    "find_duplicate_mei_xml_ids",
]


@dataclass
class TimelineParseResult:
    """Container for parsed timeline data and source metadata."""

    df_timeline: pd.DataFrame
    metadata: Dict[str, str]


_KNOWN_TIMELINE_COLUMNS = [
    "source",
    "row_number",
    "event_index",
    "section",
    "section_role",
    "section_index",
    "measure",
    "measure_index",
    "local_onset",
    "global_onset",
    "duration",
    "duration_token",
    "duration_base",
    "duration_dots",
    "duration_modifier",
    "meter",
    "tempo_bpm",
    "lyric",
    "ipa",
    "stress",
    "tone",
    "break",
    "rhyme",
    "hype",
    "is_rest",
    "wordpos",
    "word_id",
    "xml_id_event",
    "xml_id_note",
    "xml_id_syl",
    "xml_id_annot",
]


def _read_source(source: str, *, encoding: str = "utf-8") -> str:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source) as response:  # noqa: S310 - user-provided corpus URL
            return response.read().decode(encoding, errors="ignore")
    return Path(source).read_text(encoding=encoding, errors="ignore")


def _source_name(source: Optional[str]) -> str:
    if not source:
        return "timeline"
    base = os.path.basename(str(source).split("?", 1)[0].split("#", 1)[0])
    stem = os.path.splitext(base)[0]
    return stem or "timeline"


def _slug(value: Any, *, fallback: str = "x") -> str:
    text = str(value if value is not None else "").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    text = text.strip("-._")
    if not text:
        text = fallback
    if not re.match(r"[a-zA-Z_]", text):
        text = f"{fallback}-{text}"
    return text


def _is_null_token(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() in {"", "."}


def _clean_token(value: Any) -> Optional[str]:
    if _is_null_token(value):
        return None
    return str(value).strip()


def _section_role(section: Any) -> Optional[str]:
    if _is_null_token(section):
        return None
    text = str(section).strip().lower()
    if any(marker in text for marker in ("chorus", "refrain")):
        return "chorus"
    if "hook" in text:
        return "hook"
    if "verse" in text:
        return "verse"
    if "bridge" in text:
        return "bridge"
    if "intro" in text:
        return "intro"
    if "outro" in text:
        return "outro"
    return None


def _unique_spine_names(headers: Sequence[str]) -> List[str]:
    names: List[str] = []
    counts: Dict[str, int] = {}
    for header in headers:
        name = str(header).strip()
        if name.startswith("**"):
            name = name[2:]
        name = _slug(name.replace("-", "_"), fallback="spine").replace("-", "_")
        count = counts.get(name, 0) + 1
        counts[name] = count
        names.append(name if count == 1 else f"{name}_{count}")
    return names


def _parse_reference_record(line: str) -> Optional[Tuple[str, str]]:
    if not line.startswith("!!!") or ":" not in line:
        return None
    key, value = line[3:].split(":", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    return key, value


def _parse_meter_token(token: str) -> Optional[str]:
    match = re.match(r"^\*M(\d+)/(\d+)", token.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def _parse_tempo_token(token: str) -> Optional[float]:
    match = re.match(r"^\*MM(\d+(?:\.\d+)?)", token.strip())
    if not match:
        return None
    return float(match.group(1))


def _duration_from_recip(token: Any) -> Tuple[Optional[float], Optional[str], int, Optional[str]]:
    """Parse a Humdrum reciprocal duration into quarter-note units.

    This intentionally keeps uncommon modifiers such as ``%13`` as metadata.
    The base reciprocal value still provides a practical display duration for
    the experimental MEI layer.
    """
    if _is_null_token(token):
        return None, None, 0, None
    text = str(token).strip()
    match = re.match(r"^(\d+|0)(\.*)(.*)$", text)
    if not match:
        return None, None, 0, text

    base = match.group(1)
    dots = len(match.group(2) or "")
    modifier = (match.group(3) or "").strip() or None
    if base == "0":
        duration = 0.0
    else:
        duration = 4.0 / float(base)
        dot_add = 0.0
        for idx in range(dots):
            dot_add += duration / (2 ** (idx + 1))
        duration += dot_add
    return duration, base, dots, modifier


def _duration_to_mei_attrs(row: pd.Series) -> str:
    base = row.get("duration_base")
    if _is_null_token(base):
        base = "4"
    attrs = [f'dur="{escape(str(base), quote=True)}"']
    dots = row.get("duration_dots")
    try:
        dot_count = int(dots)
    except Exception:
        dot_count = 0
    if dot_count > 0:
        attrs.append(f'dots="{dot_count}"')
    return " ".join(attrs)


def _note_position_attrs(
    *,
    pitch_name: str,
    octave: int,
    staff_lines: int,
    show_clef: bool,
    note_position: str,
    note_loc: int,
) -> str:
    position = note_position.lower()
    if position == "auto":
        position = "staff" if staff_lines == 1 and not show_clef else "pitch"
    if position == "staff":
        return f'loc="{int(note_loc)}"'
    if position == "pitch":
        return f'pname="{escape(pitch_name, quote=True)}" oct="{int(octave)}"'
    raise ValueError("note_position must be 'auto', 'staff', or 'pitch'.")


def _lyric_wordpos(lyric: Optional[str]) -> Optional[str]:
    if lyric is None:
        return None
    text = lyric.strip()
    if not text:
        return None
    starts = text.startswith("-")
    ends = text.endswith("-")
    if starts and ends:
        return "m"
    if starts:
        return "t"
    if ends:
        return "i"
    return "s"


def _measure_id_piece(measure: Any, measure_index: int) -> str:
    raw = str(measure if measure is not None else "").strip()
    match = re.search(r"-?\d+", raw)
    if match:
        value = int(match.group(0))
    else:
        value = int(measure_index)
    if value < 0:
        return f"neg{abs(value):03d}"
    return f"{value:03d}"


def _build_event_ids(
    section: Optional[str],
    section_index: int,
    measure: Any,
    measure_index: int,
    event_index: int,
    is_rest: bool,
) -> Dict[str, str]:
    section_slug = _slug(section or f"section-{section_index}", fallback="sec")
    measure_slug = _measure_id_piece(measure, measure_index)
    event_slug = f"{event_index:04d}"
    prefix = f"{section_slug}-m{measure_slug}-s{event_slug}"
    return {
        "xml_id_event": f"evt-{prefix}",
        "xml_id_note": pd.NA if is_rest else f"n-{prefix}",
        "xml_id_syl": pd.NA if is_rest else f"syl-{prefix}",
        "xml_id_annot": f"ann-{prefix}",
    }


def humdrum_rap_to_timeline(
    text: str,
    *,
    source: Optional[str] = None,
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Parse MCFlow-style rap Humdrum into a syllable/token timeline.

    The parser is intentionally spine-driven rather than ``**kern``-driven. It
    expects a rhythmic ``**recip`` spine and preserves parallel rap annotation
    spines such as ``**stress``, ``**break``, ``**rhyme``, ``**ipa``,
    ``**lyrics`` and ``**hype``.
    """
    metadata: Dict[str, str] = {}
    spine_names: List[str] = []
    rows: List[Dict[str, Any]] = []

    section: Optional[str] = None
    section_index = 0
    measure: Optional[str] = None
    measure_index = -1
    local_onset = 0.0
    global_onset = 0.0
    meter: Optional[str] = None
    tempo_bpm: Optional[float] = None
    event_index = 0
    word_index = 0
    active_word_id: Optional[str] = None

    for row_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue

        reference = _parse_reference_record(line)
        if reference is not None:
            key, value = reference
            metadata[key] = value
            continue

        cells = line.split("\t")
        if not spine_names:
            if all(cell.strip().startswith("**") for cell in cells):
                spine_names = _unique_spine_names(cells)
            continue

        if all(cell.strip() == "*-" for cell in cells):
            spine_names = []
            continue

        first = cells[0].strip() if cells else ""
        if first.startswith("*>"):
            section = first[2:].strip() or f"Section{section_index + 1}"
            section_index += 1
            measure = None
            measure_index = -1
            local_onset = 0.0
            active_word_id = None
            continue

        if first.startswith("="):
            measure = first.lstrip("=").strip() or str(measure_index + 1)
            measure = measure.split()[0]
            measure_index += 1
            local_onset = 0.0
            active_word_id = None
            continue

        if first.startswith("*"):
            for token in cells:
                parsed_meter = _parse_meter_token(token)
                if parsed_meter is not None:
                    meter = parsed_meter
                parsed_tempo = _parse_tempo_token(token)
                if parsed_tempo is not None:
                    tempo_bpm = parsed_tempo
            continue

        values = dict(zip(spine_names, cells))
        duration, duration_base, duration_dots, duration_modifier = _duration_from_recip(
            values.get("recip")
        )
        if duration is None:
            continue

        lyric = _clean_token(values.get("lyrics"))
        ipa = _clean_token(values.get("ipa"))
        is_rest = bool((lyric is None and ipa in {None, "R"}) or ipa == "R")
        wordpos = None if is_rest else _lyric_wordpos(lyric)
        if not is_rest:
            if active_word_id is None or wordpos in {"i", "s", None}:
                word_index += 1
                active_word_id = f"w-{_slug(section or 'section', fallback='sec')}-{word_index:04d}"
            word_id = active_word_id
            if wordpos in {"t", "s"}:
                active_word_id = None
        else:
            word_id = None

        event_index += 1
        ids = _build_event_ids(
            section,
            section_index,
            measure,
            measure_index,
            event_index,
            is_rest,
        )
        row: Dict[str, Any] = {
            "source": source,
            "row_number": row_number,
            "event_index": event_index,
            "section": section,
            "section_role": _section_role(section),
            "section_index": section_index,
            "measure": measure,
            "measure_index": measure_index,
            "local_onset": local_onset,
            "global_onset": global_onset,
            "duration": duration,
            "duration_token": _clean_token(values.get("recip")),
            "duration_base": duration_base,
            "duration_dots": duration_dots,
            "duration_modifier": duration_modifier,
            "meter": meter,
            "tempo_bpm": tempo_bpm,
            "lyric": lyric,
            "ipa": ipa,
            "stress": _clean_token(values.get("stress")),
            "tone": _clean_token(values.get("tone")),
            "break": _clean_token(values.get("break")),
            "rhyme": _clean_token(values.get("rhyme")),
            "hype": _clean_token(values.get("hype")),
            "is_rest": is_rest,
            "wordpos": wordpos,
            "word_id": word_id,
            **ids,
        }
        for name, value in values.items():
            if name not in row:
                row[f"spine_{name}"] = _clean_token(value)
        rows.append(row)
        local_onset += duration
        global_onset += duration

    df = pd.DataFrame(rows)
    for col in _KNOWN_TIMELINE_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    extra_cols = [col for col in df.columns if col not in _KNOWN_TIMELINE_COLUMNS]
    df = df[_KNOWN_TIMELINE_COLUMNS + extra_cols]
    return df, metadata


def _mei_head(metadata: Dict[str, str], *, title: Optional[str] = None) -> List[str]:
    resolved_title = title or metadata.get("OTL") or "Rap Timeline"
    lines = [
        '  <meiHead>',
        '    <fileDesc>',
        '      <titleStmt>',
        f"        <title>{escape(resolved_title)}</title>",
        '      </titleStmt>',
        '      <pubStmt><p>Generated by CAMAT timeline_backend.</p></pubStmt>',
        '    </fileDesc>',
        '    <workList>',
        '      <work>',
        f"        <title>{escape(resolved_title)}</title>",
    ]
    composer = metadata.get("COM") or metadata.get("COC")
    if composer:
        lines.extend(
            [
                "        <composer>",
                f"          <persName>{escape(composer)}</persName>",
                "        </composer>",
            ]
        )
    lines.extend(["      </work>", "    </workList>", "  </meiHead>"])
    return lines


def _annotation_text(row: pd.Series) -> str:
    fields = [
        "duration_token",
        "ipa",
        "stress",
        "tone",
        "break",
        "rhyme",
        "hype",
        "word_id",
    ]
    values = []
    for field in fields:
        value = row.get(field)
        if not _is_null_token(value):
            values.append(f"{field}={value}")
    return "; ".join(values)


def _lyric_info_text(
    row: pd.Series,
    fields: Sequence[str],
    *,
    labels: Optional[Mapping[str, str]] = None,
    separator: str = " ",
) -> str:
    values = []
    for field in fields:
        value = row.get(field)
        if not _is_null_token(value):
            label = str(labels.get(field, field)) if labels else str(field)
            if label:
                values.append(f"{label}:{value}")
            else:
                values.append(str(value))
    return separator.join(values)


def _lyric_info_items(
    row: pd.Series,
    fields: Sequence[str],
    *,
    labels: Optional[Mapping[str, str]] = None,
) -> List[Tuple[int, str, str]]:
    items: List[Tuple[int, str, str]] = []
    for field_index, field in enumerate(fields):
        value = row.get(field)
        if _is_null_token(value):
            continue
        label = str(labels.get(field, field)) if labels else str(field)
        text = f"{label}:{value}" if label else str(value)
        items.append((field_index, field, text))
    return items


def _lyric_info_verse_start(verse_n: str) -> int:
    try:
        return int(verse_n)
    except Exception:
        return 2


def _scoredef_attrs(df_timeline: pd.DataFrame) -> Tuple[str, str, Optional[float]]:
    meter = None
    tempo = None
    if not df_timeline.empty:
        meters = [m for m in df_timeline["meter"].dropna().astype(str).tolist() if m]
        tempos = [t for t in df_timeline["tempo_bpm"].dropna().tolist()]
        meter = meters[0] if meters else None
        tempo = float(tempos[0]) if tempos else None
    if meter and "/" in meter:
        count, unit = meter.split("/", 1)
    else:
        count, unit = "4", "4"
    return count, unit, tempo


def _iter_measure_groups(df_timeline: pd.DataFrame):
    if df_timeline.empty:
        return
    sort_cols = ["section_index", "measure_index", "event_index"]
    ordered = df_timeline.sort_values(sort_cols, kind="stable")
    group_cols = ["section_index", "section", "measure_index", "measure"]
    for keys, group in ordered.groupby(group_cols, dropna=False, sort=False):
        yield keys, group


def timeline_to_mei(
    df_timeline: pd.DataFrame,
    *,
    metadata: Optional[Dict[str, str]] = None,
    title: Optional[str] = None,
    pitch_name: str = "c",
    octave: int = 4,
    note_position: str = "auto",
    note_loc: int = 0,
    staff_lines: int = 1,
    show_clef: bool = False,
    main_lyric_verse_n: str = "1",
    lyric_info_fields: Optional[Sequence[str]] = None,
    lyric_info_labels: Optional[Mapping[str, str]] = None,
    lyric_info_separator: str = " ",
    lyric_info_verse_n: str = "2",
    lyric_info_layout: str = "combined",
    include_annotations: bool = True,
    measures_per_system: Optional[int] = None,
    show_section_labels: bool = False,
    section_label_roles: Optional[Sequence[str]] = None,
) -> str:
    """Convert a timeline dataframe to MEI note/lyric anchors plus annotations."""
    metadata = dict(metadata or {})
    count, unit, _tempo = _scoredef_attrs(df_timeline)
    staff_line_count = max(1, int(staff_lines))
    clef_attrs = ' clef.shape="G" clef.line="2"' if show_clef else ""
    note_position_attr = _note_position_attrs(
        pitch_name=pitch_name,
        octave=octave,
        staff_lines=staff_line_count,
        show_clef=show_clef,
        note_position=note_position,
        note_loc=note_loc,
    )
    info_fields = tuple(lyric_info_fields or ())
    info_layout = str(lyric_info_layout).lower()
    if info_layout not in {"combined", "separate"}:
        raise ValueError("lyric_info_layout must be 'combined' or 'separate'.")
    system_measure_count = int(measures_per_system) if measures_per_system else 0
    section_roles = set(section_label_roles or ())
    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<mei xmlns="{MEI_NS}" meiversion="5.0">',
        *_mei_head(metadata, title=title),
        "  <music>",
        "    <body>",
        "      <mdiv>",
        "        <score>",
        f'          <scoreDef meter.count="{escape(count, quote=True)}" meter.unit="{escape(unit, quote=True)}">',
        '            <staffGrp>',
        f'              <staffDef n="1" lines="{staff_line_count}"{clef_attrs}/>',
        '            </staffGrp>',
        '          </scoreDef>',
    ]
    current_section_key: Optional[Tuple[Any, Any]] = None
    measures_in_section = 0
    for keys, group in _iter_measure_groups(df_timeline) or []:
        section_index, section, measure_index, measure = keys
        section_key = (section_index, section)
        if section_key != current_section_key:
            if current_section_key is not None:
                lines.append("          </section>")
            section_label = "" if _is_null_token(section) else f' label="{escape(str(section), quote=True)}"'
            role = _section_role(section)
            section_type = "" if role is None else f' type="{escape(role, quote=True)}"'
            section_id = _slug(section or f"section-{section_index}", fallback="sec")
            lines.append(f'          <section xml:id="sec-{section_id}"{section_label}{section_type}>')
            current_section_key = section_key
            measures_in_section = 0

        measure_piece = _measure_id_piece(measure, int(measure_index))
        measure_n = measure if not _is_null_token(measure) else int(measure_index)
        if system_measure_count > 0 and measures_in_section > 0 and measures_in_section % system_measure_count == 0:
            lines.append("            <sb/>")
        lines.append(
            f'            <measure xml:id="measure-{_slug(section or "section", fallback="sec")}-{measure_piece}" n="{escape(str(measure_n), quote=True)}">'
        )
        measures_in_section += 1
        lines.append('              <staff n="1">')
        lines.append('                <layer n="1">')
        for _, row in group.iterrows():
            event_id = str(row.get("xml_id_event"))
            mei_duration = _duration_to_mei_attrs(row)
            if bool(row.get("is_rest")):
                lines.append(f'                  <rest xml:id="{escape(event_id, quote=True)}" {mei_duration}/>')
                continue

            note_id = str(row.get("xml_id_note"))
            syl_id = str(row.get("xml_id_syl"))
            lines.append(
                f'                  <note xml:id="{escape(note_id, quote=True)}" {mei_duration} {note_position_attr}>'
            )
            lyric = row.get("lyric")
            if not _is_null_token(lyric):
                wordpos = row.get("wordpos")
                wordpos_attr = "" if _is_null_token(wordpos) else f' wordpos="{escape(str(wordpos), quote=True)}"'
                lines.append(f'                    <verse n="{escape(str(main_lyric_verse_n), quote=True)}">')
                lines.append(
                    f'                      <syl xml:id="{escape(syl_id, quote=True)}"{wordpos_attr}>{escape(str(lyric))}</syl>'
                )
                lines.append("                    </verse>")
            info_text = (
                _lyric_info_text(
                    row,
                    info_fields,
                    labels=lyric_info_labels,
                    separator=lyric_info_separator,
                )
                if info_fields
                else ""
            )
            if info_text:
                info_id = str(syl_id).replace("syl-", "sylinfo-", 1)
                if info_layout == "combined":
                    lines.append(f'                    <verse n="{escape(str(lyric_info_verse_n), quote=True)}">')
                    lines.append(
                        f'                      <syl xml:id="{escape(info_id, quote=True)}" type="rap-info">{escape(info_text)}</syl>'
                    )
                    lines.append("                    </verse>")
                else:
                    verse_start = _lyric_info_verse_start(lyric_info_verse_n)
                    for field_index, field, item_text in _lyric_info_items(
                        row, info_fields, labels=lyric_info_labels
                    ):
                        field_slug = _slug(field, fallback="field")
                        field_info_id = f"{info_id}-{field_slug}"
                        verse_n = str(verse_start + field_index)
                        lines.append(f'                    <verse n="{escape(verse_n, quote=True)}">')
                        lines.append(
                            f'                      <syl xml:id="{escape(field_info_id, quote=True)}" type="rap-info-{escape(field_slug, quote=True)}">{escape(item_text)}</syl>'
                        )
                        lines.append("                    </verse>")
            lines.append("                  </note>")
        lines.append("                </layer>")
        lines.append("              </staff>")
        section_role = _section_role(section)
        should_show_section = show_section_labels and not _is_null_token(section)
        if should_show_section and section_roles and section_role not in section_roles:
            should_show_section = False
        if should_show_section and measures_in_section == 1:
            lines.append(
                f'              <dir type="section-label" place="above" tstamp="1">{escape(str(section))}</dir>'
            )
        if include_annotations:
            for _, row in group.iterrows():
                annot_text = _annotation_text(row)
                if not annot_text:
                    continue
                annot_id = str(row.get("xml_id_annot"))
                target_id = str(row.get("xml_id_event") if bool(row.get("is_rest")) else row.get("xml_id_note"))
                syl_id = row.get("xml_id_syl")
                plist = f"#{target_id}"
                if not _is_null_token(syl_id):
                    plist += f" #{syl_id}"
                lines.append(
                    f'              <annot xml:id="{escape(annot_id, quote=True)}" type="rap-token" plist="{escape(plist, quote=True)}">'
                )
                lines.append(f"                <p>{escape(annot_text)}</p>")
                lines.append("              </annot>")
        lines.append("            </measure>")

    if current_section_key is not None:
        lines.append("          </section>")
    lines.extend(
        [
            "        </score>",
            "      </mdiv>",
            "    </body>",
            "  </music>",
            "</mei>",
        ]
    )
    return "\n".join(lines) + "\n"


def save_timeline_mei(
    df_timeline: pd.DataFrame,
    path: str | Path,
    *,
    metadata: Optional[Dict[str, str]] = None,
    title: Optional[str] = None,
    pitch_name: str = "c",
    octave: int = 4,
    note_position: str = "auto",
    note_loc: int = 0,
    staff_lines: int = 1,
    show_clef: bool = False,
    main_lyric_verse_n: str = "1",
    lyric_info_fields: Optional[Sequence[str]] = None,
    lyric_info_labels: Optional[Mapping[str, str]] = None,
    lyric_info_separator: str = " ",
    lyric_info_verse_n: str = "2",
    lyric_info_layout: str = "combined",
    include_annotations: bool = True,
    measures_per_system: Optional[int] = None,
    show_section_labels: bool = False,
    section_label_roles: Optional[Sequence[str]] = None,
    encoding: str = "utf-8",
) -> str:
    """Compose timeline data as MEI, write it to ``path``, and return the text."""
    mei = timeline_to_mei(
        df_timeline,
        metadata=metadata,
        title=title,
        pitch_name=pitch_name,
        octave=octave,
        note_position=note_position,
        note_loc=note_loc,
        staff_lines=staff_lines,
        show_clef=show_clef,
        main_lyric_verse_n=main_lyric_verse_n,
        lyric_info_fields=lyric_info_fields,
        lyric_info_labels=lyric_info_labels,
        lyric_info_separator=lyric_info_separator,
        lyric_info_verse_n=lyric_info_verse_n,
        lyric_info_layout=lyric_info_layout,
        include_annotations=include_annotations,
        measures_per_system=measures_per_system,
        show_section_labels=show_section_labels,
        section_label_roles=section_label_roles,
    )
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(mei, encoding=encoding)
    return mei


def parse_rap_humdrum_source(
    source: str,
    *,
    encoding: str = "utf-8",
) -> TimelineParseResult:
    """Parse a rap/timeline Humdrum source into ``df_timeline`` only.

    MEI creation is intentionally separate; call ``timeline_to_mei`` or
    ``save_timeline_mei`` after selecting what analysis fields should render.
    """
    text = _read_source(source, encoding=encoding)
    df_timeline, metadata = humdrum_rap_to_timeline(text, source=source)
    return TimelineParseResult(df_timeline=df_timeline, metadata=metadata)


def parse_rap_humdrum_file(
    path: str,
    *,
    encoding: str = "utf-8",
) -> TimelineParseResult:
    """Parse a local rap/timeline Humdrum file into ``df_timeline`` only."""
    return parse_rap_humdrum_source(path, encoding=encoding)


def parse_files_timeline(
    file_sources: Iterable[str],
    *,
    encoding: str = "utf-8",
) -> Tuple[List[Dict[str, Any]], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """Parse rap/timeline sources without registering a main parser backend."""
    results: List[Dict[str, Any]] = []
    dfs_by_name: Dict[str, pd.DataFrame] = {}
    last_df: Optional[pd.DataFrame] = None

    for index, source in enumerate(file_sources):
        parsed = parse_rap_humdrum_source(source, encoding=encoding)
        name = f"{index:02d}_{_slug(_source_name(source), fallback='timeline')}"
        df_name = f"{name}_timeline"
        entry = {
            "name": name,
            "source": source,
            "df": parsed.df_timeline,
            "df_timeline": parsed.df_timeline,
            "df_name_timeline": df_name,
            "metadata": parsed.metadata,
        }
        results.append(entry)
        dfs_by_name[df_name] = parsed.df_timeline
        last_df = parsed.df_timeline
    return results, dfs_by_name, last_df


def load_timeline_mei_with_verovio(mei: str) -> int:
    """Load generated timeline MEI into Verovio and return the page count."""
    import verovio  # type: ignore

    toolkit = verovio.toolkit()
    toolkit.setOptions({"inputFrom": "mei"})
    ok = toolkit.loadData(mei)
    pages = int(toolkit.getPageCount())
    if not ok or pages <= 0:
        log = ""
        if hasattr(toolkit, "getLog"):
            try:
                log = toolkit.getLog() or ""
            except Exception:
                log = ""
        raise RuntimeError(f"Verovio failed to load generated timeline MEI. {log}".strip())
    return pages


def find_duplicate_mei_xml_ids(mei: str) -> pd.DataFrame:
    """Return duplicated ``xml:id`` values in a generated MEI string."""
    root = ET.fromstring(mei)
    xml_id_attr = "{http://www.w3.org/XML/1998/namespace}id"
    seen: Dict[str, int] = {}
    for elem in root.iter():
        xml_id = elem.attrib.get(xml_id_attr)
        if not xml_id:
            continue
        seen[xml_id] = seen.get(xml_id, 0) + 1
    rows = [
        {"xml_id": xml_id, "count": count}
        for xml_id, count in sorted(seen.items())
        if count > 1
    ]
    return pd.DataFrame(rows, columns=["xml_id", "count"])
