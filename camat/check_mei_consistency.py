#!/usr/bin/env python3
"""
Automated proofreading checks for MEI files.

The checks are intentionally conservative: they report likely inconsistencies
with enough file, line, measure, staff, layer, and xml:id context to inspect the
source quickly.

Usage:
    camat-check-mei Demo/finished_material
    camat-check-mei Demo/finished_material --output mei_report.csv --json mei_report.json
    camat-check-mei Demo/finished_material --check-ppq
    camat-check-mei Demo/finished_material --strip-ppq-output Demo/finished_material_no_ppq
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable


MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"

TIMED_EVENTS = {"note", "rest", "chord", "space", "mRest", "mSpace"}
PITCHED_EVENTS = {"note"}
REFERENCE_ATTRS = {
    "facs",
    "startid",
    "endid",
    "target",
    "plist",
    "corresp",
    "sameas",
    "next",
    "prev",
    "copyof",
    "synch",
    "decls",
}
VALID_DURS = {
    "maxima",
    "long",
    "breve",
    "1",
    "2",
    "4",
    "8",
    "16",
    "32",
    "64",
    "128",
    "256",
    "512",
    "1024",
}
VALID_PNAMES = set("abcdefg")
GENERIC_LABEL_RE = re.compile(r"^(system|part|prt)\s*\.?\s*\d*$", re.I)


@dataclass
class Finding:
    severity: str
    category: str
    check: str
    file: str
    line: int | None
    element: str
    measure_n: str
    staff_n: str
    layer_n: str
    xml_id: str
    message: str
    expected: str = ""
    actual: str = ""
    context: str = ""


class MeiChecker:
    def __init__(
        self,
        path: Path,
        root_dir: Path,
        check_ppq: bool = False,
        publication_profile: bool = False,
        corpus_id_locations: dict[str, list[str]] | None = None,
    ):
        self.path = path.resolve()
        self.root_dir = root_dir.resolve()
        try:
            self.rel_path = self.path.relative_to(self.root_dir).as_posix()
        except ValueError:
            self.rel_path = self.path.name
        self.check_ppq = check_ppq
        self.publication_profile = publication_profile
        self.corpus_id_locations = corpus_id_locations or {}
        self.text = self.path.read_text(encoding="utf-8")
        self.lines = self.text.splitlines()
        self.id_lines = self._scan_xml_id_lines()
        self.findings: list[Finding] = []
        self.root: ET.Element | None = None
        self.parent: dict[ET.Element, ET.Element] = {}
        self.current_staff_defs: dict[str, dict[str, str]] = {}
        self.initial_staff_defs: dict[str, dict[str, str]] = {}
        self.ids: dict[str, ET.Element] = {}
        self.staff_records: list[dict[str, str]] = []
        self.term_records: list[dict[str, str]] = []

    def add(
        self,
        severity: str,
        category: str,
        check: str,
        element: ET.Element | None,
        message: str,
        expected: str = "",
        actual: str = "",
        context: str = "",
        measure_n: str = "",
        staff_n: str = "",
        layer_n: str = "",
        line: int | None = None,
    ) -> None:
        if element is not None:
            xml_id = element.get(XML_ID, "")
            element_name = local_name(element.tag)
            line = line if line is not None else self.line_for(element)
            measure_n = measure_n or ancestor_attr(element, self.parent, "measure", "n")
            staff_n = staff_n or ancestor_attr(element, self.parent, "staff", "n") or element.get("staff", "")
            layer_n = layer_n or ancestor_attr(element, self.parent, "layer", "n")
        else:
            xml_id = ""
            element_name = ""
        self.findings.append(
            Finding(
                severity=severity,
                category=category,
                check=check,
                file=self.rel_path,
                line=line,
                element=element_name,
                measure_n=measure_n or "",
                staff_n=staff_n or "",
                layer_n=layer_n or "",
                xml_id=xml_id,
                message=message,
                expected=expected,
                actual=actual,
                context=context,
            )
        )

    def run(self) -> tuple[list[Finding], list[dict[str, str]], list[dict[str, str]]]:
        self._check_duplicate_xml_ids()
        try:
            self.root = ET.fromstring(self.text)
        except ET.ParseError as exc:
            line = getattr(exc, "position", ("", None))[0]
            self.add(
                "error",
                "xml",
                "well_formed_xml",
                None,
                f"XML parser error: {exc}",
                line=line,
            )
            return self.findings, self.staff_records, self.term_records

        self.parent = {child: parent for parent in self.root.iter() for child in list(parent)}
        self.ids = {el.get(XML_ID): el for el in self.root.iter() if el.get(XML_ID)}

        self._check_root()
        if self.publication_profile:
            self._check_publication_profile()
        self._check_references()
        self._check_facsimile_zones()
        if self.publication_profile:
            self._check_facsimile_page_structure()
            self._check_empty_structural_elements()
        self._walk_score_for_meters_and_measures()
        self._check_terms()
        self._collect_staff_records()

        return self.findings, self.staff_records, self.term_records

    def _scan_xml_id_lines(self) -> dict[str, int]:
        id_lines: dict[str, int] = {}
        pattern = re.compile(r'\bxml:id\s*=\s*["\']([^"\']+)["\']')
        for line_no, line in enumerate(self.lines, start=1):
            for match in pattern.finditer(line):
                id_lines.setdefault(match.group(1), line_no)
        return id_lines

    def line_for(self, element: ET.Element | None) -> int | None:
        if element is None:
            return None
        xml_id = element.get(XML_ID)
        if xml_id:
            return self.id_lines.get(xml_id)
        for descendant in element.iter():
            if descendant is element:
                continue
            xml_id = descendant.get(XML_ID)
            if xml_id and xml_id in self.id_lines:
                return self.id_lines[xml_id]
        current = self.parent.get(element)
        while current is not None:
            xml_id = current.get(XML_ID)
            if xml_id and xml_id in self.id_lines:
                return self.id_lines[xml_id]
            current = self.parent.get(current)
        return None

    def _check_duplicate_xml_ids(self) -> None:
        seen: dict[str, int] = {}
        pattern = re.compile(r'\bxml:id\s*=\s*["\']([^"\']+)["\']')
        for line_no, line in enumerate(self.lines, start=1):
            for match in pattern.finditer(line):
                xml_id = match.group(1)
                if xml_id in seen:
                    self.add(
                        "error",
                        "xml",
                        "duplicate_xml_id",
                        None,
                        f"Duplicate xml:id '{xml_id}'. First occurrence is on line {seen[xml_id]}.",
                        actual=xml_id,
                        line=line_no,
                    )
                else:
                    seen[xml_id] = line_no

    def _check_root(self) -> None:
        assert self.root is not None
        if local_name(self.root.tag) != "mei" or namespace(self.root.tag) != MEI_NS:
            self.add(
                "error",
                "mei",
                "root_element",
                self.root,
                "Root element is not MEI in the expected MEI namespace.",
                expected=f"{{{MEI_NS}}}mei",
                actual=self.root.tag,
            )
        version = self.root.get("meiversion", "")
        if not version:
            self.add("warning", "mei", "mei_version", self.root, "Missing @meiversion on root <mei>.")
        elif version not in {"5.1", "5.1+CMN"}:
            self.add(
                "info",
                "mei",
                "mei_version",
                self.root,
                "MEI version differs from the project files inspected here.",
                expected="5.1 or 5.1+CMN",
                actual=version,
            )

    def _check_publication_profile(self) -> None:
        """Check project-level publication metadata beyond generic MEI validity."""
        assert self.root is not None

        model_pis = re.findall(r"<\?xml-model\s+([^?]+)\?>", self.text)
        has_cmn_rng = any(
            "mei-CMN.rng" in pi and "http://relaxng.org/ns/structure/1.0" in pi
            for pi in model_pis
        )
        has_cmn_schematron = any(
            "mei-CMN.rng" in pi and "http://purl.oclc.org/dsdl/schematron" in pi
            for pi in model_pis
        )
        for present, check, scheme in (
            (has_cmn_rng, "cmn_relaxng_pi", "RELAX NG"),
            (has_cmn_schematron, "cmn_schematron_pi", "Schematron"),
        ):
            if not present:
                self.add(
                    "error",
                    "publication",
                    check,
                    self.root,
                    f"Publication MEI is missing its MEI 5.1 CMN {scheme} xml-model declaration.",
                    expected="https://music-encoding.org/schema/5.1/mei-CMN.rng",
                    actual=" | ".join(model_pis),
                )

        if self.root.get("meiversion") != "5.1+CMN":
            self.add(
                "warning",
                "publication",
                "cmn_meiversion",
                self.root,
                "Publication profile should identify the MEI version and customization.",
                expected="5.1+CMN",
                actual=self.root.get("meiversion", ""),
            )

        mei_head = first_child(self.root, "meiHead")
        if mei_head is None:
            self.add("error", "publication", "meihead", self.root, "Publication MEI has no meiHead.")
            return

        def descendants(tag: str) -> list[ET.Element]:
            return [element for element in mei_head.iter() if local_name(element.tag) == tag]

        alt_ids = [
            element
            for element in list(mei_head)
            if local_name(element.tag) == "altId" and element.get("type") == "repository-stem"
        ]
        if not alt_ids or not normalized_text(alt_ids[0]):
            self.add(
                "warning",
                "publication",
                "repository_alt_id",
                mei_head,
                "meiHead should carry a non-empty repository-stem altId.",
            )

        editions = descendants("edition")
        if not editions or not normalized_text(editions[0]) or not editions[0].get("n"):
            self.add(
                "warning",
                "publication",
                "edition_statement",
                mei_head,
                "Publication MEI should record a named, versioned edition.",
                expected="edition text and semantic version in @n",
            )
        elif not re.fullmatch(r"\d+\.\d+\.\d+", editions[0].get("n", "")):
            self.add(
                "info",
                "publication",
                "edition_version",
                editions[0],
                "Edition @n is not a three-part semantic version.",
                expected="MAJOR.MINOR.PATCH",
                actual=editions[0].get("n", ""),
            )

        for tag, check, message in (
            ("publisher", "publisher", "Publication MEI should identify its publisher."),
            ("availability", "mei_license", "Publication MEI should state reuse conditions."),
            ("sourceDesc", "source_description", "Publication MEI should describe its source."),
            ("editorialDecl", "editorial_declaration", "Publication MEI should state its editorial policy."),
            ("projectDesc", "project_description", "Publication MEI should identify its project context."),
            ("workList", "work_description", "Publication MEI should identify the encoded work."),
            ("revisionDesc", "revision_history", "Publication MEI should record meaningful revisions."),
        ):
            elements = descendants(tag)
            if not elements or not normalized_text(elements[0]):
                self.add("warning", "publication", check, mei_head, message)

        identifiers = descendants("identifier")
        identifier_types = {element.get("type", "") for element in identifiers if normalized_text(element)}
        for identifier_type in ("URN", "BSB-ID", "BuxWV"):
            if identifier_type not in identifier_types:
                self.add(
                    "warning",
                    "publication",
                    "stable_identifier",
                    mei_head,
                    f"Publication metadata has no {identifier_type} identifier.",
                    expected=identifier_type,
                    actual=", ".join(sorted(identifier_types)),
                )

        refs = descendants("ref")
        if not any(element.get("type") == "iiif-manifest" and element.get("target") for element in refs):
            self.add(
                "warning",
                "publication",
                "iiif_manifest",
                mei_head,
                "Source metadata should link the IIIF Presentation manifest.",
            )

        app_names = {normalized_text(element) for element in descendants("name")}
        for application_name in ("musiconn.scoresearch", "Verovio", "mei-friend"):
            if application_name not in app_names:
                self.add(
                    "info",
                    "publication",
                    "application_provenance",
                    mei_head,
                    f"Application provenance does not list {application_name}.",
                )

        work_ids = {
            element.get(XML_ID, "")
            for element in descendants("work")
            if element.get(XML_ID)
        }
        for mdiv in (element for element in self.root.iter() if local_name(element.tag) == "mdiv"):
            decls = {token.lstrip("#") for token in mdiv.get("decls", "").split()}
            if not decls.intersection(work_ids):
                self.add(
                    "warning",
                    "publication",
                    "mdiv_work_link",
                    mdiv,
                    "Music division is not linked to a described work using @decls.",
                    expected=" ".join(f"#{work_id}" for work_id in sorted(work_ids)),
                    actual=mdiv.get("decls", ""),
                )

        changes = descendants("change")
        dates = [element.get("isodate", "") for element in changes]
        dated = [date for date in dates if date]
        if dated and dated != sorted(dated, reverse=True):
            self.add(
                "warning",
                "publication",
                "revision_order",
                changes[0],
                "revisionDesc should list changes in reverse chronological order.",
                expected="newest first",
                actual=" -> ".join(dates),
            )
        for change in changes:
            if not change.get("resp") and first_child(change, "respStmt") is None:
                self.add(
                    "warning",
                    "publication",
                    "revision_responsibility",
                    change,
                    "Revision entry does not identify a responsible agent.",
                )

    def _check_facsimile_page_structure(self) -> None:
        """Check page/surface transitions and image geometry for full MEI files."""
        assert self.root is not None

        surfaces = [element for element in self.root.iter() if local_name(element.tag) == "surface"]
        surface_by_id = {
            element.get(XML_ID, ""): element
            for element in surfaces
            if element.get(XML_ID)
        }
        zone_surface: dict[str, str] = {}
        zone_elements: dict[str, ET.Element] = {}
        surface_numbers = []

        for surface in surfaces:
            surface_id = surface.get(XML_ID, "")
            raw_n = surface.get("n", "")
            if raw_n.isdigit():
                surface_numbers.append(int(raw_n))
            else:
                self.add(
                    "warning",
                    "facsimile",
                    "surface_page_number",
                    surface,
                    "Publication surface should carry a numeric printed-page @n.",
                    actual=raw_n,
                )

            graphics = direct_children(surface, "graphic")
            if len(graphics) != 1:
                self.add(
                    "error",
                    "facsimile",
                    "surface_graphic_count",
                    surface,
                    "Each facsimile surface must contain exactly one graphic.",
                    expected="1",
                    actual=str(len(graphics)),
                )
                graphic = graphics[0] if graphics else None
            else:
                graphic = graphics[0]

            max_width = max_height = None
            if graphic is not None:
                for attr in ("target", "width", "height", "mimetype"):
                    if not graphic.get(attr):
                        self.add(
                            "warning",
                            "facsimile",
                            "graphic_metadata",
                            graphic,
                            f"Facsimile graphic is missing @{attr}.",
                        )
                try:
                    max_width = float(graphic.get("width", ""))
                    max_height = float(graphic.get("height", ""))
                except ValueError:
                    pass
            if not surface.get("corresp"):
                self.add(
                    "info",
                    "facsimile",
                    "surface_iiif_canvas",
                    surface,
                    "Surface has no stable @corresp link to its IIIF canvas.",
                )

            for zone in direct_children(surface, "zone"):
                zone_id = zone.get(XML_ID, "")
                if zone_id:
                    zone_surface[zone_id] = surface_id
                    zone_elements[zone_id] = zone
                if max_width is None or max_height is None:
                    continue
                try:
                    ulx = float(zone.get("ulx", ""))
                    uly = float(zone.get("uly", ""))
                    lrx = float(zone.get("lrx", ""))
                    lry = float(zone.get("lry", ""))
                except ValueError:
                    continue
                if ulx < 0 or uly < 0 or lrx > max_width or lry > max_height:
                    self.add(
                        "error",
                        "facsimile",
                        "zone_image_bounds",
                        zone,
                        "Zone coordinates extend beyond the graphic dimensions.",
                        expected=f"0..{max_width:g} x 0..{max_height:g}",
                        actual=f"ulx={ulx:g} uly={uly:g} lrx={lrx:g} lry={lry:g}",
                    )

        if surface_numbers and surface_numbers != list(
            range(surface_numbers[0], surface_numbers[0] + len(surface_numbers))
        ):
            self.add(
                "warning",
                "facsimile",
                "surface_page_sequence",
                surfaces[0],
                "Numeric surface page labels are not sequential.",
                expected=f"{surface_numbers[0]}..{surface_numbers[0] + len(surface_numbers) - 1}",
                actual=", ".join(map(str, surface_numbers)),
            )

        measures = [element for element in self.root.iter() if local_name(element.tag) == "measure"]
        used_zones = Counter(measure.get("facs", "").lstrip("#") for measure in measures)
        for zone_id, count in used_zones.items():
            if zone_id and count > 1 and zone_id in zone_elements:
                self.add(
                    "error",
                    "facsimile",
                    "duplicate_measure_zone_use",
                    zone_elements[zone_id],
                    "A measure zone is referenced by more than one measure.",
                    expected="1",
                    actual=str(count),
                )

        page_breaks = [element for element in self.root.iter() if local_name(element.tag) == "pb"]
        pb_surfaces = Counter(pb.get("facs", "").lstrip("#") for pb in page_breaks)
        referenced_surfaces = {
            zone_surface.get(measure.get("facs", "").lstrip("#"), "")
            for measure in measures
        }
        referenced_surfaces.discard("")
        for surface_id in sorted(referenced_surfaces):
            count = pb_surfaces.get(surface_id, 0)
            if count != 1:
                self.add(
                    "error",
                    "facsimile",
                    "page_break_per_surface",
                    surface_by_id.get(surface_id),
                    "Each referenced facsimile surface must have exactly one page break.",
                    expected="1",
                    actual=str(count),
                    context=f"surface=#{surface_id}",
                )

        for pb in page_breaks:
            surface_id = pb.get("facs", "").lstrip("#")
            surface = surface_by_id.get(surface_id)
            if surface is not None and pb.get("n", "") != surface.get("n", ""):
                self.add(
                    "warning",
                    "facsimile",
                    "page_break_number",
                    pb,
                    "Page break @n does not match the linked surface @n.",
                    expected=surface.get("n", ""),
                    actual=pb.get("n", ""),
                )

        active_surface = ""
        for element in self.root.iter():
            tag = local_name(element.tag)
            if tag == "pb":
                active_surface = element.get("facs", "").lstrip("#")
            elif tag == "measure":
                expected_surface = zone_surface.get(element.get("facs", "").lstrip("#"), "")
                if expected_surface and active_surface != expected_surface:
                    self.add(
                        "error",
                        "facsimile",
                        "measure_page_context",
                        element,
                        "Measure occurs under the wrong active page break.",
                        expected=f"#{expected_surface}",
                        actual=f"#{active_surface}" if active_surface else "no preceding pb",
                    )

        encoded_system_breaks: set[str] = set()
        pending_system_break = False
        for element in self.root.iter():
            tag = local_name(element.tag)
            if tag == "sb":
                pending_system_break = True
            elif tag == "measure":
                if pending_system_break and element.get(XML_ID):
                    encoded_system_breaks.add(element.get(XML_ID, ""))
                pending_system_break = False

        measures_by_surface: dict[
            str, list[tuple[ET.Element, ET.Element]]
        ] = defaultdict(list)
        for measure in measures:
            zone_id = measure.get("facs", "").lstrip("#")
            zone = zone_elements.get(zone_id)
            surface_id = zone_surface.get(zone_id, "")
            if zone is not None and surface_id:
                measures_by_surface[surface_id].append((measure, zone))

        for surface_id, surface_measures in measures_by_surface.items():
            try:
                heights = sorted(
                    float(zone.get("lry", "")) - float(zone.get("uly", ""))
                    for _, zone in surface_measures
                )
                threshold = max(50.0, heights[len(heights) // 2] * 0.45)
            except ValueError:
                continue
            band_centers: list[float] = []
            for measure, zone in surface_measures:
                try:
                    center = (
                        float(zone.get("uly", ""))
                        + float(zone.get("lry", ""))
                    ) / 2.0
                except ValueError:
                    continue
                if not band_centers:
                    band_centers.append(center)
                    continue
                band_center = sum(band_centers) / len(band_centers)
                if abs(center - band_center) > threshold:
                    measure_id = measure.get(XML_ID, "")
                    if measure_id not in encoded_system_breaks:
                        self.add(
                            "warning",
                            "facsimile",
                            "system_break_zone_alignment",
                            measure,
                            "Facsimile measure zones begin a new vertical system "
                            "without a preceding <sb>.",
                            expected="preceding <sb>",
                            actual="none",
                            context=f"surface=#{surface_id}",
                        )
                    band_centers = [center]
                else:
                    band_centers.append(center)

    def _check_empty_structural_elements(self) -> None:
        assert self.root is not None
        empty_note_accidentals: list[ET.Element] = []
        for element in self.root.iter():
            tag = local_name(element.tag)
            if tag == "accid":
                meaningful = {
                    local_name(name): value
                    for name, value in element.attrib.items()
                    if local_name(name) != "id" and value
                }
                if not meaningful and not normalized_text(element):
                    parent = self.parent.get(element)
                    if parent is None or local_name(parent.tag) != "note":
                        self.add(
                            "error",
                            "structure",
                            "misplaced_empty_accid",
                            element,
                            "Empty accid is not attached to a note and is invalid in the CMN profile.",
                        )
                    else:
                        empty_note_accidentals.append(element)
            elif tag == "chord" and not direct_children(element, "note"):
                self.add(
                    "error",
                    "structure",
                    "empty_chord",
                    element,
                    "Chord contains no note elements.",
                )
            elif tag == "annot" and not normalized_text(element) and not any(
                element.get(attr) for attr in ("plist", "target", "startid", "endid")
            ):
                self.add(
                    "warning",
                    "structure",
                    "empty_annotation",
                    element,
                    "Annotation has neither text nor a target reference.",
                )

        if empty_note_accidentals:
            examples = [
                element.get(XML_ID, "")
                for element in empty_note_accidentals[:5]
                if element.get(XML_ID)
            ]
            self.add(
                "warning",
                "structure",
                "empty_note_accidentals",
                empty_note_accidentals[0],
                "Empty accid children carry no visual or gestural accidental data and can be removed safely.",
                expected="0",
                actual=str(len(empty_note_accidentals)),
                context=f"first xml:ids={', '.join(examples)}",
            )

    def _check_references(self) -> None:
        assert self.root is not None
        for element in self.root.iter():
            for attr_name, value in element.attrib.items():
                clean_attr = local_name(attr_name)
                if clean_attr not in REFERENCE_ATTRS:
                    continue
                for token in str(value).split():
                    if not token.startswith("#"):
                        continue
                    ref_id = token[1:]
                    if not ref_id:
                        self.add(
                            "error",
                            "references",
                            "empty_internal_reference",
                            element,
                            f"Reference '{token}' in @{clean_attr} is empty.",
                            actual=token,
                        )
                    elif ref_id not in self.ids and ref_id in self.corpus_id_locations:
                        locations = sorted(set(self.corpus_id_locations[ref_id]))
                        context_parts = [
                            "Reference resolves in another selected MEI file and should resolve after combining.",
                            f"target_file={', '.join(locations[:3])}",
                        ]
                        if len(locations) > 3:
                            context_parts.append(f"+{len(locations) - 3} more")
                        boundary_context = self._measure_boundary_context(element)
                        if boundary_context:
                            context_parts.append(boundary_context)
                        self.add(
                            "info",
                            "references",
                            "cross_file_internal_reference",
                            element,
                            f"Reference '{token}' in @{clean_attr} does not resolve inside this page but resolves in the selected file set.",
                            actual=token,
                            context="; ".join(context_parts),
                        )
                    elif ref_id not in self.ids:
                        self.add(
                            "error",
                            "references",
                            "broken_internal_reference",
                            element,
                            f"Reference '{token}' in @{clean_attr} does not resolve to an xml:id in this file.",
                            actual=token,
                        )

    def _measure_boundary_context(self, element: ET.Element) -> str:
        assert self.root is not None
        measure = ancestor_element(element, self.parent, "measure")
        if measure is None:
            return ""
        measures = [candidate for candidate in self.root.iter() if local_name(candidate.tag) == "measure"]
        if not measures:
            return ""
        if measure is measures[0]:
            return "source_measure=first_on_page"
        if measure is measures[-1]:
            return "source_measure=last_on_page"
        return ""

    def _check_facsimile_zones(self) -> None:
        assert self.root is not None
        zones = {}
        used_measure_zones = set()
        for zone in self.root.iter():
            if local_name(zone.tag) != "zone":
                continue
            xml_id = zone.get(XML_ID, "")
            if xml_id:
                zones[xml_id] = zone
            if zone.get("type") == "measure":
                self._check_zone_coordinates(zone)

        for measure in self.root.iter():
            if local_name(measure.tag) != "measure":
                continue
            facs = measure.get("facs", "")
            if not facs:
                self.add("warning", "facsimile", "measure_facs", measure, "Measure has no @facs reference.")
                continue
            if not facs.startswith("#"):
                self.add(
                    "warning",
                    "facsimile",
                    "measure_facs",
                    measure,
                    "Measure @facs is not an internal zone reference.",
                    actual=facs,
                )
                continue
            zone_id = facs[1:]
            used_measure_zones.add(zone_id)
            zone = zones.get(zone_id)
            if zone is None:
                continue
            if zone.get("type") != "measure":
                self.add(
                    "warning",
                    "facsimile",
                    "measure_facs_zone_type",
                    measure,
                    "Measure @facs points to a zone that is not marked type='measure'.",
                    expected="type='measure'",
                    actual=zone.get("type", ""),
                )

        for zone_id, zone in zones.items():
            if zone.get("type") == "measure" and zone_id not in used_measure_zones:
                self.add(
                    "info",
                    "facsimile",
                    "unused_measure_zone",
                    zone,
                    "Measure zone is not referenced by any <measure>@facs.",
                    actual=f"#{zone_id}",
                )

    def _check_zone_coordinates(self, zone: ET.Element) -> None:
        coords = {}
        for attr in ("ulx", "uly", "lrx", "lry"):
            raw = zone.get(attr)
            if raw is None:
                self.add("warning", "facsimile", "zone_coordinates", zone, f"Measure zone is missing @{attr}.")
                return
            try:
                coords[attr] = float(raw)
            except ValueError:
                self.add(
                    "warning",
                    "facsimile",
                    "zone_coordinates",
                    zone,
                    f"Measure zone @{attr} is not numeric.",
                    actual=raw,
                )
                return
        if coords["lrx"] <= coords["ulx"] or coords["lry"] <= coords["uly"]:
            self.add(
                "warning",
                "facsimile",
                "zone_coordinates",
                zone,
                "Measure zone has non-positive width or height.",
                actual=f"ulx={coords['ulx']} uly={coords['uly']} lrx={coords['lrx']} lry={coords['lry']}",
            )

    def _walk_score_for_meters_and_measures(self) -> None:
        assert self.root is not None
        previous_measure_n: int | None = None
        for element in self.root.iter():
            tag = local_name(element.tag)
            if tag == "scoreDef":
                self._apply_score_def(element)
                if not self.initial_staff_defs and self.current_staff_defs:
                    self.initial_staff_defs = {k: v.copy() for k, v in self.current_staff_defs.items()}
            elif tag == "measure":
                previous_measure_n = self._check_measure_sequence(element, previous_measure_n)
                self._check_measure_staff_inventory(element)
                self._check_measure_rhythm(element)

    def _apply_score_def(self, score_def: ET.Element) -> None:
        global_meter = meter_from_element(score_def)
        for staff_def in score_def.iter():
            if local_name(staff_def.tag) != "staffDef":
                continue
            staff_n = staff_def.get("n", "")
            if not staff_n:
                self.add("warning", "staffing", "staffdef_n", staff_def, "<staffDef> is missing @n.")
                continue
            record = self.current_staff_defs.setdefault(staff_n, {})
            record.update(
                {
                    "staff_n": staff_n,
                    "ppq": staff_def.get("ppq") or record.get("ppq") or "4",
                    "line": str(self.line_for(staff_def) or ""),
                    "xml_id": staff_def.get(XML_ID, ""),
                }
            )
            local_meter = meter_from_element(staff_def)
            meter = local_meter or global_meter
            if meter:
                record["meter_count"], record["meter_unit"] = meter
            elif "meter_count" not in record:
                self.add(
                    "warning",
                    "meter",
                    "missing_meter",
                    staff_def,
                    "No meter signature found for this staff definition.",
                )
            record.update(self._staff_identity(staff_def, inherited=record))

        if global_meter:
            for record in self.current_staff_defs.values():
                record["meter_count"], record["meter_unit"] = global_meter

        meters = {
            (record.get("meter_count", ""), record.get("meter_unit", ""))
            for record in self.current_staff_defs.values()
            if record.get("meter_count") and record.get("meter_unit")
        }
        meter_spans = {meter_measure_span(meter) for meter in meters}
        incompatible_meters = len(meter_spans) > 1 or None in meter_spans
        if len(meters) > 1 and incompatible_meters:
            self.add(
                "warning",
                "meter",
                "mixed_staff_meters",
                score_def,
                "Different staff meters with incompatible measure spans are active at the same scoreDef.",
                actual="; ".join(f"{count}/{unit}" for count, unit in sorted(meters)),
            )

    def _staff_identity(
        self,
        staff_def: ET.Element,
        report: bool = True,
        inherited: dict[str, str] | None = None,
    ) -> dict[str, str]:
        inherited = inherited or {}
        parent = self.parent.get(staff_def)
        direct_label_el = first_child(staff_def, "label")
        direct_abbr_el = first_child(staff_def, "labelAbbr")
        label_el = direct_label_el
        abbr_el = direct_abbr_el
        instr_el = first_child(staff_def, "instrDef")
        if label_el is None and parent is not None and local_name(parent.tag) == "staffGrp":
            label_el = first_child(parent, "label")
        if abbr_el is None and parent is not None and local_name(parent.tag) == "staffGrp":
            abbr_el = first_child(parent, "labelAbbr")
        if instr_el is None and parent is not None and local_name(parent.tag) == "staffGrp":
            instr_el = first_child(parent, "instrDef")
        grouped_staff = parent is not None and local_name(parent.tag) == "staffGrp"

        label = normalized_text(label_el)
        abbr = normalized_text(abbr_el)
        effective_label = label or inherited.get("label", "")
        effective_abbr = abbr or inherited.get("label_abbr", "")
        instr_num = instr_el.get("midi.instrnum", "") if instr_el is not None else ""
        midi_channel = instr_el.get("midi.channel", "") if instr_el is not None else ""

        if report and direct_label_el is not None and not label:
            self.add(
                "warning",
                "instrumentation",
                "empty_staff_label",
                label_el,
                "Staff label is empty; use a stable instrument/voice name for the edition.",
                staff_n=staff_def.get("n", ""),
            )
        if report and label and GENERIC_LABEL_RE.match(label):
            self.add(
                "info",
                "instrumentation",
                "generic_staff_label",
                label_el if label_el is not None else staff_def,
                "Staff label looks like generated system text rather than an editorial instrument name.",
                actual=label,
                staff_n=staff_def.get("n", ""),
            )
        if report and abbr and GENERIC_LABEL_RE.match(abbr):
            self.add(
                "info",
                "instrumentation",
                "generic_staff_abbr",
                abbr_el if abbr_el is not None else staff_def,
                "Staff abbreviation looks generated and should be checked for edition consistency.",
                actual=abbr,
                staff_n=staff_def.get("n", ""),
            )
        if report and not effective_label and not effective_abbr and not grouped_staff:
            self.add(
                "warning",
                "instrumentation",
                "missing_staff_name",
                staff_def,
                "Staff has neither a label nor a label abbreviation.",
                staff_n=staff_def.get("n", ""),
            )
        inherited_instr = inherited.get("midi_instrnum", "") or inherited.get("midi_channel", "")
        if report and instr_el is None and not inherited_instr:
            self.add(
                "info",
                "instrumentation",
                "missing_instrdef",
                staff_def,
                "Staff definition has no instrDef in staffDef, enclosing staffGrp, or inherited active staff identity.",
                staff_n=staff_def.get("n", ""),
            )

        return {
            "label": effective_label,
            "label_abbr": effective_abbr,
            "midi_instrnum": instr_num or inherited.get("midi_instrnum", ""),
            "midi_channel": midi_channel or inherited.get("midi_channel", ""),
        }

    def _check_measure_sequence(self, measure: ET.Element, previous: int | None) -> int | None:
        raw_n = measure.get("n", "")
        if not raw_n:
            self.add("warning", "measures", "measure_number", measure, "Measure is missing @n.")
            return previous
        if not raw_n.isdigit():
            self.add(
                "info",
                "measures",
                "measure_number",
                measure,
                "Measure @n is not a plain integer; sequence check skipped for this measure.",
                actual=raw_n,
            )
            return previous
        current = int(raw_n)
        if previous is not None and current != previous + 1:
            self.add(
                "warning",
                "measures",
                "measure_sequence",
                measure,
                "Measure numbers are not sequential.",
                expected=str(previous + 1),
                actual=str(current),
            )
        return current

    def _check_measure_staff_inventory(self, measure: ET.Element) -> None:
        expected = set(self.current_staff_defs)
        actual = {child.get("n", "") for child in list(measure) if local_name(child.tag) == "staff"}
        if not expected:
            return
        missing = sorted(staff for staff in expected - actual if staff)
        extra = sorted(staff for staff in actual - expected if staff)
        if missing and measure.get("metcon") != "false":
            self.add(
                "warning",
                "staffing",
                "missing_staff_in_measure",
                measure,
                "Measure does not contain all staff numbers declared in the active staffDef.",
                expected=", ".join(sorted(expected)),
                actual=", ".join(sorted(actual)),
                context=f"missing={', '.join(missing)}",
            )
        if extra:
            self.add(
                "warning",
                "staffing",
                "extra_staff_in_measure",
                measure,
                "Measure contains a staff number not declared in the active staffDef.",
                expected=", ".join(sorted(expected)),
                actual=", ".join(sorted(actual)),
                context=f"extra={', '.join(extra)}",
            )

    def _check_measure_rhythm(self, measure: ET.Element) -> None:
        for staff in direct_children(measure, "staff"):
            staff_n = staff.get("n", "")
            staff_def = self.current_staff_defs.get(staff_n, {})
            expected = expected_measure_ppq(staff_def)
            layers = direct_children(staff, "layer")
            if not layers:
                self.add("warning", "rhythm", "missing_layer", staff, "Staff has no layer.")
                continue
            layer_nums = [layer.get("n", "") for layer in layers]
            duplicates = [n for n, count in Counter(layer_nums).items() if n and count > 1]
            if duplicates:
                self.add(
                    "warning",
                    "layering",
                    "duplicate_layer_n",
                    staff,
                    "Staff has duplicate layer numbers in the same measure.",
                    actual=", ".join(duplicates),
                )
            if len(layers) == 1 and layer_nums[0] and layer_nums[0] != "1":
                self.add(
                    "info",
                    "layering",
                    "single_layer_not_numbered_one",
                    layers[0],
                    "Single-layer staff has layer @n other than '1'; check whether voice numbering is intentional.",
                    expected="1",
                    actual=layer_nums[0],
                )

            for layer in layers:
                self._check_layer_rhythm(measure, staff, layer, expected)

    def _check_layer_rhythm(
        self,
        measure: ET.Element,
        staff: ET.Element,
        layer: ET.Element,
        expected: Fraction | None,
    ) -> None:
        total = Fraction(0)
        event_count = 0
        space_count = 0
        missing_duration = []
        for event in layer.iter():
            tag = local_name(event.tag)
            if tag not in TIMED_EVENTS:
                continue
            if tag == "note" and parent_is(event, self.parent, "chord"):
                self._check_pitch(event)
                continue
            if event.get("grace"):
                continue
            if tag == "space":
                space_count += 1
            if tag in PITCHED_EVENTS:
                self._check_pitch(event)
            staff_def = self.current_staff_defs.get(staff.get("n", ""), {})
            duration = event_duration_written(event, staff_def)
            if duration is not None:
                duration *= tuplet_duration_scale(event, self.parent, layer)
            ppq_duration = event_duration_ppq(event) if self.check_ppq else None
            if self.check_ppq and duration is not None and ppq_duration is not None and duration != ppq_duration:
                self.add(
                    "info",
                    "rhythm",
                    "dur_ppq_mismatch",
                    event,
                    "@dur.ppq differs from the written duration implied by @dur/@dots under the active @ppq.",
                    expected=format_fraction(duration),
                    actual=format_fraction(ppq_duration),
                    context="@dur/@dots are treated as authoritative for this facsimile-based edition.",
                )
            if duration is None:
                if tag in {"mRest", "mSpace"} and expected is not None:
                    duration = expected
                else:
                    missing_duration.append(event)
                    continue
            total += duration
            event_count += 1

        for event in missing_duration:
            self.add(
                "warning",
                "rhythm",
                "missing_duration",
                event,
                "Timed event has no usable written @dur value.",
            )

        if event_count == 0 and expected is not None:
            self.add("warning", "rhythm", "empty_layer", layer, "Layer contains no timed musical events.")
            return
        if expected is None:
            self.add(
                "info",
                "rhythm",
                "rhythm_no_meter",
                layer,
                "Layer duration could not be checked because no active meter was found.",
                actual=format_fraction(total),
            )
            return

        if total != expected and measure.get("metcon") != "false":
            direction = "underfull" if total < expected else "overfull"
            check = "layer_duration_underfull" if total < expected else "layer_duration_overfull"
            context = ""
            if total < expected and space_count == 0:
                context = "No <space> found in this layer; a missing space/rest is a likely cause."
            self.add(
                "warning",
                "rhythm",
                check,
                layer,
                f"Layer is {direction} against the active meter.",
                expected=format_fraction(expected),
                actual=format_fraction(total),
                context=context,
            )

    def _check_pitch(self, note: ET.Element) -> None:
        pname = note.get("pname", "")
        octv = note.get("oct", "")
        if pname and pname not in VALID_PNAMES:
            self.add("warning", "pitch", "invalid_pname", note, "Note @pname is not a-g.", actual=pname)
        if not pname and not note.get("loc"):
            self.add(
                "warning",
                "pitch",
                "missing_pitch",
                note,
                "Note has neither @pname nor staff-location pitch information.",
            )
        if octv and not re.fullmatch(r"-?\d+", octv):
            self.add("warning", "pitch", "invalid_octave", note, "Note @oct is not an integer.", actual=octv)

    def _check_terms(self) -> None:
        assert self.root is not None
        terms_by_normalized = defaultdict(list)
        for element in self.root.iter():
            tag = local_name(element.tag)
            if tag not in {"dir", "tempo", "dynam"}:
                continue
            text = normalized_text(element)
            if not text:
                self.add("warning", "terms", "empty_term", element, f"<{tag}> has no text content.")
                continue
            stripped = text.strip()
            if text != stripped:
                self.add("info", "terms", "term_whitespace", element, "Musical term has leading/trailing whitespace.")
            if tag in {"dir", "tempo"} and not (element.get("tstamp") or element.get("startid")):
                self.add(
                    "info",
                    "terms",
                    "term_anchor",
                    element,
                    f"<{tag}> has neither @tstamp nor @startid; check placement anchor.",
                    actual=text,
                )
            norm = normalize_term(text)
            terms_by_normalized[norm].append(text)
            self.term_records.append(
                {
                    "file": self.rel_path,
                    "line": str(self.line_for(element) or ""),
                    "element": tag,
                    "measure_n": ancestor_attr(element, self.parent, "measure", "n"),
                    "staff_n": element.get("staff", ""),
                    "xml_id": element.get(XML_ID, ""),
                    "text": text,
                    "normalized": norm,
                }
            )
        for norm, variants in terms_by_normalized.items():
            distinct = sorted(set(variants))
            if len(distinct) > 1:
                first = next(
                    element
                    for element in self.root.iter()
                    if local_name(element.tag) in {"dir", "tempo", "dynam"}
                    and normalize_term(normalized_text(element)) == norm
                )
                self.add(
                    "info",
                    "terms",
                    "term_spelling_variants_in_file",
                    first,
                    "Same normalized musical term appears with spelling/punctuation variants in this file.",
                    actual=" | ".join(distinct),
                )

    def _collect_staff_records(self) -> None:
        assert self.root is not None
        for staff_def in self.root.iter():
            if local_name(staff_def.tag) != "staffDef":
                continue
            identity = self._staff_identity(staff_def, report=False)
            meter = meter_from_element(staff_def)
            self.staff_records.append(
                {
                    "file": self.rel_path,
                    "line": str(self.line_for(staff_def) or ""),
                    "staff_n": staff_def.get("n", ""),
                    "xml_id": staff_def.get(XML_ID, ""),
                    "label": identity.get("label", ""),
                    "label_abbr": identity.get("label_abbr", ""),
                    "midi_instrnum": identity.get("midi_instrnum", ""),
                    "midi_channel": identity.get("midi_channel", ""),
                    "ppq": staff_def.get("ppq", ""),
                    "meter": "/".join(meter) if meter else "",
                }
            )


def direct_children(element: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in list(element) if local_name(child.tag) == tag]


def first_child(element: ET.Element, tag: str) -> ET.Element | None:
    for child in list(element):
        if local_name(child.tag) == tag:
            return child
    return None


def parent_is(element: ET.Element, parent_map: dict[ET.Element, ET.Element], tag: str) -> bool:
    parent = parent_map.get(element)
    return parent is not None and local_name(parent.tag) == tag


def ancestor_attr(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    ancestor_tag: str,
    attr: str,
) -> str:
    current = parent_map.get(element)
    while current is not None:
        if local_name(current.tag) == ancestor_tag:
            return current.get(attr, "")
        current = parent_map.get(current)
    return ""


def ancestor_element(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    ancestor_tag: str,
) -> ET.Element | None:
    current = parent_map.get(element)
    while current is not None:
        if local_name(current.tag) == ancestor_tag:
            return current
        current = parent_map.get(current)
    return None


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def normalized_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def normalize_term(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^[\(\[]|[\)\].,:;!]+$", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def meter_from_element(element: ET.Element) -> tuple[str, str] | None:
    count = element.get("meter.count")
    unit = element.get("meter.unit")
    if count and unit:
        return count, unit
    for child in list(element):
        if local_name(child.tag) == "meterSig":
            count = child.get("count")
            unit = child.get("unit")
            if count and unit:
                return count, unit
    return None


def meter_measure_span(meter: tuple[str, str]) -> Fraction | None:
    count, unit = meter
    try:
        count_int = int(count)
        unit_int = int(unit)
    except ValueError:
        return None
    if unit_int == 0:
        return None
    if (count_int, unit_int) == (12, 8):
        return Fraction(4, 4)
    return Fraction(count_int, unit_int)


def expected_measure_ppq(staff_def: dict[str, str]) -> Fraction | None:
    count = staff_def.get("meter_count", "")
    unit = staff_def.get("meter_unit", "")
    ppq = staff_def.get("ppq", "4")
    try:
        return Fraction(int(count) * int(ppq) * 4, int(unit))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def event_duration_ppq(event: ET.Element) -> Fraction | None:
    dur_ppq = event.get("dur.ppq")
    if not dur_ppq:
        return None
    try:
        return Fraction(dur_ppq)
    except ValueError:
        return None


def event_duration_written(event: ET.Element, staff_def: dict[str, str]) -> Fraction | None:
    dur = event.get("dur")
    if not dur:
        return None
    if dur not in VALID_DURS:
        return None
    ppq = staff_def.get("ppq", "4")
    try:
        ppq_fraction = Fraction(ppq)
    except ValueError:
        return None
    if dur == "breve":
        base = ppq_fraction * 8
    elif dur == "long":
        base = ppq_fraction * 16
    elif dur == "maxima":
        base = ppq_fraction * 32
    else:
        base = ppq_fraction * Fraction(4, int(dur))
    dots = event.get("dots", "0")
    try:
        dot_count = int(dots)
    except ValueError:
        dot_count = 0
    multiplier = sum(Fraction(1, 2**i) for i in range(dot_count + 1))
    return base * multiplier


def tuplet_duration_scale(
    event: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
    layer: ET.Element,
) -> Fraction:
    """Return the cumulative performed-duration ratio for enclosing tuplets."""
    scale = Fraction(1)
    current = parent_map.get(event)
    while current is not None and current is not layer:
        if local_name(current.tag) == "tuplet":
            try:
                scale *= Fraction(int(current.get("numbase", "")), int(current.get("num", "")))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        current = parent_map.get(current)
    return scale


def format_fraction(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def find_mei_files(inputs: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            paths.extend(sorted(path.rglob("*.mei")))
        elif path.suffix.lower() == ".mei":
            paths.append(path)
    return sorted(dict.fromkeys(paths))


def relative_file_label(path: Path, root_dir: Path) -> str:
    try:
        return path.resolve().relative_to(root_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def scan_corpus_id_locations(files: Iterable[Path], root_dir: Path) -> dict[str, list[str]]:
    id_locations: dict[str, list[str]] = defaultdict(list)
    pattern = re.compile(r'\bxml:id\s*=\s*["\']([^"\']+)["\']')
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        label = relative_file_label(path, root_dir)
        for match in pattern.finditer(text):
            id_locations[match.group(1)].append(label)
    return dict(id_locations)


def strip_ppq_text(text: str) -> tuple[str, int]:
    """Remove @ppq and @dur.ppq attributes while preserving the rest of the XML text."""
    pattern = re.compile(r"\s+(?:dur\.)?ppq\s*=\s*(?:\"[^\"]*\"|'[^']*')")
    return pattern.subn("", text)


def strip_accid_ges_text(text: str) -> tuple[str, int]:
    """Remove leftover MusicXML @accid.ges attributes while preserving the rest of the XML text."""
    pattern = re.compile(r"\s+accid\.ges\s*=\s*(?:\"[^\"]*\"|'[^']*')")
    return pattern.subn("", text)


def strip_ppq_files(files: list[Path], output_dir: Path | None = None, input_base: Path | None = None) -> tuple[list[Path], int]:
    stripped_files: list[Path] = []
    removed_total = 0
    if input_base is None and files:
        input_base = Path(os.path.commonpath([file.resolve() for file in files]))
        if input_base.is_file():
            input_base = input_base.parent

    for source in files:
        source = source.resolve()
        cleaned, removed = strip_ppq_text(source.read_text(encoding="utf-8"))
        removed_total += removed
        if output_dir is None:
            target = source
        else:
            try:
                relative = source.relative_to(input_base.resolve() if input_base else source.parent)
            except ValueError:
                relative = Path(source.name)
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(cleaned, encoding="utf-8")
        stripped_files.append(target)
    return stripped_files, removed_total


def add_corpus_findings(
    findings: list[Finding],
    staff_records: list[dict[str, str]],
    term_records: list[dict[str, str]],
) -> None:
    by_file_staffs = defaultdict(set)
    by_file_first_staff = {}
    for record in staff_records:
        if not record["staff_n"]:
            continue
        by_file_staffs[record["file"]].add(record["staff_n"])
        by_file_first_staff.setdefault(record["file"], record)

    staff_sets = Counter(tuple(sorted(staffs, key=natural_sort_key)) for staffs in by_file_staffs.values())
    if len(staff_sets) > 1:
        expected_staffs = list(staff_sets.most_common(1)[0][0])
        for file_label, staffs in sorted(by_file_staffs.items()):
            actual_staffs = sorted(staffs, key=natural_sort_key)
            if actual_staffs == expected_staffs:
                continue
            first = by_file_first_staff[file_label]
            findings.append(
                Finding(
                    severity="warning",
                    category="staffing",
                    check="corpus_staff_set_variants",
                    file=file_label,
                    line=int(first["line"]) if first["line"].isdigit() else None,
                    element="staffDef",
                    measure_n="",
                    staff_n="",
                    layer_n="",
                    xml_id=first["xml_id"],
                    message="File declares a different staff set than the majority of selected MEI files.",
                    expected=f"{len(expected_staffs)} staves: {', '.join(expected_staffs)}",
                    actual=f"{len(actual_staffs)} staves: {', '.join(actual_staffs)}",
                    context=f"{len(by_file_staffs)} files checked",
                )
            )

    by_staff = defaultdict(list)
    for record in staff_records:
        if record["staff_n"]:
            by_staff[record["staff_n"]].append(record)
    for staff_n, records in sorted(by_staff.items()):
        for field, check, label in (
            ("label", "corpus_staff_label_variants", "staff labels"),
            ("label_abbr", "corpus_staff_abbr_variants", "staff abbreviations"),
            ("midi_instrnum", "corpus_midi_instrnum_variants", "MIDI instrument numbers"),
        ):
            values = sorted({record[field] for record in records if record[field]})
            if len(values) <= 1:
                continue
            first = records[0]
            findings.append(
                Finding(
                    severity="info",
                    category="instrumentation",
                    check=check,
                    file=first["file"],
                    line=int(first["line"]) if first["line"].isdigit() else None,
                    element="staffDef",
                    measure_n="",
                    staff_n=staff_n,
                    layer_n="",
                    xml_id=first["xml_id"],
                    message=f"Corpus uses multiple {label} for staff {staff_n}; decide whether this is intentional.",
                    expected="consistent naming",
                    actual=" | ".join(values),
                    context=f"{len(records)} staffDef records checked",
                )
            )

    term_variants = defaultdict(set)
    term_first = {}
    for record in term_records:
        term_variants[record["normalized"]].add(record["text"])
        term_first.setdefault(record["normalized"], record)
    for norm, variants in sorted(term_variants.items()):
        if len(variants) <= 1:
            continue
        first = term_first[norm]
        findings.append(
            Finding(
                severity="info",
                category="terms",
                check="corpus_term_spelling_variants",
                file=first["file"],
                line=int(first["line"]) if first["line"].isdigit() else None,
                element=first["element"],
                measure_n=first["measure_n"],
                staff_n=first["staff_n"],
                layer_n="",
                xml_id=first["xml_id"],
                message="Corpus uses spelling/punctuation variants of the same normalized musical term.",
                expected=norm,
                actual=" | ".join(sorted(variants)),
            )
        )


def natural_sort_key(value: str) -> tuple[int, int | str]:
    if value.isdigit():
        return (0, int(value))
    return (1, value)


def check_mei_files(
    files: Iterable[str | Path],
    *,
    root_dir: str | Path | None = None,
    check_ppq: bool = False,
    publication_profile: bool = False,
) -> list[Finding]:
    """Check explicit MEI files and return sorted, structured findings.

    Parameters
    ----------
    files
        MEI paths to check. Directories can be expanded with
        :func:`camat.mei_consistency_workflow.resolve_mei_inputs` first.
    root_dir
        Base directory used for file labels in reports. Defaults to the current
        working directory.
    check_ppq
        Compare optional ``@dur.ppq`` values with written durations.
    publication_profile
        Enable the MEI 5.1 CMN header and facsimile-topology checks.
    """
    paths = [Path(path) for path in files]
    if not paths:
        return []

    root = Path.cwd() if root_dir is None else Path(root_dir)
    corpus_id_locations = scan_corpus_id_locations(paths, root)
    findings: list[Finding] = []
    staff_records: list[dict[str, str]] = []
    term_records: list[dict[str, str]] = []

    for file_path in paths:
        checker = MeiChecker(
            file_path,
            root,
            check_ppq=check_ppq,
            publication_profile=publication_profile,
            corpus_id_locations=corpus_id_locations,
        )
        file_findings, file_staff_records, file_term_records = checker.run()
        findings.extend(file_findings)
        staff_records.extend(file_staff_records)
        term_records.extend(file_term_records)

    add_corpus_findings(findings, staff_records, term_records)
    severity_order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(
        key=lambda finding: (
            severity_order.get(finding.severity, 9),
            finding.file,
            finding.line or 0,
            finding.check,
        )
    )
    return findings


def write_csv(path: Path, findings: list[Finding]) -> None:
    rows = [asdict(finding) for finding in findings]
    fieldnames = list(Finding.__dataclass_fields__)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="MEI file(s) or folder(s) to check")
    parser.add_argument("--output", default="mei_consistency_report.csv", help="CSV output path")
    parser.add_argument("--json", dest="json_output", help="Optional JSON output path")
    parser.add_argument(
        "--check-ppq",
        action="store_true",
        help="Also compare optional @dur.ppq values against written @dur/@dots durations.",
    )
    parser.add_argument(
        "--publication-profile",
        action="store_true",
        help="Also check MEI 5.1 CMN publication metadata, page topology, and structural empties.",
    )
    parser.add_argument(
        "--strip-ppq-output",
        help="Write ppq-free MEI copies to this directory before checking them. Removes @ppq and @dur.ppq.",
    )
    parser.add_argument(
        "--strip-ppq-in-place",
        action="store_true",
        help="Remove @ppq and @dur.ppq directly from the input MEI files before checking them.",
    )
    parser.add_argument("--fail-on", choices=["error", "warning"], help="Return exit code 1 if findings at this severity or higher exist")
    args = parser.parse_args(argv)

    if args.strip_ppq_output and args.strip_ppq_in_place:
        parser.error("Use either --strip-ppq-output or --strip-ppq-in-place, not both.")

    root_dir = Path.cwd()
    files = find_mei_files(args.paths)
    if not files:
        print("No .mei files found.", file=sys.stderr)
        return 2
    input_base = Path(args.paths[0]).resolve() if len(args.paths) == 1 and Path(args.paths[0]).is_dir() else None
    if args.strip_ppq_output:
        output_dir = Path(args.strip_ppq_output).resolve()
        files, removed_total = strip_ppq_files(files, output_dir=output_dir, input_base=input_base)
        root_dir = output_dir
        print(f"Stripped {removed_total} @ppq/@dur.ppq attribute(s) into {output_dir}.")
    elif args.strip_ppq_in_place:
        files, removed_total = strip_ppq_files(files, output_dir=None, input_base=input_base)
        print(f"Stripped {removed_total} @ppq/@dur.ppq attribute(s) in place.")

    findings = check_mei_files(
        files,
        root_dir=root_dir,
        check_ppq=args.check_ppq,
        publication_profile=args.publication_profile,
    )

    output_path = Path(args.output)
    write_csv(output_path, findings)
    if args.json_output:
        json_output_path = Path(args.json_output)
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        json_output_path.write_text(
            json.dumps([asdict(finding) for finding in findings], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    counts = Counter(finding.severity for finding in findings)
    print(f"Checked {len(files)} MEI file(s). Wrote {len(findings)} findings to {output_path}.")
    print(
        "Findings by severity: "
        + ", ".join(f"{severity}={counts.get(severity, 0)}" for severity in ("error", "warning", "info"))
    )

    if args.fail_on:
        severity_order = {"error": 0, "warning": 1, "info": 2}
        threshold = severity_order[args.fail_on]
        if any(severity_order.get(finding.severity, 9) <= threshold for finding in findings):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
