from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from camat import (
    Finding,
    MEI_CMN_51_SCHEMA,
    check_mei_files,
    convert_harm_startid_to_tstamp,
    link_pb_to_surface,
    run_checker,
)


def _write_editorial_fixture(path: Path) -> None:
    path.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
  <meiHead><fileDesc><titleStmt><title>Editorial checks</title></titleStmt>
    <pubStmt><p>Test fixture</p></pubStmt></fileDesc></meiHead>
  <facsimile>
    <surface xml:id="surface-1">
      <graphic target="scan.jpg" width="1000" height="1400" />
      <zone xml:id="zone-1" type="measure" ulx="10" uly="20" lrx="900" lry="500" />
    </surface>
  </facsimile>
  <music><body><mdiv><score>
    <scoreDef meter.count="4" meter.unit="4">
      <staffGrp><staffDef n="1" lines="5" /></staffGrp>
    </scoreDef>
    <section>
      <pb xml:id="pb-1" />
      <measure xml:id="measure-1" n="1" facs="#zone-1">
        <staff n="1"><layer n="1">
          <note xml:id="note-1" pname="c" oct="4" dur="4" />
        </layer></staff>
        <harm xml:id="harm-1" startid="#note-1"><fb><f>6</f></fb></harm>
      </measure>
    </section>
  </score></mdiv></body></music>
</mei>
''',
        encoding="utf-8",
    )


def test_package_checker_returns_findings_and_writes_reports(tmp_path: Path) -> None:
    mei_path = Path("tests/fixtures/basic.mei").resolve()

    findings = check_mei_files([mei_path], root_dir=Path.cwd())

    assert all(finding.file == "tests/fixtures/basic.mei" for finding in findings)
    assert not any(finding.check == "well_formed_xml" for finding in findings)

    csv_path = tmp_path / "report.csv"
    json_path = tmp_path / "report.json"
    written_findings = run_checker(
        [mei_path],
        root=Path.cwd(),
        csv_out=csv_path,
        json_out=json_path,
    )

    report = pd.read_csv(csv_path)
    assert len(report) == len(written_findings)
    assert list(report.columns) == list(Finding.__dataclass_fields__)
    assert len(json.loads(json_path.read_text(encoding="utf-8"))) == len(written_findings)


def test_pinned_mei_schema_is_packaged() -> None:
    assert MEI_CMN_51_SCHEMA.is_file()
    assert "Licensed under the Educational Community License" in MEI_CMN_51_SCHEMA.read_text(
        encoding="utf-8"
    )[:1000]


def test_figured_bass_and_page_break_helpers_support_dry_run_and_apply(
    tmp_path: Path,
) -> None:
    mei_path = tmp_path / "editorial.mei"
    _write_editorial_fixture(mei_path)

    harm_check = convert_harm_startid_to_tstamp(mei_path)
    pb_check = link_pb_to_surface(mei_path)

    assert harm_check.applied is False
    assert harm_check.converted == 1
    assert pb_check.applied is False
    assert pb_check.updates == 1
    original = mei_path.read_text(encoding="utf-8")
    assert 'startid="#note-1"' in original
    assert '<pb xml:id="pb-1" />' in original

    harm_apply = convert_harm_startid_to_tstamp(mei_path, apply=True)
    pb_apply = link_pb_to_surface(mei_path, apply=True)
    updated = mei_path.read_text(encoding="utf-8")

    assert harm_apply.changed is True
    assert pb_apply.changed is True
    assert 'startid="#note-1"' not in updated
    assert 'tstamp="1"' in updated
    assert 'staff="1"' in updated
    assert '<pb xml:id="pb-1" facs="#surface-1" />' in updated
