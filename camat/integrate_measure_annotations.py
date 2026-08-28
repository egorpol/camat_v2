#!/usr/bin/env python3
"""
Integrate measure annotations MEI into a main MEI file.

Usage:
    camat-integrate-annotation-file INPUT_MEI ANNOTATIONS_MEI OUTPUT_MEI
    camat-integrate-annotation-file INPUT_MEI ANNOTATIONS_MEI OUTPUT_MEI --force

Example for this repo:
    camat-integrate-annotation-file \
        Demo/bsb00023116_00019.mei \
        Demo/bsb00023116_00019_measure_annotations.xml \
        Demo/bsb00023116_00019_facs_zones.mei
"""

from __future__ import annotations

import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MEI_NS = "http://www.music-encoding.org/ns/mei"
NSMAP = {"m": MEI_NS}
MEI = f"{{{MEI_NS}}}"

ET.register_namespace("", MEI_NS)


def parse_mei(path: str) -> ET.ElementTree:
    return ET.parse(path)


def find_single(root: ET.Element, xpath: str):
    return root.find(xpath, NSMAP)


def get_body_measures(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//m:body//m:measure", NSMAP)


def get_measure_numbers(measures: list[ET.Element]) -> list[str]:
    return [n.strip() for n in (measure.get("n") for measure in measures) if n and n.strip()]


def get_zone_count(root: ET.Element) -> int:
    return len(root.findall(".//m:facsimile//m:zone[@type='measure']", NSMAP))


def summarize_numbers(numbers: list[str], limit: int = 8) -> str:
    if not numbers:
        return "[]"
    if len(numbers) <= limit:
        return "[" + ", ".join(numbers) + "]"
    head = ", ".join(numbers[: limit // 2])
    tail = ", ".join(numbers[-(limit // 2) :])
    return f"[{head}, ..., {tail}]"


def get_measure_alignment_report(main_root: ET.Element, ann_root: ET.Element) -> dict[str, object]:
    main_measures = get_body_measures(main_root)
    ann_measures = get_body_measures(ann_root)

    main_numbers = get_measure_numbers(main_measures)
    ann_numbers = get_measure_numbers(ann_measures)
    zone_count = get_zone_count(ann_root)

    if not main_measures:
        raise RuntimeError("Main MEI does not contain any <measure> elements in <body>.")
    if not ann_measures:
        raise RuntimeError("Annotations MEI does not contain any <measure> elements in <body>.")
    if len(main_measures) != len(main_numbers):
        raise RuntimeError("Main MEI contains <measure> elements without @n attributes.")
    if len(ann_measures) != len(ann_numbers):
        raise RuntimeError("Annotations MEI contains <measure> elements without @n attributes.")
    if len(set(main_numbers)) != len(main_numbers):
        raise RuntimeError("Main MEI contains duplicate measure @n values.")
    if len(set(ann_numbers)) != len(ann_numbers):
        raise RuntimeError("Annotations MEI contains duplicate measure @n values.")
    if zone_count != len(ann_measures):
        raise RuntimeError(
            "Annotations MEI is internally inconsistent: "
            f"{len(ann_measures)} annotated measures but {zone_count} measure zones."
        )
    ann_number_set = set(ann_numbers)
    main_number_set = set(main_numbers)
    main_only = [number for number in main_numbers if number not in ann_number_set]
    ann_only = [number for number in ann_numbers if number not in main_number_set]
    return {
        "main_numbers": main_numbers,
        "ann_numbers": ann_numbers,
        "zone_count": zone_count,
        "mismatch_count": len(main_only) + len(ann_only),
        "main_only": main_only,
        "ann_only": ann_only,
    }


def validate_measure_alignment(
    main_root: ET.Element,
    ann_root: ET.Element,
    *,
    max_measure_mismatch: int | None = 0,
) -> dict[str, object]:
    report = get_measure_alignment_report(main_root, ann_root)
    main_numbers = report["main_numbers"]
    ann_numbers = report["ann_numbers"]
    mismatch_count = report["mismatch_count"]

    if max_measure_mismatch is None:
        return report

    if mismatch_count > max_measure_mismatch:
        raise RuntimeError(
            "Measure numbering does not align between the source and annotations MEI. "
            f"mismatch count={mismatch_count}, allowed={max_measure_mismatch}; "
            f"source count={len(main_numbers)} numbers={summarize_numbers(main_numbers)}; "
            f"annotations count={len(ann_numbers)} numbers={summarize_numbers(ann_numbers)}"
        )

    return report


def integrate_facsimile(
    main_root: ET.Element,
    ann_root: ET.Element,
    graphic_target_prefix: str = "img/",
    graphic_target_override: str | None = None,
) -> None:
    main_music = find_single(main_root, "./m:music")
    ann_music = find_single(ann_root, "./m:music")
    if main_music is None or ann_music is None:
        raise RuntimeError("Both MEI documents must contain a <music> element.")

    ann_facsimile = find_single(ann_music, "./m:facsimile")
    if ann_facsimile is None:
        raise RuntimeError("Annotations MEI does not contain a <facsimile> element.")

    facsimile_copy = copy.deepcopy(ann_facsimile)

    graphic = facsimile_copy.find(".//m:graphic", NSMAP)
    if graphic is not None:
        if graphic_target_override:
            graphic.set("target", graphic_target_override)
        else:
            target = graphic.get("target")
            if (
                graphic_target_prefix
                and target
                and not target.startswith(graphic_target_prefix)
                and "://" not in target
                and "/" not in target
            ):
                graphic.set("target", f"{graphic_target_prefix}{target}")

    existing_facsimile = find_single(main_music, "./m:facsimile")
    if existing_facsimile is not None:
        children = list(main_music)
        idx = children.index(existing_facsimile)
        main_music.remove(existing_facsimile)
        main_music.insert(idx, facsimile_copy)
        return

    body = find_single(main_music, "./m:body")
    if body is not None:
        children = list(main_music)
        idx = children.index(body)
        main_music.insert(idx, facsimile_copy)
    else:
        main_music.append(facsimile_copy)


def integrate_measure_facs(main_root: ET.Element, ann_root: ET.Element) -> None:
    facs_by_n = {}
    for measure in get_body_measures(ann_root):
        n = measure.get("n")
        facs = measure.get("facs")
        if n and facs:
            facs_by_n[n.strip()] = facs

    if not facs_by_n:
        raise RuntimeError("Annotations MEI does not contain any measure @facs bindings.")

    for measure in get_body_measures(main_root):
        n = measure.get("n")
        if not n:
            continue
        facs = facs_by_n.get(n.strip())
        if facs:
            measure.set("facs", facs)


def read_processing_instructions(path: str) -> list[str]:
    instructions: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("<?xml "):
            continue
        if stripped.startswith("<?") and stripped.endswith("?>"):
            instructions.append(stripped)
            continue
        if stripped:
            break
    return instructions


def write_mei(tree: ET.ElementTree, output_path: str, processing_instructions: list[str]) -> None:
    if hasattr(ET, "indent"):
        ET.indent(tree, space="   ")

    root_bytes = ET.tostring(tree.getroot(), encoding="utf-8")
    with Path(output_path).open("wb") as handle:
        handle.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        for instruction in processing_instructions:
            handle.write(f"{instruction}\n".encode("utf-8"))
        handle.write(root_bytes)
        handle.write(b"\n")


def integrate_annotation_file(
    input_mei: str,
    annotations_mei: str,
    output_mei: str,
    *,
    max_measure_mismatch: int | None = 0,
    graphic_target_prefix: str = "img/",
    graphic_target_override: str | None = None,
) -> None:
    main_tree = parse_mei(input_mei)
    ann_tree = parse_mei(annotations_mei)

    main_root = main_tree.getroot()
    ann_root = ann_tree.getroot()

    validate_measure_alignment(
        main_root,
        ann_root,
        max_measure_mismatch=max_measure_mismatch,
    )

    integrate_facsimile(
        main_root,
        ann_root,
        graphic_target_prefix=graphic_target_prefix,
        graphic_target_override=graphic_target_override,
    )
    integrate_measure_facs(main_root, ann_root)

    write_mei(main_tree, output_mei, read_processing_instructions(input_mei))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_mei", help="Path to the source MEI file")
    parser.add_argument("annotations_mei", help="Path to the annotations MEI file")
    parser.add_argument("output_mei", help="Path to write the integrated MEI file")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow any amount of source-vs-annotation measure mismatch",
    )
    parser.add_argument(
        "--max-measure-mismatch",
        type=int,
        default=0,
        help="Maximum number of unmatched measure numbers allowed during integration",
    )
    parser.add_argument(
        "--graphic-target-prefix",
        default="img/",
        help='Prefix added to bare <graphic @target> values (default: "img/")',
    )
    return parser


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        integrate_annotation_file(
            args.input_mei,
            args.annotations_mei,
            args.output_mei,
            max_measure_mismatch=None if args.force else args.max_measure_mismatch,
            graphic_target_prefix=args.graphic_target_prefix,
        )
    except Exception as exc:  # pragma: no cover - CLI error path
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
