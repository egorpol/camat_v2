from __future__ import annotations

from pathlib import Path

import pytest

from camat import check_mei_files


def write_score(path: Path, music: str, *, metcon: str | None = "false") -> None:
    flag = "" if metcon is None else f' metcon="{metcon}"'
    path.write_text(
        '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">'
        '<music><body><mdiv><score><scoreDef meter.count="4" meter.unit="4">'
        '<staffGrp><staffDef n="1" lines="5" ppq="1"/></staffGrp>'
        '</scoreDef><section>'
        f'<measure xml:id="m1" n="1"{flag}><staff n="1">'
        f'<layer xml:id="voice1" n="1">{music}</layer></staff></measure>'
        '</section></score></mdiv></body></music></mei>',
        encoding="utf-8",
    )


@pytest.mark.parametrize("metcon", [None, "true", "false"])
def test_hidden_extra_eighth_is_reported_with_any_meter_marker(tmp_path, metcon):
    score = tmp_path / "overfull.mei"
    write_score(score, '<note xml:id="n1" pname="c" oct="4" dur="1"/>'
                '<space xml:id="padding" dur="8"/>', metcon=metcon)
    before = score.read_bytes()
    rows = [r for r in check_mei_files([score], root_dir=tmp_path)
            if r.check == "layer_duration_overfull"]
    assert len(rows) == 1
    row = rows[0]
    assert (row.severity, row.measure_n, row.staff_n, row.layer_n, row.xml_id) == (
        "warning", "1", "1", "1", "voice1")
    assert (row.expected, row.actual) == ("4", "9/2")
    assert ('@metcon="false"' in row.context) == (metcon == "false")
    assert score.read_bytes() == before


def test_marked_pickup_remains_visible_as_a_review_warning(tmp_path):
    score = tmp_path / "pickup.mei"
    write_score(score, '<note xml:id="n1" pname="c" oct="4" dur="4"/>')
    rows = [r for r in check_mei_files([score], root_dir=tmp_path)
            if r.check == "layer_duration_underfull"]
    assert len(rows) == 1
    assert rows[0].severity == "warning"
    assert (rows[0].expected, rows[0].actual) == ("4", "1")
    assert '@metcon="false"' in rows[0].context
    assert "may be intentional" in rows[0].context
    assert "missing space/rest is a likely cause" not in rows[0].context


def test_complete_marked_measure_does_not_gain_a_duration_mismatch(tmp_path):
    score = tmp_path / "complete.mei"
    write_score(score, '<note xml:id="n1" pname="c" oct="4" dur="1"/>')
    assert not any(r.check.startswith("layer_duration_")
                   for r in check_mei_files([score], root_dir=tmp_path))


def test_dotted_chord_and_scaled_tuplet_fill_a_marked_bar(tmp_path):
    score = tmp_path / "complete-polyphony.mei"
    write_score(score,
        '<chord xml:id="ch" dur="2" dots="1">'
        '<note xml:id="n1" pname="c" oct="4"/>'
        '<note xml:id="n2" pname="e" oct="4"/></chord>'
        '<tuplet num="3" numbase="2">'
        '<note xml:id="t1" pname="d" oct="4" dur="8"/>'
        '<note xml:id="t2" pname="e" oct="4" dur="8"/>'
        '<note xml:id="t3" pname="f" oct="4" dur="8"/>'
        '</tuplet>')
    assert not any(r.check.startswith("layer_duration_")
                   for r in check_mei_files([score], root_dir=tmp_path))
