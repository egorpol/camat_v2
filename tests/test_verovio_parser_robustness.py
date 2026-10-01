from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import test_verovio_parser_robustness as runner


@pytest.mark.parametrize("selection", ["empty_folder", "empty_list", "missing_list"])
def test_empty_selection_fails_and_replaces_old_report(tmp_path: Path, monkeypatch, capsys, selection: str) -> None:
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_run_isolated", lambda *args, **kwargs: pytest.fail("No worker should run"))
    report = tmp_path / "report.json"
    report.write_text('[{"status": "ok", "source": "old.mei"}]')
    args = ["--json", str(report)]
    if selection != "empty_folder":
        source_list = tmp_path / "scores.txt"
        if selection == "empty_list":
            source_list.write_text("\n# No scores selected\n")
        args.extend(["--source", str(source_list)])
    assert runner.main(args) == 2
    assert json.loads(report.read_text()) == []
    output = capsys.readouterr()
    assert "Selected: 0; tested: 0; passed: 0; failed: 0" in output.out
    assert ("Source list does not exist" if selection == "missing_list" else "nothing was tested") in output.err


def test_missing_list_cannot_be_silently_dropped_from_mixed_selection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "REPO_ROOT", tmp_path)
    report = tmp_path / "report.json"
    monkeypatch.setattr(runner, "_run_isolated", lambda *args, **kwargs: pytest.fail("Incomplete selection must fail"))
    assert runner.main([
        "--source", "valid.mei", "--source", "missing.txt", "--json", str(report),
    ]) == 2
    assert json.loads(report.read_text()) == []


@pytest.mark.parametrize("statuses,exit_code", [(["ok"], 0), (["ok", "invalid"], 1), ([], 1)])
def test_success_requires_a_result_for_every_selected_score(tmp_path: Path, monkeypatch, capsys, statuses, exit_code) -> None:
    sources = [str(tmp_path / "first.mei"), str(tmp_path / "second.mei")]
    selected = sources[:max(1, len(statuses))]
    records = [{"source": source, "status": status} for source, status in zip(selected, statuses)]
    monkeypatch.setattr(runner, "_resolve_sources", lambda *args: selected)
    monkeypatch.setattr(runner, "_run_isolated", lambda *args, **kwargs: records)
    report = tmp_path / "report.json"
    assert runner.main(["--json", str(report)]) == exit_code
    assert json.loads(report.read_text()) == records
    output = capsys.readouterr()
    passed = statuses.count("ok")
    assert f"Selected: {len(selected)}; tested: {len(records)}; passed: {passed}; failed: {len(records) - passed}" in output.out
    if not records:
        assert "Not every selected score produced a result" in output.err


def test_source_counts_exclude_incipit_and_filter_note_or_chord_grace(tmp_path: Path) -> None:
    source = tmp_path / "grace.mei"
    source.write_text('''<mei xmlns="http://www.music-encoding.org/ns/mei">
      <meiHead><workList><work><incip><score><section><measure><note/></measure></section></score></incip></work></workList></meiHead>
      <music><body><mdiv><score><section><measure>
        <note/><note grace="unacc"/>
        <chord grace="acc"><note/><note grace="unacc"/></chord>
        <chord><note/></chord>
      </measure></section></score></mdiv></body></music>
    </mei>''')
    assert runner._source_stats(source) == {
        "source_measures": 1, "source_notes": 5,
        "source_grace_notes": 3, "expected_pitch_rows": 2,
    }


def test_grace_filtering_does_not_hide_missing_ordinary_notes() -> None:
    frame = pd.DataFrame([{column: 1 for column in runner.REQUIRED_PITCH_COLUMNS}])
    assert not runner._validate_pitch_dataframe(frame, 1)
    assert any("expected 2 notes" in issue for issue in runner._validate_pitch_dataframe(frame, 2))
    assert any("expected 0 notes" in issue for issue in runner._validate_pitch_dataframe(frame, 0))


def test_fixed_source_list_matches_manifest() -> None:
    root = Path(__file__).resolve().parents[1]
    baseline = root / "test_corpus/parser_robustness"
    manifest = json.loads((baseline / "manifest.json").read_text())
    sources = runner._resolve_sources([str(baseline / "sources.txt")])
    assert sources == [str(root / item["path"]) for item in manifest["inputs"]]
    for item, source in zip(manifest["inputs"], sources):
        stats = runner._source_stats(Path(source))
        assert stats == {
            "source_measures": item["music_measures"],
            "source_notes": item["source_notes"],
            "source_grace_notes": item["source_grace_notes"],
            "expected_pitch_rows": item["expected_pitch_rows"],
        }
