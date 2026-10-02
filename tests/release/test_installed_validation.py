from __future__ import annotations

from importlib.metadata import distribution
from importlib.resources import files
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

import camat
from camat.mei_schematron import COMPILER


REPO_ROOT = Path(os.environ["CAMAT_REPO_ROOT"]).resolve()
BASE = REPO_ROOT / "test_corpus" / "validation_baseline" / "minimal-cmn-51.mei"
MEI = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def test_validation_assets_and_license_are_installed() -> None:
    package = Path(camat.__file__).resolve().parent
    assert not package.is_relative_to(REPO_ROOT / "camat")
    assert camat.MEI_CMN_51_SCHEMA.resolve().is_relative_to(package)
    assert COMPILER.resolve().is_relative_to(package)
    assert camat.MEI_CMN_51_SCHEMA.read_bytes() == (REPO_ROOT / "camat/schemas/mei-CMN-5.1.rng").read_bytes()

    compiler_source = REPO_ROOT / "camat/schemas/schxslt"
    assets = [*compiler_source.rglob("*.xsl"), compiler_source / "README.md"]
    assert assets
    for source in assets:
        packaged = files("camat").joinpath("schemas", "schxslt", source.relative_to(compiler_source).as_posix())
        assert packaged.is_file(), f"Missing compiler asset: {source.name}"
        assert packaged.read_bytes() == source.read_bytes()

    dist = distribution("camat")
    licenses = [path for path in dist.files or () if path.name == "SchXslt-MIT.txt"]
    assert len(licenses) == 1
    assert dist.locate_file(licenses[0]).read_bytes() == (REPO_ROOT / "LICENSES/SchXslt-MIT.txt").read_bytes()


def test_valid_mei_passes_with_packaged_validators(tmp_path: Path) -> None:
    before = BASE.read_bytes()
    result = camat.run_mei_validation(
        [BASE], root=tmp_path, output_dir=tmp_path / "validation-valid",
    )
    assert result.passed, result.findings
    assert result.record["completion_status"] == "completed"
    for check in result.record["required_checks"]:
        assert result.record["executions"][check]["status"] == "passed"
    schematron = result.record["executions"]["schematron"]
    assert schematron["rule_count"] > 0
    assert all(Path(path).is_file() for path in schematron["svrl"])
    assert BASE.read_bytes() == before


@pytest.mark.parametrize("validator", ["relaxng", "schematron"])
def test_invalid_mei_is_rejected_by_packaged_validators(tmp_path: Path, validator: str) -> None:
    tree = ET.parse(BASE)
    if validator == "relaxng":
        tree.getroot().find(f".//{{{MEI}}}note").set("pname", "invalid")
    else:
        measure = tree.getroot().find(f".//{{{MEI}}}measure")
        ET.SubElement(measure, f"{{{MEI}}}harm", {XML_ID: "unanchored-harm"}).text = "I"
    source = tmp_path / "invalid.mei"
    tree.write(source, encoding="utf-8", xml_declaration=True)
    before = source.read_bytes()
    output = tmp_path / f"validation-{validator}"
    result = camat.run_mei_validation([source], root=tmp_path, output_dir=output)
    assert not result.passed
    assert result.record["completion_status"] == "completed"
    assert result.record["conformance"] == "failed"
    assert result.record["executions"][validator]["status"] == "failed"
    if validator == "schematron":
        assert result.record["executions"]["relaxng"]["status"] == "passed"
        assert result.record["executions"]["schematron"]["error_assertions"] > 0
    assert source.read_bytes() == before
    assert json.loads((output / "run.json").read_text())["conformance"] == "failed"
