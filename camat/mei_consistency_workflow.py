"""Reusable orchestration helpers for CAMAT's MEI editorial checks.

The module contains the check, cleanup, schema-validation, and Verovio passes
used by the corrected-full-MEI maintainer notebook.  Cleanup functions only
rewrite files when their corresponding flags are enabled.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .check_mei_consistency import (
    Finding,
    check_mei_files,
    strip_accid_ges_text,
    strip_ppq_text,
    write_csv,
)


MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
REFERENCE_ATTRS = {"facs", "startid", "endid", "target", "plist", "corresp", "sameas", "next", "prev", "copyof", "synch", "decls"}
MEI_CMN_51_SCHEMA = Path(__file__).with_name("schemas") / "mei-CMN-5.1.rng"

ET.register_namespace("", MEI_NS)


@dataclass
class WriteResult:
    files: list[Path]
    count: int = 0
    message: str = ""


@dataclass
class CombineResult:
    path: Path
    duplicate_ids: list[str]
    skipped_expansions: int
    renumbered_measures: int
    numbered_zones: int
    normalized_single_layers: int = 0
    staff_names_written: int = 0
    staff_group_names_written: int = 0
    later_staff_names_removed: int = 0


@dataclass
class AnnotationResult:
    path: Path
    created: int
    skipped: int
    capped: bool


@dataclass
class CleanupResult:
    files: list[Path]
    changed: int
    rows: list[dict[str, str]]
    message: str


VEROVIO_REPORT_COLUMNS = [
    "severity",
    "category",
    "check",
    "file",
    "line",
    "element",
    "measure_n",
    "staff_n",
    "layer_n",
    "xml_id",
    "message",
    "expected",
    "actual",
    "context",
]


@dataclass
class VerovioLogResult:
    version: str
    rows: list[dict[str, str]]
    files_checked: int
    render_pages: bool

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame(self.rows, columns=VEROVIO_REPORT_COLUMNS)


@dataclass
class SchemaValidationResult:
    schema: Path
    rows: list[dict[str, str]]
    files_checked: int

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame(self.rows, columns=VEROVIO_REPORT_COLUMNS)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def qname(local: str) -> str:
    return f"{{{MEI_NS}}}{local}"


def first_descendant(root: ET.Element, tag: str) -> ET.Element | None:
    return next((element for element in root.iter() if local_name(element.tag) == tag), None)


def first_child(element: ET.Element, tag: str) -> ET.Element | None:
    return next((child for child in list(element) if local_name(child.tag) == tag), None)


def ancestor_attr(
    element: ET.Element,
    parent_map: Mapping[ET.Element, ET.Element],
    ancestor_tag: str,
    attr: str,
) -> str:
    current = parent_map.get(element)
    while current is not None:
        if local_name(current.tag) == ancestor_tag:
            return current.get(attr, "")
        current = parent_map.get(current)
    return ""


def normalized_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def resolve_mei_inputs(inputs: Iterable[str | Path], root: Path) -> list[Path]:
    files: list[Path] = []
    for raw_path in inputs:
        path = Path(raw_path)
        if not path.is_absolute():
            path = root / path
        if path.is_dir():
            files.extend(sorted(path.rglob("*.mei")))
        elif path.is_file() and path.suffix.lower() == ".mei":
            files.append(path)
        elif path.suffix.lower() == ".mei":
            raise FileNotFoundError(f"MEI file does not exist: {path}")
        else:
            raise ValueError(f"Input is not a directory or .mei file: {path}")
    return sorted(dict.fromkeys(file.resolve() for file in files))


def _local_attr_name(name: str) -> str:
    return name.rsplit("}", 1)[-1] if "}" in name else name


def make_unique_xml_id_copies(files: Iterable[Path], output_dir: Path) -> WriteResult:
    output_files: list[Path] = []
    seen_ids: set[str] = set()
    renamed_total = 0
    output_dir.mkdir(parents=True, exist_ok=True)

    for source in files:
        tree = ET.parse(source)
        root = tree.getroot()
        rename_map: dict[str, str] = {}
        prefix = source.stem

        for element in root.iter():
            xml_id = element.get(XML_ID)
            if not xml_id:
                continue
            if xml_id in seen_ids:
                candidate = f"{prefix}_{xml_id}"
                suffix = 2
                while candidate in seen_ids:
                    candidate = f"{prefix}_{xml_id}_{suffix}"
                    suffix += 1
                element.set(XML_ID, candidate)
                rename_map[xml_id] = candidate
                seen_ids.add(candidate)
                renamed_total += 1
            else:
                seen_ids.add(xml_id)

        if rename_map:
            for element in root.iter():
                for attr_name, value in list(element.attrib.items()):
                    if _local_attr_name(attr_name) not in REFERENCE_ATTRS:
                        continue
                    tokens = str(value).split()
                    updated = [
                        f"#{rename_map[token[1:]]}"
                        if token.startswith("#") and token[1:] in rename_map
                        else token
                        for token in tokens
                    ]
                    if updated != tokens:
                        element.set(attr_name, " ".join(updated))

        target = output_dir / f"{source.stem}_unique_ids{source.suffix}"
        _write_tree_with_original_preamble(tree, root, source, target)
        output_files.append(target)

    return WriteResult(output_files, renamed_total, f"Renamed {renamed_total} duplicate xml:id value(s).")


def strip_ppq_copies(files: Iterable[Path], output_dir: Path) -> WriteResult:
    output_files: list[Path] = []
    removed_total = 0
    output_dir.mkdir(parents=True, exist_ok=True)

    for source in files:
        cleaned, removed = strip_ppq_text(source.read_text(encoding="utf-8"))
        removed_total += removed
        target = output_dir / f"{source.stem}_noppq{source.suffix}"
        target.write_text(cleaned, encoding="utf-8")
        output_files.append(target)

    return WriteResult(output_files, removed_total, f"Removed {removed_total} @ppq/@dur.ppq attribute(s).")


def normalize_single_layer_number_copies(
    files: Iterable[Path],
    output_dir: Path | None = None,
    *,
    suffix: str = "_layers_normalized",
) -> WriteResult:
    output_files: list[Path] = []
    changed_total = 0
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for source in files:
        tree = ET.parse(source)
        root = tree.getroot()
        changed = normalize_single_layer_numbers_to_one(root)
        changed_total += changed
        target_dir = output_dir if output_dir is not None else source.parent
        target = target_dir / f"{source.stem}{suffix}{source.suffix}"
        _write_tree_with_original_preamble(tree, root, source, target)
        output_files.append(target)

    return WriteResult(
        output_files,
        changed_total,
        f"Normalized {changed_total} layer @n value(s).",
    )


def apply_safe_cleanup(
    files: Iterable[Path],
    *,
    root: Path,
    clean_ppq: bool = False,
    clean_accid: bool = False,
    clean_accid_ges: bool = False,
    fix_ties: bool = False,
) -> CleanupResult:
    files = list(files)
    rows: list[dict[str, str]] = []
    changed_total = 0

    if not clean_ppq and not clean_accid and not clean_accid_ges and not fix_ties:
        return CleanupResult(files, 0, [], "Safe cleanup disabled.")

    for path in files:
        if clean_ppq:
            cleaned, removed = strip_ppq_text(path.read_text(encoding="utf-8"))
            if removed:
                path.write_text(cleaned, encoding="utf-8")
                changed_total += removed

        if clean_accid_ges:
            cleaned, removed = strip_accid_ges_text(path.read_text(encoding="utf-8"))
            if removed:
                path.write_text(cleaned, encoding="utf-8")
                changed_total += removed

        if not clean_accid and not fix_ties:
            continue

        tree = ET.parse(path)
        mei_root = tree.getroot()
        text = path.read_text(encoding="utf-8")
        id_lines = _scan_xml_id_lines(text)
        parent_map = _build_parent_map(mei_root)
        ids = {element.get(XML_ID): element for element in mei_root.iter() if element.get(XML_ID)}
        changed = 0

        if clean_accid:
            changed += _clean_duplicate_accidentals(
                path,
                mei_root,
                parent_map,
                id_lines=id_lines,
                root=root,
                rows=rows,
            )

        if fix_ties:
            changed += _fix_ties_safely(
                path,
                mei_root,
                parent_map,
                ids=ids,
                id_lines=id_lines,
                root=root,
                rows=rows,
            )

        if changed:
            _write_tree_with_original_preamble(tree, mei_root, path, path)
            changed_total += changed

    actions = []
    if clean_ppq:
        actions.append("PPQ cleanup")
    if clean_accid:
        actions.append("accidental cleanup")
    if clean_accid_ges:
        actions.append("accid.ges cleanup")
    if fix_ties:
        actions.append("safe tie cleanup")
    return CleanupResult(
        files,
        changed_total,
        rows,
        f"Applied {' and '.join(actions)}: {changed_total} edit(s), {len(rows)} review warning(s).",
    )


def _clean_duplicate_accidentals(
    path: Path,
    root_element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    *,
    id_lines: Mapping[str, int],
    root: Path,
    rows: list[dict[str, str]],
) -> int:
    changed = 0
    referenced_ids = {
        token[1:]
        for element in root_element.iter()
        for attr_name, value in element.attrib.items()
        if _local_attr_name(attr_name) in REFERENCE_ATTRS
        for token in str(value).split()
        if token.startswith("#") and len(token) > 1
    }
    for note in root_element.iter():
        if local_name(note.tag) != "note":
            continue
        accidental_children = [child for child in list(note) if local_name(child.tag) == "accid"]
        if not accidental_children:
            continue

        retained_accidentals = []
        for accidental in accidental_children:
            meaningful_attrs = {
                _local_attr_name(name): value
                for name, value in accidental.attrib.items()
                if _local_attr_name(name) != "id" and value
            }
            accidental_id = accidental.get(XML_ID, "")
            if meaningful_attrs or normalized_text(accidental):
                retained_accidentals.append(accidental)
            elif accidental_id and accidental_id in referenced_ids:
                retained_accidentals.append(accidental)
                rows.append(
                    _cleanup_row(
                        path,
                        root=root,
                        element=accidental,
                        parent_map=parent_map,
                        id_lines=id_lines,
                        check="empty_accid_referenced",
                        message="Empty accid is referenced elsewhere; automatic removal was skipped.",
                        actual=f"#{accidental_id}",
                    )
                )
            else:
                note.remove(accidental)
                changed += 1

        accidental_children = retained_accidentals
        if not accidental_children:
            continue

        note_accidentals = {
            name: note.get(name, "")
            for name in ("accid", "accid.ges")
            if note.get(name)
        }
        if not note_accidentals:
            continue

        child_values = [child.get("accid", "") for child in accidental_children]
        child_value = child_values[0] if len(set(child_values)) == 1 else ""
        if child_value and all(value == child_value for value in note_accidentals.values()):
            for name in note_accidentals:
                del note.attrib[name]
                changed += 1
            continue

        rows.append(
            _cleanup_row(
                path,
                root=root,
                element=note,
                parent_map=parent_map,
                id_lines=id_lines,
                check="accid_conflict",
                message="Note has both note-level accidental data and <accid> child data that do not agree.",
                expected="matching accidental values before automatic cleanup",
                actual=f"note={note_accidentals}; child={child_values}",
            )
        )
    return changed


def _fix_ties_safely(
    path: Path,
    root_element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    *,
    ids: Mapping[str, ET.Element],
    id_lines: Mapping[str, int],
    root: Path,
    rows: list[dict[str, str]],
) -> int:
    changed = 0
    tie_infos: list[dict[str, object]] = []
    incoming: Counter[str] = Counter()
    outgoing: Counter[str] = Counter()

    for tie in [element for element in root_element.iter() if local_name(element.tag) == "tie"]:
        start_id, start_changed = _normalize_reference_attr(tie, "startid", ids)
        end_id, end_changed = _normalize_reference_attr(tie, "endid", ids)
        changed += start_changed + end_changed

        start = ids.get(start_id)
        end = ids.get(end_id)
        valid = True
        if start is None or end is None:
            rows.append(
                _cleanup_row(
                    path,
                    root=root,
                    element=tie,
                    parent_map=parent_map,
                    id_lines=id_lines,
                    check="tie_missing_endpoint",
                    message="Tie endpoint does not resolve to an xml:id.",
                    expected="both @startid and @endid resolve",
                    actual=f"startid={tie.get('startid', '')}; endid={tie.get('endid', '')}",
                )
            )
            valid = False
        elif local_name(start.tag) != "note" or local_name(end.tag) != "note":
            rows.append(
                _cleanup_row(
                    path,
                    root=root,
                    element=tie,
                    parent_map=parent_map,
                    id_lines=id_lines,
                    check="tie_endpoint_not_note",
                    message="Tie endpoint is not a <note>; automatic tie role repair skipped.",
                    expected="note-to-note tie endpoints",
                    actual=f"start={local_name(start.tag)}; end={local_name(end.tag)}",
                )
            )
            valid = False
        elif _note_pitch_key(start) != _note_pitch_key(end):
            rows.append(
                _cleanup_row(
                    path,
                    root=root,
                    element=tie,
                    parent_map=parent_map,
                    id_lines=id_lines,
                    check="tie_pitch_mismatch",
                    message="Tie endpoints do not have the same written pname/oct; automatic repair skipped.",
                    expected=str(_note_pitch_key(start)),
                    actual=str(_note_pitch_key(end)),
                )
            )
            valid = False

        if not valid:
            continue

        outgoing[start_id] += 1
        incoming[end_id] += 1
        tie_infos.append({"tie": tie, "start_id": start_id, "end_id": end_id, "start": start, "end": end})

    _warn_cross_layer_note_ties(
        path,
        root_element,
        parent_map,
        id_lines=id_lines,
        root=root,
        rows=rows,
    )

    for info in tie_infos:
        tie = info["tie"]  # type: ignore[assignment]
        start = info["start"]  # type: ignore[assignment]
        current_parent = parent_map.get(tie)
        start_measure = _nearest_ancestor(start, parent_map, "measure")  # type: ignore[arg-type]
        if current_parent is not None and start_measure is not None and current_parent is not start_measure:
            current_parent.remove(tie)  # type: ignore[arg-type]
            start_measure.append(tie)  # type: ignore[arg-type]
            changed += 1

    for info in tie_infos:
        start = info["start"]  # type: ignore[assignment]
        end = info["end"]  # type: ignore[assignment]
        start_role = start.get("tie", "")  # type: ignore[union-attr]
        end_role = end.get("tie", "")  # type: ignore[union-attr]

        if start_role not in {"i", "m"}:
            if start_role:
                rows.append(
                    _cleanup_row(
                        path,
                        root=root,
                        element=start,  # type: ignore[arg-type]
                        parent_map=parent_map,
                        id_lines=id_lines,
                        check="tie_role_conflict",
                        message="Tie starts at a note whose existing @tie value is not initial or median; terminal repair skipped.",
                        expected="i or m",
                        actual=start_role,
                    )
                )
            continue

        if outgoing[info["end_id"]]:  # type: ignore[index]
            if end_role != "m":
                rows.append(
                    _cleanup_row(
                        path,
                        root=root,
                        element=end,  # type: ignore[arg-type]
                        parent_map=parent_map,
                        id_lines=id_lines,
                        check="tie_role_review",
                        message="Tie endpoint also starts another tie; median role requires manual review.",
                        expected="m",
                        actual=end_role,
                    )
                )
            continue

        if not end_role:
            end.set("tie", "t")  # type: ignore[union-attr]
            changed += 1
        elif end_role != "t":
            rows.append(
                _cleanup_row(
                    path,
                    root=root,
                    element=end,  # type: ignore[arg-type]
                    parent_map=parent_map,
                    id_lines=id_lines,
                    check="tie_role_conflict",
                    message="Tie endpoint has an existing @tie value that is not terminal; automatic repair skipped.",
                    expected="t",
                    actual=end_role,
                )
            )

    return changed


def _warn_cross_layer_note_ties(
    path: Path,
    root_element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    *,
    id_lines: Mapping[str, int],
    root: Path,
    rows: list[dict[str, str]],
) -> None:
    open_notes: dict[tuple[str, str, tuple[str, str]], ET.Element] = {}
    reported: set[tuple[str, str]] = set()

    for note in root_element.iter():
        if local_name(note.tag) != "note":
            continue

        role = note.get("tie", "")
        if role not in {"i", "m", "t"}:
            continue

        pitch = _note_pitch_key(note)
        if not all(pitch):
            continue

        staff_n = ancestor_attr(note, parent_map, "staff", "n")
        layer_n = ancestor_attr(note, parent_map, "layer", "n")
        if not staff_n or not layer_n:
            continue

        key = (staff_n, layer_n, pitch)
        if role == "i":
            open_notes[key] = note
            continue

        start = open_notes.pop(key, None)
        if start is not None:
            if role == "m":
                open_notes[key] = note
            continue

        cross_layer_candidates = [
            (open_key, open_note)
            for open_key, open_note in open_notes.items()
            if open_key[0] == staff_n and open_key[2] == pitch and open_key[1] != layer_n
        ]
        if not cross_layer_candidates:
            if role == "m":
                open_notes[key] = note
            continue

        start_key, start_note = cross_layer_candidates[-1]
        start_id = start_note.get(XML_ID, "")
        end_id = note.get(XML_ID, "")
        report_key = (start_id, end_id)
        if report_key not in reported:
            rows.append(
                _cleanup_row(
                    path,
                    root=root,
                    element=note,
                    parent_map=parent_map,
                    id_lines=id_lines,
                    check="tie_cross_layer_note_roles",
                    message="Note-level @tie chain crosses layers; Verovio may leave the starting layer unresolved. Prefer an explicit <tie> for cross-layer ties.",
                    expected="same-layer @tie chain or explicit <tie>",
                    actual=(
                        f"start={start_id or '(no xml:id)'} layer={start_key[1]}; "
                        f"end={end_id or '(no xml:id)'} layer={layer_n}; pitch={pitch}"
                    ),
                )
            )
            reported.add(report_key)

        del open_notes[start_key]
        if role == "m":
            open_notes[key] = note


def _normalize_reference_attr(tie: ET.Element, attr: str, ids: Mapping[str, ET.Element]) -> tuple[str, int]:
    raw = tie.get(attr, "")
    if not raw:
        return "", 0
    ref = raw[1:] if raw.startswith("#") else raw
    if ref in ids and not raw.startswith("#"):
        tie.set(attr, f"#{ref}")
        return ref, 1
    return ref, 0


def _note_pitch_key(note: ET.Element) -> tuple[str, str]:
    return note.get("pname", ""), note.get("oct", "")


def _cleanup_row(
    path: Path,
    *,
    root: Path,
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    id_lines: Mapping[str, int],
    check: str,
    message: str,
    expected: str = "",
    actual: str = "",
) -> dict[str, str]:
    xml_id = element.get(XML_ID, "")
    record = _element_context_record(element, parent_map, line=str(id_lines.get(xml_id, "")) if xml_id else "")
    return {
        "severity": "warning",
        "category": "cleanup",
        "check": check,
        "file": _relative_path_text(path, root),
        "line": record["line"],
        "element": record["element"],
        "measure_n": record["measure_n"],
        "staff_n": record["staff_n"],
        "layer_n": record["layer_n"],
        "xml_id": record["xml_id"],
        "message": message,
        "expected": expected,
        "actual": actual,
        "context": "safe cleanup",
    }


def run_checker(
    files: Iterable[Path],
    *,
    root: Path,
    csv_out: Path,
    json_out: Path | None = None,
    check_ppq: bool = False,
    publication_profile: bool = False,
) -> list[Finding]:
    """Run the package checker and write its CSV and optional JSON reports."""
    files = list(files)
    findings = check_mei_files(
        files,
        root_dir=root,
        check_ppq=check_ppq,
        publication_profile=publication_profile,
    )
    write_csv(csv_out, findings)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(
                [asdict(finding) for finding in findings],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    counts = Counter(finding.severity for finding in findings)
    print(f"Checked {len(files)} MEI file(s). Wrote {len(findings)} findings to {csv_out}.")
    print(
        "Findings by severity: "
        + ", ".join(
            f"{severity}={counts.get(severity, 0)}"
            for severity in ("error", "warning", "info")
        )
    )
    return findings


def run_relaxng_validation(
    files: Iterable[Path],
    *,
    schema: Path = MEI_CMN_51_SCHEMA,
    root: Path,
) -> SchemaValidationResult:
    """Validate MEI files with xmllint and return errors in report-row form."""
    files = list(files)
    schema = schema.resolve()
    if not schema.is_file():
        raise FileNotFoundError(f"RELAX NG schema does not exist: {schema}")

    rows: list[dict[str, str]] = []
    error_re = re.compile(
        r"^(?P<file>.+?):(?P<line>\d+): element (?P<element>[^:]+): "
        r"Relax-NG validity error : (?P<message>.*)$"
    )
    parser_error_re = re.compile(
        r"^(?P<file>.+?):(?P<line>\d+): (?P<kind>parser error|validity error) : "
        r"(?P<message>.*)$"
    )

    for path in files:
        try:
            result = subprocess.run(
                ["xmllint", "--noout", "--relaxng", str(schema), str(path)],
                cwd=root,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "xmllint is required for the pinned RELAX NG validation pass."
            ) from exc

        if result.returncode == 0:
            continue

        parsed_any = False
        for output_line in result.stderr.splitlines():
            match = error_re.match(output_line) or parser_error_re.match(output_line)
            if not match:
                continue
            parsed_any = True
            rows.append(
                {
                    "severity": "error",
                    "category": "schema",
                    "check": "mei_51_cmn_relaxng",
                    "file": _relative_path_text(path, root),
                    "line": match.group("line"),
                    "element": match.groupdict().get("element") or "",
                    "measure_n": "",
                    "staff_n": "",
                    "layer_n": "",
                    "xml_id": "",
                    "message": match.group("message"),
                    "expected": f"valid against {schema.name}",
                    "actual": "RELAX NG validation error",
                    "context": "xmllint",
                }
            )
        if not parsed_any:
            rows.append(
                {
                    "severity": "error",
                    "category": "schema",
                    "check": "mei_51_cmn_relaxng",
                    "file": _relative_path_text(path, root),
                    "line": "",
                    "element": "",
                    "measure_n": "",
                    "staff_n": "",
                    "layer_n": "",
                    "xml_id": "",
                    "message": result.stderr.strip() or "xmllint validation failed.",
                    "expected": f"valid against {schema.name}",
                    "actual": f"xmllint exit code {result.returncode}",
                    "context": "xmllint",
                }
            )

    return SchemaValidationResult(schema=schema, rows=rows, files_checked=len(files))


def run_verovio_warning_check(
    files: Iterable[Path],
    *,
    root: Path,
    render_pages: bool = True,
) -> VerovioLogResult:
    try:
        import verovio
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Verovio is not installed in this Python environment. "
            "Install the repo requirements, e.g. `python -m pip install -r requirements.txt`."
        ) from exc

    verovio.enableLog(verovio.LOG_WARNING)

    rows: list[dict[str, str]] = []
    version = verovio.toolkit().getVersion()
    files = list(files)

    if not hasattr(verovio, "enableLogToBuffer"):
        return _run_verovio_warning_check_subprocess(files, root=root, render_pages=render_pages, version=version)

    verovio.enableLogToBuffer(True)

    for path in files:
        tk = verovio.toolkit()
        loaded = tk.loadFile(str(path))
        rows.extend(_verovio_log_rows(tk.getLog(), path, root=root, context="load"))

        if loaded and render_pages:
            for page_no in range(1, tk.getPageCount() + 1):
                tk.renderToSVG(page_no)
                rows.extend(
                    _verovio_log_rows(
                        tk.getLog(),
                        path,
                        root=root,
                        context=f"render page {page_no}",
                    )
                )

        if not loaded and not any(row["file"] == _relative_path_text(path, root) for row in rows):
            rows.append(
                _verovio_log_row(
                    path,
                    root=root,
                    severity="error",
                    message="Verovio could not load this file and returned no log message.",
                    context="load",
                )
            )

    _enrich_verovio_rows(rows, root=root)
    return VerovioLogResult(version, _dedupe_verovio_rows(rows), len(files), render_pages)


def _run_verovio_warning_check_subprocess(
    files: list[Path],
    *,
    root: Path,
    render_pages: bool,
    version: str,
) -> VerovioLogResult:
    rows: list[dict[str, str]] = []
    child_code = """
