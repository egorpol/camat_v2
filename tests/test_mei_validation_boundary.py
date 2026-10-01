from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from camat import check_mei_files, prepare_pages_for_combine, run_editorial_checks
from camat.mei_references import REFERENCE_ATTRS

ROOT = Path(__file__).parents[1]
BASELINE = ROOT / "test_corpus" / "validation_baseline"
MEI = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _minimal(path: Path, *, reference: str | None = None, target_id: str | None = None) -> Path:
    root = ET.parse(BASELINE / "minimal-cmn-51.mei").getroot()
    note = root.find(f".//{{{MEI}}}note")
    assert note is not None
    if reference:
        note.set("corresp", reference)
    if target_id:
        note.set(XML_ID, target_id)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


@pytest.mark.parametrize("name", [
    "minimal-cmn-51.mei", "Hummel_Preludes_Op67_No11.mei",
    "Webern_Variations_for_Piano_Op27_No2.mei",
])
def test_general_baseline_has_no_edition_policy_findings(name: str) -> None:
    path = BASELINE / name
    before = hashlib.sha256(path.read_bytes()).digest()
    findings = check_mei_files([path], root_dir=ROOT, check_ppq=True)
    assert not [f for f in findings if f.severity == "error"]
    assert not [f for f in findings if f.category in {"publication", "facsimile", "instrumentation", "terms", "measures"}]
    assert before == hashlib.sha256(path.read_bytes()).digest()


@pytest.mark.skipif(shutil.which("xmllint") is None, reason="RNG integration needs xmllint")
def test_frozen_baseline_content_passes_cmn_rng(tmp_path: Path) -> None:
    from camat import run_relaxng_validation

    manifest = json.loads((BASELINE / "manifest.json").read_text())
    paths = []
    for item in manifest["inputs"]:
        path = BASELINE / item["path"]
        if item.get("optional_when_local_snapshot_absent") and not path.exists():
            continue
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        paths.append(path)
    assert len(paths) >= 3
    assert not run_relaxng_validation(paths, root=ROOT).rows


def test_standalone_fragments_cannot_resolve_in_another_selected_file(tmp_path: Path) -> None:
    first = _minimal(tmp_path / "first.mei", reference="#neighbor")
    second = _minimal(tmp_path / "second.mei", target_id="neighbor")
    standalone = check_mei_files([first, second], root_dir=tmp_path)
    assert any(f.check == "broken_internal_reference" and f.actual == "#neighbor" for f in standalone)
    assembly = check_mei_files([first, second], root_dir=tmp_path, document_mode="assembly")
    assert not [f for f in assembly if f.severity == "error"]
    assert any(f.check == "cross_file_internal_reference" for f in assembly)
    third = _minimal(tmp_path / "third.mei", target_id="neighbor")
    ambiguous = check_mei_files([first, second, third], root_dir=tmp_path, document_mode="assembly")
    assert any(f.check == "ambiguous_assembly_reference" for f in ambiguous)


def test_general_batch_does_not_impose_majority_instrumentation() -> None:
    files = [BASELINE / "minimal-cmn-51.mei", BASELINE / "Webern_Variations_for_Piano_Op27_No2.mei"]
    general = check_mei_files(files, root_dir=ROOT)
    assert not any(f.check.startswith("corpus_") for f in general)
    grouped = check_mei_files(files, root_dir=ROOT, group_diagnostics=True)
    assert any(f.check == "corpus_staff_set_variants" for f in grouped)


def test_responsibility_and_source_pointers_are_checked_and_rewritten(tmp_path: Path) -> None:
    source = _minimal(tmp_path / "source.mei")
    tree = ET.parse(source)
    root = tree.getroot()
    title_stmt = root.find(f".//{{{MEI}}}titleStmt")
    file_desc = root.find(f".//{{{MEI}}}fileDesc")
    section = root.find(f".//{{{MEI}}}section")
    assert title_stmt is not None and file_desc is not None and section is not None
    resp_stmt = ET.SubElement(title_stmt, f"{{{MEI}}}respStmt")
    ET.SubElement(resp_stmt, f"{{{MEI}}}persName", {XML_ID: "editor"}).text = "Editor"
    source_desc = ET.SubElement(file_desc, f"{{{MEI}}}sourceDesc")
    ET.SubElement(source_desc, f"{{{MEI}}}source", {XML_ID: "witness"})
    annotation = ET.SubElement(section, f"{{{MEI}}}annot", {
        XML_ID: "annotation", "resp": "#editor", "source": "#witness",
    })
    annotation.text = "Test editorial note"
    tree.write(source, encoding="utf-8", xml_declaration=True)
    second = tmp_path / "second.mei"
    shutil.copyfile(source, second)
    prepared = prepare_pages_for_combine(
        [source, second], tmp_path / "prepared", strip_ppq=False, strip_accid_ges=False,
    )
    for path in prepared.files:
        parsed = ET.parse(path).getroot()
        ids = {e.get(XML_ID) for e in parsed.iter() if e.get(XML_ID)}
        for element in parsed.iter():
            for attr, value in element.attrib.items():
                if attr in REFERENCE_ATTRS:
                    assert all(token[1:] in ids for token in value.split() if token.startswith("#"))
    annotation.set("resp", "#missing-editor")
    annotation.set("source", "#missing-witness")
    tree.write(source, encoding="utf-8", xml_declaration=True)
    broken = check_mei_files([source], root_dir=tmp_path)
    assert {f.actual for f in broken if f.check == "broken_internal_reference"} == {
        "#missing-editor", "#missing-witness",
    }


def test_valid_figured_bass_anchor_has_no_general_conversion_warning(tmp_path: Path) -> None:
    path = _minimal(tmp_path / "harm.mei")
    tree = ET.parse(path)
    measure = tree.getroot().find(f".//{{{MEI}}}measure")
    assert measure is not None
    harm = ET.SubElement(measure, f"{{{MEI}}}harm", {XML_ID: "harm", "startid": "#note-c4"})
    ET.SubElement(ET.SubElement(harm, f"{{{MEI}}}fb"), f"{{{MEI}}}f").text = "6"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    before = path.read_bytes()
    general = run_editorial_checks([path], root=tmp_path, csv_out=tmp_path / "general.csv",
                                   publication_profile=False, check_relaxng=False, check_verovio=False)
    assert general.empty
    style = run_editorial_checks([path], root=tmp_path, csv_out=tmp_path / "style.csv",
                                 publication_profile=False, check_fb_tstamp=True,
                                 check_relaxng=False, check_verovio=False)
    assert "fb_startid_to_tstamp" in set(style["check"])
    assert path.read_bytes() == before


@pytest.mark.skipif(shutil.which("xmllint") is None, reason="RNG integration needs xmllint")
def test_workflow_uses_the_explicit_schema(tmp_path: Path) -> None:
    schema = tmp_path / "different.rng"
    schema.write_text('<element xmlns="http://relaxng.org/ns/structure/1.0" name="different"><empty/></element>')
    report = run_editorial_checks(
        [BASELINE / "minimal-cmn-51.mei"], root=ROOT, csv_out=tmp_path / "custom.csv",
        publication_profile=False, schema=schema, check_verovio=False,
    )
    assert any(report["category"].eq("schema") & report["severity"].eq("error"))
