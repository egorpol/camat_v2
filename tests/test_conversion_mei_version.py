"""Conversion records, resume compatibility, and real Humdrum MEI targets."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from camat import conversion
from camat.mei_consistency_workflow import run_relaxng_validation


KERN = """**kern\t**dynam
*>[A,A,B]\t*>[A,A,B]
*>norep[A,B]\t*>norep[A,B]
*>A\t*>A
*M4/4\t*M4/4
=1\t=1
!\t!LO:DY:ed=paren
4c\tp
4d\t.
4e\t.
4f\t.
=2:|!\t=2:|!
*>B\t*>B
1ryy\t.
==\t==
*-\t*-
"""
SYNTHETIC_MEI = '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="6.0-dev">\r\n</mei>\r\n'


@pytest.fixture
def fake_verovio(monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run

    def run(args, **kwargs):
        if conversion.CONVERT_CHILD in args:
            Path(args[7]).write_bytes(SYNTHETIC_MEI.encode("utf-8"))
            return subprocess.CompletedProcess(args, 0, json.dumps({"svg_ok": None, "verovio_version": "test"}), "")
        return real_run(args, **kwargs)

    monkeypatch.setattr(conversion.subprocess, "run", run)
    monkeypatch.setattr(conversion, "_verovio_version", lambda: "test")


def convert(source: Path, output: Path, **kwargs) -> dict:
    return conversion.convert_sources(
        [str(source)], output_dir=output, render_first_page=False,
        show_progress=False, expand_txt_sources=False, **kwargs,
    )[0]


def test_no_target_payload_signatures_and_old_resume_sidecar(fake_verovio, tmp_path: Path) -> None:
    source = tmp_path / "source.krn"
    source.write_text(KERN, encoding="utf-8")
    first = convert(source, tmp_path / "out")
    expected_options = {
        "midi": conversion.MidiImportOptions().to_dict(),
        "download": conversion.DownloadOptions().to_dict(),
        "verovio": dict(conversion.DEFAULT_VEROVIO_OPTIONS),
        "render_first_page": False,
    }
    assert conversion._conversion_options_payload(
        midi_options=conversion.MidiImportOptions(), download_options=conversion.DownloadOptions(),
        verovio_options=conversion.DEFAULT_VEROVIO_OPTIONS, render_first_page=False,
    ) == expected_options
    assert first["conversion_options"] == expected_options
    assert first["options_fingerprint"] == conversion._conversion_signature(expected_options)
    expected_signature = conversion._conversion_signature({
        "report_schema_version": 2, "source_sha256": first["source_sha256"],
        "input_from": "humdrum", "conversion_route": "verovio-direct",
        "conversion_options": expected_options,
        "tool_versions": {"music21": None, "musescore": None, "verovio": "test"},
    })
    assert first["conversion_signature"] == expected_signature
    assert first["mei_version_target"] is None
    assert first["mei_version_rewrite"] is None
    output = Path(first["output_mei"])
    assert output.read_bytes() == SYNTHETIC_MEI.encode("utf-8")
    sidecar = output.with_name(output.name + ".camat.json")
    stored = json.loads(sidecar.read_text())
    del stored["record"]["mei_version_target"]
    del stored["record"]["mei_version_rewrite"]
    sidecar.write_text(json.dumps(stored), encoding="utf-8")
    resumed = convert(source, tmp_path / "out", resume_policy="if-unchanged")
    assert resumed["skipped"] is True
    assert resumed["conversion_signature"] == first["conversion_signature"]
    assert resumed["mei_version_target"] is None
    assert resumed["mei_version_rewrite"] is None


def test_target_value_validation_and_failure_record(tmp_path: Path) -> None:
    for value in ("6.0", "5.0", "", 5.1):
        with pytest.raises(ValueError, match="mei_version"):
            conversion.convert_sources([], output_dir=tmp_path, mei_version=value)
    record = convert(tmp_path / "missing.krn", tmp_path / "out", mei_version="5.1")
    assert record["status"] == "fail"
    assert record["failure_stage"] == "download"
    assert record["mei_version_target"] == "5.1"
    assert record["mei_version_rewrite"] is None
    with pytest.raises(SystemExit) as exc:
        conversion.main(["--mei-version", "6.0"])
    assert exc.value.code == 2


def test_mei_pass_through_is_not_applicable_and_cli_succeeds(tmp_path: Path) -> None:
    source = tmp_path / "source.mei"
    original = SYNTHETIC_MEI.encode("utf-8")
    source.write_bytes(original)
    record = convert(source, tmp_path / "out", mei_version="5.1")
    assert record["status"] == "ok"
    assert record["mei_version"] == "6.0-dev"
    assert record["mei_version_rewrite"]["status"] == "not_applicable"
    assert record["mei_version_rewrite"]["source_mei_version"] == "6.0-dev"
    assert record["output_mei"] == str(source)
    assert source.read_bytes() == original
    assert conversion.main([
        "--source", str(source), "--output-dir", str(tmp_path / "cli"), "--no-render", "--mei-version", "5.1",
    ]) == 0


def test_missing_xmllint_does_not_fail_batch(fake_verovio, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def missing(*_args, **_kwargs):
        raise RuntimeError("xmllint is required for the pinned RELAX NG validation pass.")

    monkeypatch.setattr("camat.mei_consistency_workflow.run_relaxng_validation", missing)
    sources = [tmp_path / f"source{n}.krn" for n in range(2)]
    for source in sources:
        source.write_text(KERN, encoding="utf-8")
    records = conversion.convert_sources(
        list(map(str, sources)), output_dir=tmp_path / "out", render_first_page=False,
        show_progress=False, mei_version="5.1",
    )
    for record in records:
        assert record["status"] == "ok"
        assert record["mei_version"] == "6.0-dev"
        assert record["mei_version_rewrite"]["status"] == "incomplete"
        assert "xmllint" in record["mei_version_rewrite"]["remaining_errors"][0]["message"]
        assert Path(record["output_mei"]).read_bytes() == SYNTHETIC_MEI.encode("utf-8")


@pytest.mark.skipif(shutil.which("xmllint") is None, reason="xmllint is unavailable")
def test_humdrum_target_records_and_resume(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    pytest.importorskip("verovio")
    source = tmp_path / "source.krn"
    source.write_text(KERN, encoding="utf-8")
    first = convert(source, tmp_path / "out", mei_version="5.1")
    assert first["status"] == "ok", first.get("error")
    assert first["mei_version_target"] == first["mei_version"] == "5.1"
    assert first["conversion_options"]["mei_version"] == "5.1"
    rewrite = first["mei_version_rewrite"]
    assert rewrite["status"] == "rewritten"
    assert rewrite["source_mei_version"] == "6.0-dev"
    assert rewrite["rewrites"] == {
        "meiversion": 1, "mrest_to_mspace": 1, "choice_unwrapped": 1, "dynam_enclose_dropped": 1,
    }
    assert rewrite["dynam_enclose_dropped"] == [{"xml_id": "dynam-L8F2", "text": "p", "enclose": "paren"}]
    assert rewrite["remaining_errors"] == rewrite["unrewritable"] == []
    assert first["validation_stages"]["valid_mei"] == {
        "status": "passed", "details": "Validated against the bundled MEI 5.1 CMN schema.",
    }
    output = Path(first["output_mei"])
    original = output.read_bytes()
    assert not run_relaxng_validation([output], root=tmp_path).rows
    assert first["output_size_bytes"] == len(original)
    assert first["output_sha256"] == hashlib.sha256(original).hexdigest()
    sidecar = json.loads(output.with_name(output.name + ".camat.json").read_text())
    assert sidecar["record"]["mei_version_rewrite"] == rewrite
    resumed = convert(source, tmp_path / "out", mei_version="5.1", resume_policy="if-unchanged")
    assert resumed["skipped"] is True
    assert resumed["mei_version_rewrite"] == rewrite
    assert output.read_bytes() == original
    plain = convert(source, tmp_path / "out", resume_policy="if-unchanged")
    assert plain["skipped"] is False
    assert plain["mei_version"] == "6.0-dev"
    assert plain["conversion_signature"] != first["conversion_signature"]
    again = convert(source, tmp_path / "out", mei_version="5.1", resume_policy="if-unchanged")
    assert again["skipped"] is False
    assert again["mei_version_rewrite"]["status"] == "rewritten"
    conversion.print_conversion_summary([again])
    assert "1 rewritten file(s)" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("xmllint") is None, reason="xmllint is unavailable")
def test_humdrum_outside_supplied_incomplete_bytes_and_cli_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    pytest.importorskip("verovio")
    source = tmp_path / "outside.krn"
    source.write_text(KERN.replace("!LO:DY:ed=paren", "!LO:DY:paren"), encoding="utf-8")
    rewrite_output = conversion._rewrite_output_mei_version

    def check_unchanged(path: Path, target: str) -> dict:
        before = path.read_bytes()
        report = rewrite_output(path, target)
        assert path.read_bytes() == before
        return report

    monkeypatch.setattr(conversion, "_rewrite_output_mei_version", check_unchanged)
    args = ["--source", str(source), "--output-dir", str(tmp_path / "out"), "--no-render", "--mei-version", "5.1"]
    assert conversion.main(args) == 1
    printed = capsys.readouterr().out
    assert "incomplete" in printed and "outside.krn" in printed and "enclose" in printed
    record = json.loads((tmp_path / "out" / "conversion_report.json").read_text())[0]
    assert record["status"] == "ok"
    assert record["mei_version"] == "6.0-dev"
    assert record["mei_version_rewrite"]["status"] == "incomplete"
    assert record["validation_stages"]["valid_mei"] == {
        "status": "passed", "details": "MEI XML parsed successfully.",
    }
    assert any(row["xml_id"] == "dynam-L8F2" for row in record["mei_version_rewrite"]["unrewritable"])
    assert any("enclose" in row["message"] for row in record["mei_version_rewrite"]["remaining_errors"])
    assert not any("meiversion" in row["message"] for row in record["mei_version_rewrite"]["remaining_errors"])
    assert conversion.main([*args, "--resume"]) == 1
    resumed = json.loads((tmp_path / "out" / "conversion_report.json").read_text())[0]
    assert resumed["skipped"] is True
    assert resumed["mei_version_rewrite"] == record["mei_version_rewrite"]