import sys
import verovio

verovio.enableLog(verovio.LOG_WARNING)
tk = verovio.toolkit()
path = sys.argv[1]
render_pages = sys.argv[2] == "1"
loaded = tk.loadFile(path)
if loaded and render_pages:
    for page_no in range(1, tk.getPageCount() + 1):
        tk.renderToSVG(page_no)
print(f"__VEROVIO_VERSION__={tk.getVersion()}")
print(f"__VEROVIO_LOADED__={int(loaded)}")
"""
    for path in files:
        result = subprocess.run(
            [sys.executable, "-c", child_code, str(path), "1" if render_pages else "0"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        log_lines: list[str] = []
        loaded = False
        for stream in (result.stderr, result.stdout):
            for line in stream.splitlines():
                if line.startswith("__VEROVIO_VERSION__="):
                    version = line.split("=", 1)[1]
                elif line.startswith("__VEROVIO_LOADED__="):
                    loaded = line.endswith("1")
                else:
                    log_lines.append(line)

        rows.extend(
            _verovio_log_rows(
                "\n".join(log_lines),
                path,
                root=root,
                context="load/render" if render_pages else "load",
            )
        )
        if result.returncode != 0:
            rows.append(
                _verovio_log_row(
                    path,
                    root=root,
                    severity="error",
                    message=f"Verovio subprocess exited with code {result.returncode}.",
                    context="load/render" if render_pages else "load",
                )
            )
        elif not loaded and not any(row["file"] == _relative_path_text(path, root) for row in rows):
            rows.append(
                _verovio_log_row(
                    path,
                    root=root,
                    severity="error",
                    message="Verovio could not load this file and returned no log message.",
                    context="load",
                )
            )

    _enrich_verovio_rows(rows, root=root)
    return VerovioLogResult(version, _dedupe_verovio_rows(rows), len(files), render_pages)


def _verovio_log_rows(log_text: str, path: Path, *, root: Path, context: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in log_text.splitlines():
        message = line.strip()
        if not message:
            continue
        match = re.match(r"^\[(?P<severity>[A-Za-z]+)\]\s*(?P<message>.*)$", message)
        if match:
            severity = match.group("severity").lower()
            message = match.group("message").strip()
        else:
            severity = "warning"
        if severity not in {"error", "warning", "info", "debug"}:
            severity = "warning"
        line_match = re.search(r"\bline\s+(\d+)\b", message, re.IGNORECASE)
        rows.append(
            _verovio_log_row(
                path,
                root=root,
                severity=severity,
                message=message,
                line=line_match.group(1) if line_match else "",
                context=context,
            )
        )
    return rows


def _verovio_log_row(
    path: Path,
    *,
    root: Path,
    severity: str,
    message: str,
    line: str = "",
    context: str = "",
) -> dict[str, str]:
    return {
        "severity": severity,
        "category": "verovio",
        "check": "verovio_log",
        "file": _relative_path_text(path, root),
        "line": line,
        "element": "",
        "measure_n": "",
        "staff_n": "",
        "layer_n": "",
        "xml_id": "",
        "message": message,
        "expected": "",
        "actual": "",
        "context": context,
    }


def _enrich_verovio_rows(rows: list[dict[str, str]], *, root: Path) -> None:
    indexes: dict[str, dict[str, object]] = {}
    missing_attr_offsets: Counter[tuple[str, str, str]] = Counter()
    for row in rows:
        file_key = row.get("file", "")
        if not file_key:
            continue
        index = indexes.get(file_key)
        if index is None:
            index = _mei_source_index(root / file_key)
            indexes[file_key] = index

        message = row.get("message", "")
        target_id = _verovio_message_target_id(message, index)
        if target_id:
            _apply_element_context(row, index, target_id)
            continue

        missing_match = re.search(r"Missing @([\w.-]+) on <(\w+)>", message)
        if missing_match:
            attr_name, tag = missing_match.groups()
            key = (file_key, tag, attr_name)
            element_records = index["missing_attrs"].get((tag, attr_name), [])  # type: ignore[index,union-attr]
            offset = missing_attr_offsets[key]
            missing_attr_offsets[key] += 1
            if offset < len(element_records):
                _apply_record_context(row, element_records[offset])


def _mei_source_index(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    id_lines = _scan_xml_id_lines(text)

    root = ET.fromstring(text)
    parent_map = _build_parent_map(root)
    by_id: dict[str, dict[str, str]] = {}
    missing_attrs: dict[tuple[str, str], list[dict[str, str]]] = {}

    missing_layer_n_lines = _missing_tag_attr_lines(text, "layer", "n")
    missing_layer_n_index = 0

    for element in root.iter():
        xml_id = element.get(XML_ID, "")
        line = str(id_lines.get(xml_id, "")) if xml_id else ""
        tag = local_name(element.tag)
        if tag == "layer" and not element.get("n") and missing_layer_n_index < len(missing_layer_n_lines):
            line = str(missing_layer_n_lines[missing_layer_n_index])
            missing_layer_n_index += 1

        record = _element_context_record(element, parent_map, line=line)
        if xml_id:
            by_id[xml_id] = record
        if tag == "layer" and not element.get("n"):
            missing_attrs.setdefault(("layer", "n"), []).append(record)

    return {"by_id": by_id, "missing_attrs": missing_attrs}


def _scan_xml_id_lines(text: str) -> dict[str, int]:
    id_lines: dict[str, int] = {}
    pattern = re.compile(r'\bxml:id\s*=\s*["\']([^"\']+)["\']')
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in pattern.finditer(line):
            id_lines.setdefault(match.group(1), line_no)
    return id_lines


def _missing_tag_attr_lines(text: str, tag: str, attr: str) -> list[int]:
    lines: list[int] = []
    tag_start = re.compile(rf"<{re.escape(tag)}(\s|>|/)")
    attr_pattern = re.compile(rf"\b{re.escape(attr)}\s*=")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if tag_start.search(line) and not attr_pattern.search(line):
            lines.append(line_no)
    return lines


def _element_context_record(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    *,
    line: str = "",
) -> dict[str, str]:
    return {
        "line": line,
        "element": local_name(element.tag),
        "measure_n": ancestor_attr(element, parent_map, "measure", "n"),
        "staff_n": ancestor_attr(element, parent_map, "staff", "n") or element.get("staff", ""),
        "layer_n": ancestor_attr(element, parent_map, "layer", "n") or element.get("n", ""),
        "xml_id": element.get(XML_ID, ""),
    }


def _apply_element_context(row: dict[str, str], index: dict[str, object], xml_id: str) -> None:
    by_id = index["by_id"]  # type: ignore[index]
    record = by_id.get(xml_id)  # type: ignore[union-attr]
    if record is not None:
        _apply_record_context(row, record)
        row["actual"] = xml_id


def _verovio_message_target_id(message: str, index: dict[str, object]) -> str:
    by_id = index["by_id"]  # type: ignore[index]
    patterns = [
        r"\bfor element '([^']+)'",
        r"\bstarting at '([^']+)'",
        r"\bnote '([^']+)'",
        r"\btie '([^']+)'",
        r"\belement '([^']+)'",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match and match.group(1) in by_id:  # type: ignore[operator]
            return match.group(1)
    for quoted in re.findall(r"'([^']+)'", message):
        if quoted in by_id:  # type: ignore[operator]
            return quoted
    return ""


def _dedupe_verovio_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(str(row.get(column, "")) for column in VEROVIO_REPORT_COLUMNS)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _apply_record_context(row: dict[str, str], record: Mapping[str, str]) -> None:
    for key in ("line", "element", "measure_n", "staff_n", "layer_n", "xml_id"):
        if record.get(key):
            row[key] = record[key]


def _relative_path_text(path: Path, root: Path) -> str:
    path = path.resolve()
    root = root.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def load_report(csv_path: Path):
    import pandas as pd

    df = pd.read_csv(csv_path).fillna("")
    df["line"] = df["line"].astype(str).str.replace(r"\.0$", "", regex=True)
    return df


def report_summary(df):
    return (
        df.groupby(["severity", "category", "check"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["severity", "count"], ascending=[True, False])
    )


def checked_file_path(report_file: str | Path, root: Path, active_files: Iterable[Path]) -> Path:
    report_path = Path(str(report_file))
    if report_path.is_absolute():
        return report_path
    candidate = root / report_path
    if candidate.exists():
        return candidate
    matches = [
        path for path in active_files
        if path.name == report_path.name or path.as_posix().endswith(report_path.as_posix())
    ]
    if len(matches) == 1:
        return matches[0]
    return candidate


def source_snippet(row, *, root: Path, active_files: Iterable[Path], radius: int = 2) -> None:
    path = checked_file_path(row["file"], root, active_files)
    line = str(row["line"])
    if not line.isdigit():
        print("No line number available for this row.")
        return
    line_no = int(line)
    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(1, line_no - radius)
    end = min(len(lines), line_no + radius)
    for current in range(start, end + 1):
        marker = ">" if current == line_no else " "
        print(f"{marker} {current:5d}: {lines[current - 1]}")


def _flattened_section_children(section: ET.Element) -> tuple[list[ET.Element], int]:
    children: list[ET.Element] = []
    skipped_expansions = 0
    for child in list(section):
        tag = local_name(child.tag)
        if tag == "expansion":
            skipped_expansions += 1
            continue
        if tag == "section":
            nested_children, nested_skipped = _flattened_section_children(child)
            children.extend(nested_children)
            skipped_expansions += nested_skipped
        else:
            children.append(copy.deepcopy(child))
    return children, skipped_expansions


def combine_meis(
    files: Iterable[Path],
    output_path: Path,
    *,
    renumber_measures: bool = True,
    number_measure_zones: bool = True,
    normalize_single_layer_numbers: bool = False,
    staff_names: Mapping[str, str] | Sequence[str] | None = None,
    staff_abbreviations: Mapping[str, str] | Sequence[str] | None = None,
    staff_group_label: str | None = None,
    staff_group_abbreviation: str | None = None,
    keep_original_staff_names: bool = False,
    staff_names_only_at_start: bool = True,
) -> CombineResult:
    files = list(files)
    if not files:
        raise FileNotFoundError("No active MEI files to combine")

    base_path = files[0]
    base_tree = ET.parse(base_path)
    base_root = base_tree.getroot()
    base_facsimile = first_descendant(base_root, "facsimile")
    base_section = first_descendant(base_root, "section")
    if base_section is None:
        raise ValueError(f"No <section> found in {base_path}")

    skipped_expansions = 0
    for page_index, path in enumerate(files[1:], start=2):
        page_root = ET.parse(path).getroot()
        page_facsimile = first_descendant(page_root, "facsimile")
        page_section = first_descendant(page_root, "section")
        if page_section is None:
            raise ValueError(f"No <section> found in {path}")
        if base_facsimile is not None and page_facsimile is not None:
            for surface in list(page_facsimile):
                if local_name(surface.tag) == "surface":
                    copied_surface = copy.deepcopy(surface)
                    copied_surface.set("n", str(page_index))
                    base_facsimile.append(copied_surface)
        section_children, page_skipped = _flattened_section_children(page_section)
        skipped_expansions += page_skipped
        for child in section_children:
            base_section.append(child)

    ids = [element.get(XML_ID) for element in base_root.iter() if element.get(XML_ID)]
    duplicate_ids = sorted(xml_id for xml_id, count in Counter(ids).items() if count > 1)
    renumbered_measures, numbered_zones = (
        renumber_measures_and_zones(base_root, number_zones=number_measure_zones)
        if renumber_measures
        else (0, 0)
    )
    staff_names_written, staff_group_names_written, later_staff_names_removed = apply_initial_staff_names(
        base_root,
        staff_names=staff_names,
        staff_abbreviations=staff_abbreviations,
        staff_group_label=staff_group_label,
        staff_group_abbreviation=staff_group_abbreviation,
        keep_original_staff_names=keep_original_staff_names,
        names_only_at_start=staff_names_only_at_start,
    )
    normalized_single_layers = normalize_single_layer_numbers_to_one(base_root) if normalize_single_layer_numbers else 0
    _write_tree_with_original_preamble(base_tree, base_root, base_path, output_path)
    return CombineResult(
        output_path,
        duplicate_ids,
        skipped_expansions,
        renumbered_measures,
        numbered_zones,
        normalized_single_layers,
        staff_names_written,
        staff_group_names_written,
        later_staff_names_removed,
    )


def renumber_measures_and_zones(root: ET.Element, *, number_zones: bool = True) -> tuple[int, int]:
    zones_by_id = {
        element.get(XML_ID): element
        for element in root.iter()
        if local_name(element.tag) == "zone" and element.get(XML_ID)
    }
    renumbered_measures = 0
    numbered_zones = 0

    for measure_number, measure in enumerate(
        (element for element in root.iter() if local_name(element.tag) == "measure"),
        start=1,
    ):
        measure.set("n", str(measure_number))
        renumbered_measures += 1

        if not number_zones:
            continue
        for token in measure.get("facs", "").split():
            if not token.startswith("#"):
                continue
            zone = zones_by_id.get(token[1:])
            if zone is not None and zone.get("type") == "measure":
                zone.set("n", str(measure_number))
                numbered_zones += 1

    return renumbered_measures, numbered_zones


def normalize_single_layer_numbers_to_one(root: ET.Element) -> int:
    changed = 0
    for staff in root.iter():
        if local_name(staff.tag) != "staff":
            continue
        layers = [child for child in list(staff) if local_name(child.tag) == "layer"]
        if not layers:
            continue

        if len(layers) == 1:
            layer = layers[0]
            if layer.get("n") == "1":
                continue
            layer.set("n", "1")
            changed += 1
            continue

        numbered_layers: list[tuple[int, int]] = []
        missing_layers: list[tuple[int, ET.Element]] = []
        for index, layer in enumerate(layers, start=1):
            layer_n = layer.get("n")
            if not layer_n:
                missing_layers.append((index, layer))
                continue
            if not layer_n.isdigit():
                numbered_layers = []
                break
            numbered_layers.append((index, int(layer_n)))

        if not missing_layers or not numbered_layers:
            continue

        offsets = {layer_n - index for index, layer_n in numbered_layers}
        if len(offsets) != 1:
            continue

        offset = offsets.pop()
        used_numbers = {layer_n for _, layer_n in numbered_layers}
        for index, layer in missing_layers:
            inferred_n = index + offset
            if inferred_n <= 0 or inferred_n in used_numbers:
                continue
            layer.set("n", str(inferred_n))
            used_numbers.add(inferred_n)
            changed += 1
    return changed


def apply_initial_staff_names(
    root: ET.Element,
    *,
    staff_names: Mapping[str, str] | Sequence[str] | None = None,
    staff_abbreviations: Mapping[str, str] | Sequence[str] | None = None,
    staff_group_label: str | None = None,
    staff_group_abbreviation: str | None = None,
    keep_original_staff_names: bool = False,
    names_only_at_start: bool = True,
) -> tuple[int, int, int]:
    score_defs = [element for element in root.iter() if local_name(element.tag) == "scoreDef"]
    if not score_defs:
        return 0, 0, 0

    first_score_def = score_defs[0]
    original = _initial_staff_name_spec(first_score_def) if keep_original_staff_names else {}
    names = {**original.get("staff_names", {}), **_staff_text_map(staff_names)}
    abbreviations = {**original.get("staff_abbreviations", {}), **_staff_text_map(staff_abbreviations)}
    if staff_group_label is None:
        staff_group_label = original.get("staff_group_label")
    if staff_group_abbreviation is None:
        staff_group_abbreviation = original.get("staff_group_abbreviation")

    if not names and not abbreviations and staff_group_label is None and staff_group_abbreviation is None:
        later_removed = 0
        if names_only_at_start:
            for score_def in score_defs[1:]:
                later_removed += _remove_staff_name_children(score_def)
        return 0, 0, later_removed

    staff_names_written = 0
    for staff_def in first_score_def.iter():
        if local_name(staff_def.tag) != "staffDef":
            continue
        staff_n = staff_def.get("n", "")
        if staff_n in names:
            _set_text_child(staff_def, "label", names[staff_n])
            staff_names_written += 1
        if staff_n in abbreviations:
            _set_text_child(staff_def, "labelAbbr", abbreviations[staff_n])
            staff_names_written += 1

    staff_group_names_written = 0
    if staff_group_label is not None or staff_group_abbreviation is not None:
        first_staff_group = first_descendant(first_score_def, "staffGrp")
        if first_staff_group is not None:
            target_group = _last_staff_group_with_staff_defs(first_staff_group) or first_staff_group
            if staff_group_label is not None:
                _set_text_child(target_group, "label", staff_group_label)
                staff_group_names_written += 1
            if staff_group_abbreviation is not None:
                _set_text_child(target_group, "labelAbbr", staff_group_abbreviation)
                staff_group_names_written += 1

    later_removed = 0
    if names_only_at_start:
        for score_def in score_defs[1:]:
            later_removed += _remove_staff_name_children(score_def)

    return staff_names_written, staff_group_names_written, later_removed


def _initial_staff_name_spec(score_def: ET.Element) -> dict[str, dict[str, str] | str]:
    names: dict[str, str] = {}
    abbreviations: dict[str, str] = {}
    parent_map = {child: parent for parent in score_def.iter() for child in list(parent)}
    for staff_def in score_def.iter():
        if local_name(staff_def.tag) != "staffDef":
            continue
        staff_n = staff_def.get("n", "")
        if not staff_n:
            continue
        label = _name_text_for_staff_def(staff_def, "label", parent_map)
        label_abbr = _name_text_for_staff_def(staff_def, "labelAbbr", parent_map)
        if label:
            names[staff_n] = label
        if label_abbr:
            abbreviations[staff_n] = label_abbr

    target_group = None
    first_staff_group = first_descendant(score_def, "staffGrp")
    if first_staff_group is not None:
        target_group = _last_staff_group_with_staff_defs(first_staff_group) or first_staff_group
    spec: dict[str, dict[str, str] | str] = {
        "staff_names": names,
        "staff_abbreviations": abbreviations,
    }
    if target_group is not None:
        group_label = normalized_text(first_child(target_group, "label"))
        group_abbreviation = normalized_text(first_child(target_group, "labelAbbr"))
        if group_label:
            spec["staff_group_label"] = group_label
        if group_abbreviation:
            spec["staff_group_abbreviation"] = group_abbreviation
    return spec


def _name_text_for_staff_def(
    staff_def: ET.Element,
    tag: str,
    parent_map: Mapping[ET.Element, ET.Element],
) -> str:
    direct = normalized_text(first_child(staff_def, tag))
    if direct:
        return direct
    parent = parent_map.get(staff_def)
    if parent is not None and local_name(parent.tag) == "staffGrp":
        return normalized_text(first_child(parent, tag))
    return ""


def _staff_text_map(values: Mapping[str, str] | Sequence[str] | None) -> dict[str, str]:
    if values is None:
        return {}
    if isinstance(values, Mapping):
        return {str(key): str(value) for key, value in values.items() if value is not None}
    return {str(index): str(value) for index, value in enumerate(values, start=1) if value is not None}


def _set_text_child(parent: ET.Element, tag: str, text: str) -> ET.Element:
    child = first_child(parent, tag)
    if child is None:
        child = ET.Element(qname(tag))
        parent.insert(_staff_name_insert_index(parent, tag), child)
    child.text = text
    child.tail = None
    return child


def _staff_name_insert_index(parent: ET.Element, tag: str) -> int:
    children = list(parent)
    if tag == "labelAbbr":
        for index, child in enumerate(children):
            if local_name(child.tag) == "label":
                return index + 1
    if tag == "label" and local_name(parent.tag) == "staffGrp":
        for index, child in enumerate(children):
            if local_name(child.tag) != "grpSym":
                return index
        return len(children)
    return 0


def _last_staff_group_with_staff_defs(staff_group: ET.Element) -> ET.Element | None:
    groups = [
        element
        for element in staff_group.iter()
        if local_name(element.tag) == "staffGrp"
        and any(local_name(child.tag) == "staffDef" for child in list(element))
    ]
    return groups[-1] if groups else None


def _remove_staff_name_children(root: ET.Element) -> int:
    removed = 0
    for parent in root.iter():
        if local_name(parent.tag) not in {"staffDef", "staffGrp"}:
            continue
        for child in list(parent):
            if local_name(child.tag) in {"label", "labelAbbr"}:
                parent.remove(child)
                removed += 1
    return removed


def annotation_filter_description(
    *,
    severities: set[str],
    categories: set[str] | None,
    checks: set[str] | None,
    exclude_checks: set[str] | None,
    max_annotations: int,
) -> str:
    return (
        f"severities={sorted(severities)}, "
        f"categories={sorted(categories) if categories else 'all'}, "
        f"checks={sorted(checks) if checks else 'all'}, "
        f"exclude_checks={sorted(exclude_checks) if exclude_checks else 'none'}, "
        f"max_annotations={max_annotations}"
    )


def annotate_mei_from_report(
    mei_path: Path,
    report_df,
    output_path: Path,
    *,
    severities: set[str] | None = None,
    categories: set[str] | None = None,
    checks: set[str] | None = None,
    exclude_checks: set[str] | None = None,
    max_annotations: int = 100,
) -> AnnotationResult:
    severities = severities or {"error"}
    exclude_checks = exclude_checks or set()
    selected = report_df[report_df["severity"].isin(severities)].copy()
    if categories is not None:
        selected = selected[selected["category"].isin(categories)]
    if checks is not None:
        selected = selected[selected["check"].isin(checks)]
    if exclude_checks:
        selected = selected[~selected["check"].isin(exclude_checks)]

    capped = len(selected) > max_annotations
    selected = selected.head(max_annotations)

    tree = ET.parse(mei_path)
    root = tree.getroot()
    parent_map = _build_parent_map(root)
    id_map = {element.get(XML_ID): element for element in root.iter() if element.get(XML_ID)}
    section = first_descendant(root, "section") or root

    for parent in list(root.iter()):
        for child in list(parent):
            if local_name(child.tag) == "annot" and child.get(XML_ID, "").startswith("consistency_"):
                parent.remove(child)

    created = 0
    skipped = 0
    used_annot_ids: set[str] = set()
    for _, row in selected.iterrows():
        target_id = str(row.get("xml_id", "")).strip()
        target = id_map.get(target_id)
        if target is None:
            skipped += 1
            continue

        annot_id = _unique_annotation_id(_stable_annot_id(row), used_annot_ids)
        container = _nearest_ancestor(target, parent_map, "measure") or section
        annot = ET.Element(
            qname("annot"),
            {
                XML_ID: annot_id,
                "type": "mei-consistency-check",
                "plist": f"#{target_id}",
            },
        )
        annot_p = ET.SubElement(annot, qname("p"))
        annot_p.text = _annotation_text(row)
        container.append(annot)
        created += 1

    _write_tree_with_original_preamble(tree, root, mei_path, output_path)
    return AnnotationResult(output_path, created, skipped, capped)


def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def _nearest_ancestor(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    tag: str,
) -> ET.Element | None:
    current: ET.Element | None = element
    while current is not None:
        if local_name(current.tag) == tag:
            return current
        current = parent_map.get(current)
    return None


def _stable_annot_id(row) -> str:
    key = "|".join(str(row.get(field, "")) for field in ["check", "xml_id", "line", "actual", "message"])
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"consistency_{digest}"


def _unique_annotation_id(base_id: str, used_ids: set[str]) -> str:
    annot_id = base_id
    if annot_id in used_ids:
        suffix = 2
        while f"{annot_id}_{suffix}" in used_ids:
            suffix += 1
        annot_id = f"{annot_id}_{suffix}"
    used_ids.add(annot_id)
    return annot_id


def _annotation_text(row) -> str:
    bits = [f"{row['severity']}: {row['check']}"]
    for label in ("message", "actual", "expected", "context"):
        value = row.get(label)
        if value:
            bits.append(f"{label}={value}" if label != "message" else str(value))
    return " | ".join(bits)


def _write_tree_with_original_preamble(
    tree: ET.ElementTree,
    root: ET.Element,
    source_path: Path,
    target_path: Path,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="   ")
    preamble = source_path.read_text(encoding="utf-8").split("<mei", 1)[0]
    target_path.write_text(preamble + ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
