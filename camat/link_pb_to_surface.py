#!/usr/bin/env python3
"""Link MEI page breaks to facsimile surfaces.

For each ``<pb>`` this derives the facsimile surface from the first following
``<measure>``: measure ``@facs`` -> ``<zone>`` -> parent ``<surface>``.
The default mode reports missing or mismatched links without changing files.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PB_RE = re.compile(r"<pb\b(?P<attrs>[^>]*)/>")
SURFACE_RE = re.compile(r"<surface\b(?P<attrs>[^>]*)>(?P<body>.*?)</surface>", re.S)
ZONE_RE = re.compile(r"<zone\b(?P<attrs>[^>]*)>")
MEASURE_RE = re.compile(r"<measure\b(?P<attrs>[^>]*)>")
ATTR_RE = re.compile(r'([A-Za-z_:][\w:.-]*)="([^"]*)"')


@dataclass(frozen=True)
class PbSurfaceRow:
    file: str
    line: int | None
    status: str
    pb_id: str = ""
    current_facs: str = ""
    expected_facs: str = ""
    measure_n: str = ""
    zone_id: str = ""
    message: str = ""


@dataclass(frozen=True)
class PbSurfaceResult:
    path: Path
    changed: bool
    applied: bool
    updates: int
    mismatches: int
    unresolved: int
    rows: list[PbSurfaceRow]


def parse_attrs(raw_attrs: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in ATTR_RE.finditer(raw_attrs)]


def attr_value(raw_attrs: str, name: str) -> str:
    for attr_name, value in parse_attrs(raw_attrs):
        if attr_name == name:
            return value
    return ""


def line_number(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def build_zone_surface_map(text: str) -> dict[str, str]:
    zone_to_surface: dict[str, str] = {}
    for surface_match in SURFACE_RE.finditer(text):
        surface_id = attr_value(surface_match.group("attrs"), "xml:id")
        if not surface_id:
            continue
        for zone_match in ZONE_RE.finditer(surface_match.group("body")):
            zone_id = attr_value(zone_match.group("attrs"), "xml:id")
            if zone_id:
                zone_to_surface[zone_id] = surface_id
    return zone_to_surface


def render_pb_open(raw_attrs: str, expected_facs: str, overwrite: bool) -> str:
    attrs = parse_attrs(raw_attrs)
    rendered: list[tuple[str, str]] = []
    wrote_facs = False
    for name, value in attrs:
        if name == "facs":
            rendered.append((name, f"#{expected_facs}" if overwrite else value))
            wrote_facs = True
        else:
            rendered.append((name, value))
    if not wrote_facs:
        rendered.append(("facs", f"#{expected_facs}"))
    return "<pb " + " ".join(f'{name}="{value}"' for name, value in rendered) + " />"


def analyze_file(path: Path) -> tuple[str, list[PbSurfaceRow], dict[int, PbSurfaceRow]]:
    text = path.read_text(encoding="utf-8")
    zone_to_surface = build_zone_surface_map(text)
    rows: list[PbSurfaceRow] = []
    by_index: dict[int, PbSurfaceRow] = {}

    for index, pb_match in enumerate(PB_RE.finditer(text)):
        raw_attrs = pb_match.group("attrs")
        pb_id = attr_value(raw_attrs, "xml:id")
        current_facs = attr_value(raw_attrs, "facs").lstrip("#")
        following_text = text[pb_match.end() :]
        measure_match = MEASURE_RE.search(following_text)
        line = line_number(text, pb_match.start())

        if not measure_match:
            row = PbSurfaceRow(
                file=path.as_posix(),
                line=line,
                status="unresolved",
                pb_id=pb_id,
                current_facs=current_facs,
                message="No following measure found for page break.",
            )
        else:
            measure_attrs = measure_match.group("attrs")
            measure_n = attr_value(measure_attrs, "n")
            zone_id = attr_value(measure_attrs, "facs").lstrip("#")
            expected_facs = zone_to_surface.get(zone_id, "")
            if not zone_id or not expected_facs:
                row = PbSurfaceRow(
                    file=path.as_posix(),
                    line=line,
                    status="unresolved",
                    pb_id=pb_id,
                    current_facs=current_facs,
                    measure_n=measure_n,
                    zone_id=zone_id,
                    message="Following measure has no resolvable facsimile zone.",
                )
            elif not current_facs:
                row = PbSurfaceRow(
                    file=path.as_posix(),
                    line=line,
                    status="missing",
                    pb_id=pb_id,
                    expected_facs=expected_facs,
                    measure_n=measure_n,
                    zone_id=zone_id,
                    message="Page break has no @facs link to the source surface.",
                )
            elif current_facs != expected_facs:
                row = PbSurfaceRow(
                    file=path.as_posix(),
                    line=line,
                    status="mismatch",
                    pb_id=pb_id,
                    current_facs=current_facs,
                    expected_facs=expected_facs,
                    measure_n=measure_n,
                    zone_id=zone_id,
                    message="Page break @facs does not match the following measure's source surface.",
                )
            else:
                row = PbSurfaceRow(
                    file=path.as_posix(),
                    line=line,
                    status="ok",
                    pb_id=pb_id,
                    current_facs=current_facs,
                    expected_facs=expected_facs,
                    measure_n=measure_n,
                    zone_id=zone_id,
                )

        rows.append(row)
        by_index[index] = row

    return text, rows, by_index


def link_file(path: Path, apply: bool = False, overwrite: bool = False) -> PbSurfaceResult:
    text, rows, by_index = analyze_file(path)
    pb_index = 0
    updates = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal pb_index, updates
        row = by_index[pb_index]
        pb_index += 1
        if row.status == "missing" or (overwrite and row.status == "mismatch"):
            updates += 1
            return render_pb_open(match.group("attrs"), row.expected_facs, overwrite=True)
        return match.group(0)

    new_text = PB_RE.sub(replace, text)
    changed = new_text != text
    if apply and changed:
        path.write_text(new_text, encoding="utf-8")
        ET.parse(path)

    mismatches = sum(1 for row in rows if row.status == "mismatch")
    unresolved = sum(1 for row in rows if row.status == "unresolved")
    return PbSurfaceResult(
        path=path,
        changed=changed,
        applied=apply and changed,
        updates=updates,
        mismatches=mismatches,
        unresolved=unresolved,
        rows=rows,
    )


def write_report(rows: Iterable[PbSurfaceRow], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PbSurfaceRow.__dataclass_fields__))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Link MEI <pb> elements to facsimile <surface> ids.")
    parser.add_argument("paths", nargs="+", help="MEI file(s) to check or update.")
    parser.add_argument("--apply", action="store_true", help="Rewrite files.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="When applying, replace existing mismatched pb@facs values.",
    )
    parser.add_argument("--report", type=Path, help="Optional CSV report path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    all_rows: list[PbSurfaceRow] = []
    for raw_path in args.paths:
        result = link_file(Path(raw_path), apply=args.apply, overwrite=args.overwrite)
        all_rows.extend(result.rows)
        mode = "applied" if result.applied else "dry-run"
        print(
            f"{result.path}: {mode}; updates={result.updates}, "
            f"mismatches={result.mismatches}, unresolved={result.unresolved}"
        )
    if args.report:
        write_report(all_rows, args.report)
        print(f"Wrote report to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
