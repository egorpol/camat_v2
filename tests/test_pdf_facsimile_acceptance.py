"""The PDF route end to end on the tutorial's Buxtehude Suite: navigation, a moved folder, validation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

import camat.pdf_facsimile as pf
from camat.facsimile_viewer import read_facsimile_model

M = "{http://www.music-encoding.org/ns/mei}"
ID = "{http://www.w3.org/XML/1998/namespace}id"
SUITE = Path(__file__).parents[1] / "test_corpus" / "Buxtehude-DdT11-app01-suite.mei"
# The tutorial's layout of BSB bsb00023199, images 0170-0173, behind a cover page.
LAYOUT = """
1 | cover
2 | 160 | 1-4, 5-9, 10-14
3 | 161 | 15-18, 19-25, 26-33, 34-40
4 | 162 | 41-47, 48-55, 56-63, 64-70
5 | 163 | 71-74, 75-79, 80-84, 85-89
"""


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def suite_chain(root: Path) -> tuple[Path, Path, Path]:
    """Generated page images and one box per printed bar; the Suite linked, paginated and approved."""
    folder = root / "facsimiles" / "print"
    (folder / "boxes").mkdir(parents=True)
    pages = []
    for number in range(1, 6):
        image = folder / f"page-{number:04d}.png"
        Image.new("L", (800, 1200), 250).save(image)
        pages.append({"page_id": f"print-p{number:04d}", "pdf_page_number": number, "image": image.name,
                      "width": 800, "height": 1200, "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                      "printed_page": None, "role": "unreviewed"})
    manifest = folder / "pages.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "source_id": "print", "pdf": "print.pdf", "pdf_sha256": "f" * 64,
        "page_count": 5, "dpi": 300, "renderer": "test renderer",
        "coordinate_system": "image pixels; origin top-left; x right, y down", "pages": pages}, indent=2) + "\n",
        encoding="utf-8")
    source = root / "input" / "suite.mei"
    source.parent.mkdir()
    source.write_text(pf.number_single_mdiv(SUITE.read_text(encoding="utf-8")), encoding="utf-8")
    layout = pf.parse_page_layout(LAYOUT, page_count=5)
    pf.check_page_layout(layout, source)
    for page in pf.apply_page_layout(manifest, layout, mdiv="1")["pages"]:
        if page["role"] == "music":
            boxes = [{"ulx": 40 + i * (720 // len(bars)), "uly": 60 + s * 280,
                      "lrx": 36 + (i + 1) * (720 // len(bars)), "lry": 300 + s * 280}
                     for s, bars in enumerate(page["systems"]) for i, _ in enumerate(bars)]
            (folder / "boxes" / f"{page['page_id']}.json").write_text(json.dumps({"measures": boxes}), encoding="utf-8")
    pf.detect_measure_boxes(manifest)
    alignment = pf.build_measure_alignment(manifest)
    assert pf.approve_alignment_review(alignment, "Test Reader", date="2026-10-22") == 4
    linked = root / "mei" / "suite.mei"
    report = pf.integrate_pdf_facsimile(source, manifest, alignment, linked)
    assert (report["measures_linked"], report["unreviewed_pages"]) == (89, [])
    pf.write_page_breaks(linked, manifest, linked)
    return source, linked, alignment


def music(path: Path) -> list:
    """Every body element except page and system breaks, without @facs."""
    body = ET.parse(path).getroot().find(f".//{M}body")
    return [(e.tag, {k: v for k, v in e.attrib.items() if k != "facs"}, (e.text or "").strip())
            for e in body.iter() if e.tag not in {M + "pb", M + "sb"}]


def test_every_bar_opens_its_reviewed_box_after_the_folder_moves(tmp_path):
    source, linked, alignment = suite_chain(tmp_path / "edition")
    reviewed = {r["measure_n"]: (f"surface-{r['page_id']}", r["bbox"]) for r in read_json(alignment)["regions"]}
    assert len(reviewed) == 89
    # Links and breaks leave the music alone, including the 46 ties (two cross the system break after bar 4).
    assert music(linked) == music(source)
    root = ET.parse(linked).getroot()
    ids = {e.get(ID) for e in root.iter()}
    ties = [(t.get("startid"), t.get("endid")) for t in root.iter(M + "tie")]
    assert len(ties) == 46 and all(end[1:] in ids for tie in ties for end in tie)

    moved = Path(shutil.move(tmp_path / "edition", tmp_path / "moved"))
    model = read_facsimile_model(moved / "mei" / "suite.mei")
    # A graphic the viewer cannot open keeps its target instead of an embedded image.
    assert [(s["id"], s["graphic_src"][:22], s["image_width"], s["image_height"]) for s in model["surfaces"]] == [
        (f"surface-print-p{n:04d}", "data:image/png;base64,", 800, 1200) for n in range(2, 6)]
    assert {m["measure_n"]: (m["surface_id"], [m["zone"][k] for k in ("ulx", "uly", "lrx", "lry")])
            for m in model["measures"]} == reviewed


def test_suite_passes_camat_validation_before_and_after_the_folder_moves(tmp_path):
    pytest.importorskip("lxml")
    pytest.importorskip("saxonche")
    from camat.mei_validation import run_mei_validation

    _, linked, _ = suite_chain(tmp_path / "edition")
    # music21 parses: Verovio's MIDI export crashes on this Suite (see the tutorial).
    result = run_mei_validation([linked], root=tmp_path / "edition", output_dir=tmp_path / "report",
                                check_verovio=True, check_camat_parse=True, parsing_backend="music21")
    statuses = {name: run["status"] for name, run in result.record["executions"].items()}
    assert result.passed, statuses
    assert Path(result.record["schema"]["path"]).name == "mei-CMN-5.1.rng"
    assert {statuses[name] for name in ("xml_references", "relaxng", "schematron", "resources",
                                        "verovio", "camat_parse")} == {"passed"}
    moved = Path(shutil.move(tmp_path / "edition", tmp_path / "moved"))
    result = run_mei_validation([moved / "mei" / "suite.mei"], root=moved, output_dir=tmp_path / "report-moved")
    assert result.passed, {name: run["status"] for name, run in result.record["executions"].items()}
