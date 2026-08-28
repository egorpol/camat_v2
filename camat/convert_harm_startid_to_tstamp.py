#!/usr/bin/env python3
"""Convert MEI figured-bass harmonies from startid anchors to staff+tstamp.

The converter is intentionally conservative. It derives each figured-bass
``<harm startid="#...">`` timestamp from the referenced timed event, preserves
an explicit ``staff`` value when present, and skips cross-measure references by
default because their intent is ambiguous. An optional normalization pass
replaces ASCII ``b`` and ``#`` accidentals in figured-bass ``<f>`` text with
the musical symbols ``♭`` and ``♯``.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable


MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
TIMED_EVENTS = {"note", "rest", "space", "mRest", "mSpace", "chord"}
CONTAINER_EVENTS = {"layer", "beam", "tuplet", "bTrem", "fTrem"}

ET.register_namespace("", MEI_NS)

HARM_OPEN_RE = re.compile(r"<harm\b(?P<attrs>[^>]*)>")
FB_BLOCK_RE = re.compile(r"<fb\b[^>]*>.*?</fb>", re.S)
F_TEXT_RE = re.compile(r"(<f\b[^>]*>)(?P<text>[^<]*)(</f>)")
ATTR_RE = re.compile(r'([A-Za-z_:][\w:.-]*)="([^"]*)"')
XML_ID_RE = re.compile(r'xml:id="([^"]+)"')
ASCII_FLAT_RE = re.compile(r"(?<![A-Za-z])b(?![A-Za-z])")


@dataclass(frozen=True)
class HarmConversion:
    file: str
    line: int | None
    status: str
    startid: str
    tstamp: str = ""
    staff: str = ""
    target_staff: str = ""
    measure_n: str = ""
    target_measure_n: str = ""
    target_kind: str = ""
    figure_text: str = ""
    normalized_figure: str = ""
    message: str = ""


@dataclass(frozen=True)
class ConversionResult:
    path: Path
    changed: bool
    applied: bool
    converted: int
    normalized_accidentals: int
    skipped: int
    unresolved: int
    rows: list[HarmConversion]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def format_tstamp(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    as_float = float(value)
    if as_float.is_integer():
        return str(int(as_float))
    return "%g" % as_float


def dotted_duration_beats(element: ET.Element, meter_unit: int) -> Fraction | None:
    dur = element.get("dur")
    if dur is None:
        return None
    base = Fraction(meter_unit, int(dur))
    total = base
    addition = base
    for _ in range(int(element.get("dots", "0"))):
        addition /= 2
        total += addition
    return total


def tuplet_scale(element: ET.Element) -> Fraction:
    if local_name(element.tag) != "tuplet":
        return Fraction(1)
    num = element.get("num")
    numbase = element.get("numbase")
    if not num or not numbase:
        return Fraction(1)
    return Fraction(int(numbase), int(num))


def scan_line_numbers(text: str) -> tuple[dict[str, int], dict[int, int]]:
    id_lines: dict[str, int] = {}
    harm_startid_lines: dict[int, int] = {}
    harm_startid_index = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in XML_ID_RE.finditer(line):
            id_lines.setdefault(match.group(1), line_number)
        if re.search(r"<harm\b[^>]*\bstartid=", line):
            harm_startid_lines[harm_startid_index] = line_number
            harm_startid_index += 1
    return id_lines, harm_startid_lines


def ancestor(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    name: str,
) -> ET.Element | None:
    current = element
    while current in parent_map:
        current = parent_map[current]
        if local_name(current.tag) == name:
            return current
    return None


def active_meter_by_measure(root: ET.Element) -> dict[ET.Element, dict[str, int]]:
    current = {"count": 4, "unit": 4}
    meters: dict[ET.Element, dict[str, int]] = {}
    for element in root.iter():
        if local_name(element.tag) == "meterSig":
            if element.get("count") and element.get("unit"):
                current = {
                    "count": int(element.get("count", "4")),
                    "unit": int(element.get("unit", "4")),
                }
        elif local_name(element.tag) == "measure":
            meters[element] = current.copy()
    return meters


def collect_timing(
    root: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> dict[str, tuple[ET.Element, str, Fraction, str]]:
    timing: dict[str, tuple[ET.Element, str, Fraction, str]] = {}
    measure_meters = active_meter_by_measure(root)

    def record(element: ET.Element, measure: ET.Element, staff_n: str, start: Fraction) -> None:
        xml_id = element.get(XML_ID)
        kind = local_name(element.tag)
        if xml_id:
            timing[xml_id] = (measure, staff_n, start, kind)
        if kind == "chord":
            for child in element:
                if local_name(child.tag) == "note" and child.get(XML_ID):
                    timing[child.get(XML_ID)] = (measure, staff_n, start, "note-in-chord")

    def walk(
        container: ET.Element,
        position: Fraction,
        scale: Fraction,
        measure: ET.Element,
        staff_n: str,
        meter_unit: int,
    ) -> Fraction:
        for child in container:
            kind = local_name(child.tag)
            if kind in TIMED_EVENTS:
                record(child, measure, staff_n, position)
                duration = dotted_duration_beats(child, meter_unit)
                if duration is not None:
                    position += duration * scale
            elif kind in CONTAINER_EVENTS:
                position = walk(child, position, scale * tuplet_scale(child), measure, staff_n, meter_unit)
        return position

    for measure in [element for element in root.iter() if local_name(element.tag) == "measure"]:
        meter_unit = measure_meters.get(measure, {"unit": 4})["unit"]
        for staff in [child for child in measure if local_name(child.tag) == "staff"]:
            staff_n = staff.get("n", "")
            for layer in [child for child in staff if local_name(child.tag) == "layer"]:
                walk(layer, Fraction(1), Fraction(1), measure, staff_n, meter_unit)

    return timing


def parse_attrs(raw_attrs: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in ATTR_RE.finditer(raw_attrs)]


def render_harm_open(attrs: list[tuple[str, str]], tstamp: str, staff: str) -> str:
    rendered: list[tuple[str, str]] = []
    wrote_tstamp = False
    wrote_staff = False

    for name, value in attrs:
        if name == "startid":
            rendered.append(("tstamp", tstamp))
            wrote_tstamp = True
        elif name == "tstamp":
            rendered.append((name, tstamp))
            wrote_tstamp = True
        elif name == "staff":
            rendered.append((name, value or staff))
            wrote_staff = True
        else:
            rendered.append((name, value))

    if not wrote_tstamp:
        rendered.append(("tstamp", tstamp))
    if not wrote_staff:
        rendered.append(("staff", staff))

    attr_text = " ".join(f'{name}="{value}"' for name, value in rendered)
    return f"<harm {attr_text}>"


def build_rows(path: Path, text: str) -> tuple[list[HarmConversion], dict[int, HarmConversion]]:
    root = ET.fromstring(text)
    parent_map = {child: element for element in root.iter() for child in element}
    timing = collect_timing(root, parent_map)
    _id_lines, harm_startid_lines = scan_line_numbers(text)
    rows: list[HarmConversion] = []
    by_index: dict[int, HarmConversion] = {}

    harm_startid_index = 0
    for harm in [element for element in root.iter() if local_name(element.tag) == "harm" and element.get("startid")]:
        startid = harm.get("startid", "").lstrip("#")
        line = harm_startid_lines.get(harm_startid_index)
        harm_measure = ancestor(harm, parent_map, "measure")
        measure_n = harm_measure.get("n", "") if harm_measure is not None else ""
        explicit_staff = harm.get("staff", "")

        if startid not in timing:
            row = HarmConversion(
                file=path.as_posix(),
                line=line,
                status="unresolved",
                startid=startid,
                measure_n=measure_n,
                message="startid target is missing or not a timed event",
            )
        else:
            target_measure, target_staff, start, target_kind = timing[startid]
            target_measure_n = target_measure.get("n", "")
            staff = explicit_staff or target_staff
            if harm_measure is not target_measure:
                row = HarmConversion(
                    file=path.as_posix(),
                    line=line,
                    status="skipped_cross_measure",
                    startid=startid,
                    tstamp=format_tstamp(start),
                    staff=staff,
                    target_staff=target_staff,
                    measure_n=measure_n,
                    target_measure_n=target_measure_n,
                    target_kind=target_kind,
                    message="harm and startid target are in different measures",
                )
            else:
                row = HarmConversion(
                    file=path.as_posix(),
                    line=line,
                    status="convert",
                    startid=startid,
                    tstamp=format_tstamp(start),
                    staff=staff,
                    target_staff=target_staff,
                    measure_n=measure_n,
                    target_measure_n=target_measure_n,
                    target_kind=target_kind,
                )

        rows.append(row)
        by_index[harm_startid_index] = row
        harm_startid_index += 1

    return rows, by_index


def convert_text(text: str, conversions: dict[int, HarmConversion]) -> tuple[str, int]:
    harm_startid_index = 0
    converted = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal harm_startid_index, converted
        raw_attrs = match.group("attrs")
        attrs = parse_attrs(raw_attrs)
        if not any(name == "startid" for name, _value in attrs):
            return match.group(0)

        row = conversions.get(harm_startid_index)
        harm_startid_index += 1
        if row is None or row.status != "convert":
            return match.group(0)

        converted += 1
        return render_harm_open(attrs, row.tstamp, row.staff)

    return HARM_OPEN_RE.sub(replace, text), converted


def normalize_figure_text(text: str) -> str:
    """Replace ASCII figured-bass accidentals with musical symbols."""
    return ASCII_FLAT_RE.sub("♭", text).replace("#", "♯")


def normalize_figured_bass_accidentals(
    path: Path,
    text: str,
) -> tuple[str, list[HarmConversion]]:
    """Normalize accidental characters only in plain text inside <fb>/<f>."""
    rows: list[HarmConversion] = []

    def replace_fb(fb_match: re.Match[str]) -> str:
        block = fb_match.group(0)

        def replace_figure(figure_match: re.Match[str]) -> str:
            current = figure_match.group("text")
            normalized = normalize_figure_text(current)
            if normalized == current:
                return figure_match.group(0)

            absolute_offset = fb_match.start() + figure_match.start("text")
            rows.append(
                HarmConversion(
                    file=path.as_posix(),
                    line=line_number(text, absolute_offset),
                    status="normalize_accidental",
                    startid="",
                    figure_text=current,
                    normalized_figure=normalized,
                    message="ASCII figured-bass accidental should use a musical symbol",
                )
            )
            return f"{figure_match.group(1)}{normalized}{figure_match.group(3)}"

        return F_TEXT_RE.sub(replace_figure, block)

    return FB_BLOCK_RE.sub(replace_fb, text), rows


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def convert_file(
    path: Path,
    apply: bool = False,
    normalize_accidentals: bool = False,
) -> ConversionResult:
    text = path.read_text(encoding="utf-8")
    rows, by_index = build_rows(path, text)
    new_text, converted = convert_text(text, by_index)
    accidental_rows: list[HarmConversion] = []
    if normalize_accidentals:
        new_text, accidental_rows = normalize_figured_bass_accidentals(path, new_text)
        rows.extend(accidental_rows)
    changed = new_text != text
    if apply and changed:
        path.write_text(new_text, encoding="utf-8")
        ET.parse(path)

    status_counts = Counter(row.status for row in rows)
    return ConversionResult(
        path=path,
        changed=changed,
        applied=apply and changed,
        converted=converted,
        normalized_accidentals=len(accidental_rows),
        skipped=status_counts["skipped_cross_measure"],
        unresolved=status_counts["unresolved"],
        rows=rows,
    )


def write_report(rows: Iterable[HarmConversion], output: Path) -> None:
    fieldnames = list(HarmConversion.__dataclass_fields__)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert MEI <harm startid> figured bass anchors to staff+tstamp."
    )
    parser.add_argument("paths", nargs="+", help="MEI file(s) to convert.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite files. Without this flag the command only reports changes.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional CSV report path.",
    )
    parser.add_argument(
        "--normalize-accidentals",
        action="store_true",
        help="Replace ASCII b/# in figured-bass <f> text with ♭/♯.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    all_rows: list[HarmConversion] = []
    results: list[ConversionResult] = []

    for raw_path in args.paths:
        path = Path(raw_path)
        result = convert_file(
            path,
            apply=args.apply,
            normalize_accidentals=args.normalize_accidentals,
        )
        results.append(result)
        all_rows.extend(result.rows)

    for result in results:
        mode = "applied" if result.applied else "dry-run"
        print(
            f"{result.path}: {mode}; converted={result.converted}, "
            f"accidentals={result.normalized_accidentals}, "
            f"skipped={result.skipped}, unresolved={result.unresolved}"
        )

    if args.report:
        write_report(all_rows, args.report)
        print(f"Wrote report to {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
