from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("verovio")

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "verovio-expansion-crash.mei"
BASIC_MUSICXML = Path(__file__).parent / "fixtures" / "basic.musicxml"
PYTHON = sys.executable

PROPER_REPEAT_MEI = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
      <meiHead><fileDesc><titleStmt><title>proper repeat</title></titleStmt><pubStmt/></fileDesc></meiHead>
      <music><body><mdiv><score>
        <scoreDef><staffGrp><staffDef n="1" lines="5">
          <clef shape="G" line="2"/><meterSig count="4" unit="4"/>
        </staffDef></staffGrp></scoreDef>
        <section>
          <measure xml:id="m1" n="1" left="rptstart" right="rptend">
            <staff n="1"><layer n="1">
              <note xml:id="n1" pname="c" oct="4" dur="1"/>
            </layer></staff>
          </measure>
          <measure xml:id="m2" n="2">
            <staff n="1"><layer n="1">
              <note xml:id="n2" pname="d" oct="4" dur="1"/>
            </layer></staff>
          </measure>
        </section>
      </score></mdiv></body></music>
    </mei>
    """
)

TWO_BACKWARD_REPEATS_MUSICXML = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <score-partwise version="4.0">
      <part-list><score-part id="P1"><part-name>Music</part-name></score-part></part-list>
      <part id="P1">
        <measure number="1">
          <attributes>
            <divisions>1</divisions>
            <key><fifths>0</fifths></key>
            <time><beats>4</beats><beat-type>4</beat-type></time>
            <clef><sign>G</sign><line>2</line></clef>
          </attributes>
          <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
          <barline location="right"><repeat direction="backward"/></barline>
        </measure>
        <measure number="2">
          <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
          <barline location="right"><repeat direction="backward"/></barline>
        </measure>
      </part>
    </score-partwise>
    """
)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def _run_child(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-c", script],
        env=_child_env(),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )


def _assert_camat_from_repo_preamble() -> str:
    return textwrap.dedent(
        f"""\
        from pathlib import Path
        import camat
        repo = Path({str(REPO_ROOT)!r}).resolve()
        assert Path(camat.__file__).resolve().is_relative_to(repo), camat.__file__
        """
    )


def _assert_expansion_error(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"child should exit 0 after catching RuntimeError; "
        f"rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "RuntimeError" in result.stdout
    assert "<expansion>" in result.stdout


@pytest.mark.parametrize(
    "loader",
    [
        "vrv_load_data",
        "vrv_load_from_file",
        "vrv_set_mei",
        "get_toolkit_loadData",
    ],
)
@pytest.mark.parametrize("timing_call", ["timemap", "elements_at_time"])
def test_crash_file_timing_raises_expansion_error(loader: str, timing_call: str) -> None:
    fixture = str(FIXTURE.resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.verovio_render import (
            get_toolkit,
            vrv_find_elements_at_time,
            vrv_load_data,
            vrv_load_from_file,
            vrv_set_mei,
            vrv_timemap,
        )
        text = Path({fixture!r}).read_text(encoding="utf-8")
        loader = {loader!r}
        if loader == "vrv_load_data":
            vrv_load_data(text, input_from="mei")
        elif loader == "vrv_load_from_file":
            vrv_load_from_file({fixture!r})
        elif loader == "vrv_set_mei":
            vrv_set_mei(text)
        elif loader == "get_toolkit_loadData":
            tk = get_toolkit()
            tk.setOptions({{"inputFrom": "mei"}})
            tk.loadData(text)
        else:
            raise AssertionError(loader)
        try:
            if {timing_call!r} == "timemap":
                vrv_timemap()
            else:
                vrv_find_elements_at_time(0)
        except RuntimeError as exc:
            print("RuntimeError:" + str(exc))
        else:
            raise SystemExit("expected RuntimeError")
        """
    )
    _assert_expansion_error(_run_child(script))


@pytest.mark.parametrize(
    "loader",
    ["vrv_load_data", "vrv_load_from_file", "vrv_set_mei"],
)
def test_proper_repeat_returns_expanded_timemap(loader: str, tmp_path: Path) -> None:
    path = tmp_path / "proper-repeat.mei"
    path.write_text(PROPER_REPEAT_MEI, encoding="utf-8")
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import json
        from camat.verovio_render import (
            vrv_load_data,
            vrv_load_from_file,
            vrv_set_mei,
            vrv_timemap,
        )
        text = Path({str(path)!r}).read_text(encoding="utf-8")
        loader = {loader!r}
        if loader == "vrv_load_data":
            vrv_load_data(text, input_from="mei")
        elif loader == "vrv_load_from_file":
            vrv_load_from_file({str(path)!r})
        else:
            vrv_set_mei(text)
        tm = vrv_timemap()
        note_ons = [eid for row in tm for eid in row.get("on", [])]
        source_notes = text.count("<note ")
        print(json.dumps({{"note_ons": len(note_ons), "source_notes": source_notes, "ids": note_ons}}))
        assert len(note_ons) > source_notes, (note_ons, source_notes)
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["note_ons"] > payload["source_notes"]


def test_crash_clean_crash_sequence_not_stale() -> None:
    fixture = str(FIXTURE.resolve())
    clean = str((Path(__file__).parent / "fixtures" / "basic.mei").resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.verovio_render import vrv_load_from_file, vrv_timemap
        results = []
        for path, expect_error in [
            ({fixture!r}, True),
            ({clean!r}, False),
            ({fixture!r}, True),
        ]:
            vrv_load_from_file(path)
            try:
                tm = vrv_timemap()
            except RuntimeError as exc:
                assert "<expansion>" in str(exc)
                results.append("error")
            else:
                assert tm is not None
                results.append("timing")
            if expect_error:
                assert results[-1] == "error"
            else:
                assert results[-1] == "timing"
        print(",".join(results))
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "error,timing,error"


def test_explicit_expand_never_allows_crash_file_timing() -> None:
    fixture = str(FIXTURE.resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.verovio_render import vrv_load_from_file, vrv_set_options, vrv_timemap
        vrv_set_options(expandNever=True)
        vrv_load_from_file({fixture!r})
        tm = vrv_timemap()
        assert tm is not None and len(tm) > 0
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ok" in result.stdout


def test_expand_never_then_false_raises_not_segfault() -> None:
    fixture = str(FIXTURE.resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.verovio_render import (
            get_toolkit,
            vrv_load_from_file,
            vrv_set_options,
            vrv_timemap,
        )
        vrv_set_options(expandNever=True)
        vrv_load_from_file({fixture!r})
        get_toolkit().setOptions({{"expandNever": False}})
        try:
            vrv_timemap()
        except RuntimeError as exc:
            print("RuntimeError:" + str(exc))
        else:
            raise SystemExit("expected RuntimeError")
        """
    )
    _assert_expansion_error(_run_child(script))


def test_repeated_timing_calls_spawn_one_child() -> None:
    path = str((Path(__file__).parent / "fixtures" / "basic.mei").resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import subprocess
        import camat.verovio_guard as guard
        from camat.verovio_render import vrv_load_from_file, vrv_timemap

        vrv_load_from_file({path!r})

        calls = []
        real_run = subprocess.run

        def wrapped(*args, **kwargs):
            calls.append(1)
            return real_run(*args, **kwargs)

        guard.subprocess.run = wrapped
        for _ in range(5):
            assert vrv_timemap() is not None
        print(len(calls))
        assert len(calls) == 1, len(calls)
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "1"


def test_empty_toolkit_timemap_matches_baseline() -> None:
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        """\
        import subprocess
        import camat.verovio_guard as guard
        from camat.verovio_render import vrv_timemap

        calls = []
        real_run = subprocess.run

        def wrapped(*args, **kwargs):
            calls.append(1)
            return real_run(*args, **kwargs)

        guard.subprocess.run = wrapped
        tm = vrv_timemap()
        print(repr(tm))
        print("child_calls=" + str(len(calls)))
        assert tm == {}
        assert calls == []
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    lines = [line for line in result.stdout.splitlines() if line.startswith("{") or line.startswith("child_")]
    assert "{}" in result.stdout
    assert "child_calls=0" in result.stdout


def test_musicxml_scores_return_timing() -> None:
    basic = str(BASIC_MUSICXML.resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.verovio_render import vrv_load_data, vrv_load_from_file, vrv_timemap
        vrv_load_from_file({basic!r})
        tm_basic = vrv_timemap()
        assert tm_basic is not None and len(tm_basic) > 0
        vrv_load_data({TWO_BACKWARD_REPEATS_MUSICXML!r}, input_from="musicxml")
        tm_rpt = vrv_timemap()
        assert tm_rpt is not None and len(tm_rpt) > 0
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ok" in result.stdout


def test_compressed_musicxml_load_clears_prepared_timing_mark() -> None:
    """A fresh .mxl load has no prepared timing, so it must not cost a rebuild."""
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import io
        import zipfile
        from camat import verovio_guard as guard
        from camat import verovio_render as render
        container = (
            '<container><rootfiles><rootfile full-path="score.xml"/></rootfiles></container>'
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("META-INF/container.xml", container)
            archive.writestr("score.xml", {TWO_BACKWARD_REPEATS_MUSICXML!r})
        guard._mark_source_order_timing(render._VRV_TOOLKIT)
        assert render._vrv_load_zip_bytes(buffer.getvalue()) > 0
        assert not guard._has_source_order_timing(render._VRV_TOOLKIT)
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ok" in result.stdout


def test_probe_failure_without_crash_does_not_blame_repeats() -> None:
    # Use a score that loads and times safely, then break only the timing probe.
    path = str((Path(__file__).parent / "fixtures" / "basic.mei").resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from types import SimpleNamespace
        import camat.verovio_guard as guard
        from camat.verovio_render import vrv_load_from_file, vrv_timemap

        vrv_load_from_file({path!r})

        def fake_run(*args, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="simulated probe failure")

        guard.subprocess.run = fake_run
        try:
            vrv_timemap()
        except RuntimeError as exc:
            msg = str(exc)
            print("RuntimeError:" + msg)
            assert "simulated probe failure" in msg or "returncode=1" in msg
            assert "<expansion>" not in msg
            assert "repeat" not in msg.lower()
        else:
            raise SystemExit("expected RuntimeError")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "RuntimeError:" in result.stdout
    assert "<expansion>" not in result.stdout


def test_probe_missing_python_does_not_blame_repeats() -> None:
    path = str((Path(__file__).parent / "fixtures" / "basic.mei").resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import camat.verovio_guard as guard
        from camat.verovio_render import vrv_load_from_file, vrv_timemap

        vrv_load_from_file({path!r})
        guard.python_executable = lambda: "/nonexistent/camat-missing-python"
        try:
            vrv_timemap()
        except RuntimeError as exc:
            msg = str(exc)
            print("RuntimeError:" + msg)
            assert "<expansion>" not in msg
            assert "repeat" not in msg.lower()
        else:
            raise SystemExit("expected RuntimeError")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "RuntimeError:" in result.stdout
    assert "<expansion>" not in result.stdout


def test_row_builder_returns_rows_on_crash_fixture() -> None:
    fixture = str(FIXTURE.resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.verovio_backend import _verovio_common_mei_dataframes
        df_pitch, df_rest, *_ = _verovio_common_mei_dataframes(
            {fixture!r},
            parse_enharmonic=True,
            include_xml_ids=True,
            quiet_native_warnings=True,
        )
        assert len(df_pitch) > 0
        print("rows=" + str(len(df_pitch)))
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, (
        f"row builder should survive; rc={result.returncode} "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "rows=" in result.stdout


def test_render_verovio_pages_resolves_tstamp_to_own_bar(tmp_path: Path) -> None:
    crash_text = FIXTURE.read_text(encoding="utf-8")
    crash_with_ids = crash_text.replace(
        '<measure n="1"', '<measure xml:id="m1" n="1"', 1
    ).replace('<measure n="2"', '<measure xml:id="m2" n="2"', 1)
    crash_path = tmp_path / "crash-with-ids.mei"
    crash_path.write_text(crash_with_ids, encoding="utf-8")
    repeat_path = tmp_path / "proper-repeat.mei"
    repeat_path.write_text(PROPER_REPEAT_MEI, encoding="utf-8")

    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import json
        from xml.etree import ElementTree as ET
        from camat.facsimile_viewer import render_verovio_pages

        opts = {{
            "pageWidth": 1000,
            "pageHeight": 1000,
            "scale": 40,
            "breaks": "auto",
            "adjustPageHeight": True,
        }}
        results = {{}}
        for label, path, measure_id, note_id in [
            ("crash", {str(crash_path)!r}, "m1", "n1"),
            ("repeat", {str(repeat_path)!r}, "m1", "n1"),
            ("repeat_bar2", {str(repeat_path)!r}, "m2", "n2"),
        ]:
            ann = [{{"anchor_mode": "tstamp", "measure_id": measure_id, "tstamp": 1.0}}]
            out = render_verovio_pages(path, initial_page=1, options=opts, annotations=ann)
            resolved = out["annotations"][0]
            root = ET.parse(path).getroot()
            NS = {{"m": "http://www.music-encoding.org/ns/mei", "xml": "http://www.w3.org/XML/1998/namespace"}}
            own_notes = {{
                note.get("{{http://www.w3.org/XML/1998/namespace}}id")
                for measure in root.iter("{{http://www.music-encoding.org/ns/mei}}measure")
                if measure.get("{{http://www.w3.org/XML/1998/namespace}}id") == measure_id
                for note in measure.iter("{{http://www.music-encoding.org/ns/mei}}note")
            }}
            assert resolved["status"] == "resolved"
            assert resolved["target_ids"]
            assert set(resolved["target_ids"]) <= own_notes
            assert note_id in resolved["target_ids"]
            results[label] = resolved["target_ids"]
        print(json.dumps(results))
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


FRACTIONAL_BAR_MEI = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
      <meiHead><fileDesc><titleStmt><title>fractional bar start</title></titleStmt><pubStmt/></fileDesc></meiHead>
      <music><body><mdiv><score>
        <scoreDef><staffGrp><staffDef n="1" lines="5">
          <clef shape="G" line="2"/><meterSig count="4" unit="4"/>
        </staffDef></staffGrp></scoreDef>
        <section>
          <measure xml:id="m1" n="1">
            <staff n="1"><layer n="1">
              <tuplet num="3" numbase="2">
                <note xml:id="t1" pname="c" oct="4" dur="8"/>
              </tuplet>
            </layer></staff>
          </measure>
          <measure xml:id="m2" n="2">
            <staff n="1"><layer n="1">
              <note xml:id="n2" pname="g" oct="4" dur="1"/>
            </layer></staff>
          </measure>
        </section>
      </score></mdiv></body></music>
    </mei>
    """
)

EMPTY_BAR_MEI = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
      <meiHead><fileDesc><titleStmt><title>empty bar</title></titleStmt><pubStmt/></fileDesc></meiHead>
      <music><body><mdiv><score>
        <scoreDef><staffGrp><staffDef n="1" lines="5">
          <clef shape="G" line="2"/><meterSig count="4" unit="4"/>
        </staffDef></staffGrp></scoreDef>
        <section>
          <measure xml:id="m1" n="1">
            <staff n="1"><layer n="1">
              <note xml:id="n1" pname="c" oct="4" dur="1"/>
            </layer></staff>
          </measure>
          <measure xml:id="m2" n="2">
            <staff n="1"><layer n="1">
              <space xml:id="sp1" dur="1"/>
            </layer></staff>
          </measure>
          <measure xml:id="m3" n="3">
            <staff n="1"><layer n="1">
              <note xml:id="n3" pname="e" oct="4" dur="1"/>
            </layer></staff>
          </measure>
        </section>
      </score></mdiv></body></music>
    </mei>
    """
)

RESTS_OPENING_MEI = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
      <meiHead><fileDesc><titleStmt><title>rests</title></titleStmt><pubStmt/></fileDesc></meiHead>
      <music><body><mdiv><score>
        <scoreDef><staffGrp>
          <staffDef n="1" lines="5"><clef shape="G" line="2"/><meterSig count="4" unit="4"/></staffDef>
          <staffDef n="2" lines="5"><clef shape="G" line="2"/></staffDef>
          <staffDef n="3" lines="5"><clef shape="G" line="2"/></staffDef>
          <staffDef n="4" lines="5"><clef shape="F" line="4"/></staffDef>
        </staffGrp></scoreDef>
        <section>
          <measure xml:id="m1" n="1">
            <staff n="1"><layer n="1"><note xml:id="n1" pname="c" oct="4" dur="1"/></layer></staff>
            <staff n="2"><layer n="1"><note xml:id="n1b" pname="e" oct="4" dur="1"/></layer></staff>
            <staff n="3"><layer n="1"><note xml:id="n1c" pname="g" oct="4" dur="1"/></layer></staff>
            <staff n="4"><layer n="1"><note xml:id="n1d" pname="c" oct="3" dur="1"/></layer></staff>
          </measure>
          <measure xml:id="m2" n="2">
            <staff n="1"><layer n="1"><rest xml:id="r1" dur="1"/></layer></staff>
            <staff n="2"><layer n="1"><rest xml:id="r2" dur="1"/></layer></staff>
            <staff n="3"><layer n="1"><rest xml:id="r3" dur="1"/></layer></staff>
            <staff n="4"><layer n="1"><rest xml:id="r4" dur="1"/></layer></staff>
          </measure>
        </section>
      </score></mdiv></body></music>
    </mei>
    """
)

NO_XML_ID_NOTES_MEI = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
      <meiHead><fileDesc><titleStmt><title>no ids</title></titleStmt><pubStmt/></fileDesc></meiHead>
      <music><body><mdiv><score>
        <scoreDef><staffGrp><staffDef n="1" lines="5">
          <clef shape="G" line="2"/><meterSig count="4" unit="4"/>
        </staffDef></staffGrp></scoreDef>
        <section>
          <measure xml:id="m1" n="1">
            <staff n="1"><layer n="1"><note pname="c" oct="4" dur="1"/></layer></staff>
          </measure>
          <measure xml:id="m2" n="2">
            <staff n="1"><layer n="1"><note pname="d" oct="4" dur="1"/></layer></staff>
          </measure>
        </section>
      </score></mdiv></body></music>
    </mei>
    """
)


def test_fractional_ms_bar_start_resolves_own_bar_note(tmp_path: Path) -> None:
    path = tmp_path / "fractional.mei"
    path.write_text(FRACTIONAL_BAR_MEI, encoding="utf-8")
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import json
        import verovio
        from camat.facsimile_viewer import render_verovio_pages

        opts = {{
            "pageWidth": 1000,
            "pageHeight": 1000,
            "scale": 40,
            "breaks": "auto",
            "adjustPageHeight": True,
        }}
        ann = [{{"anchor_mode": "tstamp", "measure_id": "m2", "tstamp": 1.0}}]
        out = render_verovio_pages({str(path)!r}, initial_page=1, options=opts, annotations=ann)
        resolved = out["annotations"][0]
        # Prove the fixture actually has a non-whole-ms bar start.
        tk = verovio.toolkit()
        tk.setOptions({{"expandNever": True}})
        tk.loadData(Path({str(path)!r}).read_text(encoding="utf-8"))
        raw_ms = float(tk.getTimeForElement("m2"))
        tm = tk.renderToTimemap({{"includeMeasures": True}})
        if isinstance(tm, str):
            tm = json.loads(tm)
        measure_row = next(row for row in tm if row.get("measureOn") == "m2")
        # Whole-ms getTimeForElement disagrees with the timemap row (cause A).
        assert float(measure_row["tstamp"]) != raw_ms
        assert resolved["status"] == "resolved"
        assert resolved["target_ids"] == ["n2"]
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_empty_bar_tstamp_is_measure_fallback_without_neighbours(tmp_path: Path) -> None:
    path = tmp_path / "empty-bar.mei"
    path.write_text(EMPTY_BAR_MEI, encoding="utf-8")
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.facsimile_viewer import render_verovio_pages
        opts = {{"pageWidth": 1000, "pageHeight": 1000, "scale": 40, "breaks": "auto", "adjustPageHeight": True}}
        ann = [{{"anchor_mode": "tstamp", "measure_id": "m2", "tstamp": 1.0}}]
        out = render_verovio_pages({str(path)!r}, initial_page=1, options=opts, annotations=ann)
        resolved = out["annotations"][0]
        assert resolved["status"] == "measure-fallback"
        assert resolved["target_ids"] == ["m2"]
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_rests_opening_bar_excludes_previous_bar_notes(tmp_path: Path) -> None:
    path = tmp_path / "rests.mei"
    path.write_text(RESTS_OPENING_MEI, encoding="utf-8")
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.facsimile_viewer import render_verovio_pages
        opts = {{"pageWidth": 1000, "pageHeight": 1000, "scale": 40, "breaks": "auto", "adjustPageHeight": True}}
        ann = [{{"anchor_mode": "tstamp", "measure_id": "m2", "tstamp": 1.0}}]
        out = render_verovio_pages({str(path)!r}, initial_page=1, options=opts, annotations=ann)
        resolved = out["annotations"][0]
        previous = {{"n1", "n1b", "n1c", "n1d"}}
        assert previous.isdisjoint(resolved["target_ids"])
        assert "m2" in resolved["target_ids"] or resolved["status"] == "measure-fallback"
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_notes_without_xml_id_still_resolve(tmp_path: Path) -> None:
    path = tmp_path / "noid.mei"
    path.write_text(NO_XML_ID_NOTES_MEI, encoding="utf-8")
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        from camat.facsimile_viewer import render_verovio_pages
        opts = {{"pageWidth": 1000, "pageHeight": 1000, "scale": 40, "breaks": "auto", "adjustPageHeight": True}}
        ann = [{{"anchor_mode": "tstamp", "measure_id": "m1", "tstamp": 1.0}}]
        out = render_verovio_pages({str(path)!r}, initial_page=1, options=opts, annotations=ann)
        resolved = out["annotations"][0]
        assert resolved["status"] == "resolved"
        assert len(resolved["target_ids"]) == 1
        assert resolved["target_ids"][0] != "m1"
        print(resolved["target_ids"][0])
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_resolve_annotations_falls_back_without_measure_on() -> None:
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        """\
        import json
        from xml.etree import ElementTree as ET
        from camat.facsimile_viewer import _resolve_render_annotations

        mei = '''<?xml version="1.0"?>
        <mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
          <music><body><mdiv><score>
            <scoreDef><staffGrp><staffDef n="1" lines="5">
              <clef shape="G" line="2"/><meterSig count="4" unit="4"/>
            </staffDef></staffGrp></scoreDef>
            <section>
              <measure xml:id="m1" n="1">
                <staff n="1"><layer n="1"><note xml:id="n1" pname="c" oct="4" dur="1"/></layer></staff>
              </measure>
            </section>
          </score></mdiv></body></music>
        </mei>'''
        root = ET.fromstring(mei)
        # Timemap without measureOn; qstamp/tstamp aligned so old interpolation works.
        timemap = [
            {"on": ["n1"], "qstamp": 0.0, "tstamp": 0.0, "tempo": 120},
            {"off": ["n1"], "qstamp": 4.0, "tstamp": 2000.0},
        ]

        class Stub:
            def renderToTimemap(self, *_a, **_k):
                return timemap

            def getPageWithElement(self, element_id):
                return 1 if element_id in {"m1", "n1"} else 0

            def getTimeForElement(self, element_id):
                assert element_id == "m1"
                return 0.0

            def getElementsAtTime(self, _ms):
                return {"notes": ["n1"], "chords": [], "rests": []}

        out = _resolve_render_annotations(
            [{"anchor_mode": "tstamp", "measure_id": "m1", "tstamp": 1.0}],
            root=root,
            toolkit=Stub(),
        )
        assert out[0]["status"] == "resolved"
        assert out[0]["target_ids"] == ["n1"]
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_sigterm_is_generic_uncached_then_crash_codes_blame_expansion() -> None:
    path = str((Path(__file__).parent / "fixtures" / "basic.mei").resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import signal
        from types import SimpleNamespace
        import camat.verovio_guard as guard
        import camat.verovio_render as render
        from camat.verovio_render import vrv_load_from_file, vrv_timemap

        vrv_load_from_file({path!r})
        calls = {{"n": 0}}
        real_run = guard.subprocess.run

        def sigterm_then_ok(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return SimpleNamespace(returncode=-int(signal.SIGTERM), stdout="", stderr="terminated")
            return real_run(*args, **kwargs)

        guard.subprocess.run = sigterm_then_ok
        try:
            vrv_timemap()
            raise SystemExit("expected generic failure")
        except RuntimeError as exc:
            msg = str(exc)
            assert "<expansion>" not in msg
            assert "repeat" not in msg.lower()
            assert "terminated" in msg or "returncode=" in msg

        # Not cached as unsafe or safe: a second call must probe again and succeed.
        before = calls["n"]
        tm = vrv_timemap()
        assert tm is not None
        assert calls["n"] == before + 1

        # Each listed crash code must produce the <expansion> message.
        crash_codes = [
            *(
                -int(getattr(signal, name))
                for name in ("SIGSEGV", "SIGABRT", "SIGBUS", "SIGILL", "SIGFPE")
                if hasattr(signal, name)
            ),
            139,
            0xC0000005,
            -1073741819,
        ]
        for code in crash_codes:
            render._VRV_TIMING_SAFE_CACHE.clear()
            guard.subprocess.run = lambda *a, code=code, **k: SimpleNamespace(
                returncode=code, stdout="", stderr="boom"
            )
            try:
                vrv_timemap()
                raise SystemExit(f"expected expansion error for {{code}}")
            except RuntimeError as exc:
                assert "<expansion>" in str(exc), (code, exc)
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_expand_never_does_not_leak_after_parse_or_viewer() -> None:
    fixture = str(FIXTURE.resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import json
        import tempfile
        from pathlib import Path
        # Backend first so verovio.toolkit() is the shared singleton.
        import camat.verovio_backend as vb
        import camat.verovio_render as vr
        import camat.facsimile_viewer as fv

        repeat = {PROPER_REPEAT_MEI!r}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repeat.mei"
            path.write_text(repeat, encoding="utf-8")
            crash = Path({fixture!r})

            def note_ons():
                vr.vrv_load_data(repeat, input_from="mei")
                tm = vr.vrv_timemap()
                return sum(len(row.get("on", [])) for row in tm)

            tk = __import__("verovio").toolkit()
            tk.setOptions({{"expandNever": False}})

            vb.parse_files_verovio([str(path)], show_progress=False)
            assert note_ons() == 3, note_ons()
            assert tk.getOptions()["expandNever"] is False

            fv.render_verovio_pages(
                path, initial_page=1, options={{"breaks": "auto"}}, annotations=[]
            )
            assert note_ons() == 3, note_ons()
            assert tk.getOptions()["expandNever"] is False

            # Exception inside the viewer still restores.
            try:
                fv.render_verovio_pages(
                    path, initial_page=99999, options={{"breaks": "auto"}}, annotations=[]
                )
            except ValueError:
                pass
            assert tk.getOptions()["expandNever"] is False

            # Exception inside the row builder still restores.
            original = vb._verovio_common_mei_dataframes_on_toolkit

            def boom(*_a, **_k):
                raise RuntimeError("boom inside row builder")

            vb._verovio_common_mei_dataframes_on_toolkit = boom
            try:
                try:
                    vb.parse_files_verovio([str(path)], show_progress=False)
                except RuntimeError as exc:
                    assert "boom inside row builder" in str(exc)
            finally:
                vb._verovio_common_mei_dataframes_on_toolkit = original
            assert tk.getOptions()["expandNever"] is False

            # Prior True is preserved.
            tk.setOptions({{"expandNever": True}})
            fv.render_verovio_pages(
                path, initial_page=1, options={{"breaks": "auto"}}, annotations=[]
            )
            assert tk.getOptions()["expandNever"] is True
            vb.parse_files_verovio([str(path)], show_progress=False)
            assert tk.getOptions()["expandNever"] is True

            # Crash file still raises after a parse/viewer used expandNever.
            tk.setOptions({{"expandNever": False}})
            vb.parse_files_verovio([str(crash)], show_progress=False)
            vr.vrv_load_from_file(str(crash))
            try:
                vr.vrv_timemap()
                raise SystemExit("expected expansion error")
            except RuntimeError as exc:
                assert "<expansion>" in str(exc)
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_timing_probe_failed_load_is_not_ok_or_crashed() -> None:
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        """\
        from camat.verovio_guard import _probe_verovio_timing
        import camat.verovio_render as render
        from camat.verovio_render import get_toolkit, vrv_timemap

        probe = _probe_verovio_timing("<not-xml", options={})
        assert probe["ok"] is False
        assert probe["crashed"] is False
        assert probe["returncode"] not in (None, 0)

        # Wrapper path: load broken content into the real toolkit without the
        # load guard, then timing must raise the generic probe failure.
        tk = get_toolkit()
        tk.setOptions({"inputFrom": "mei"})
        # Valid tiny score first so getMEI is non-empty after we swap? Use a
        # well-formed MEI that still fails in the child if we pass broken via
        # probing the function directly is enough for the probe; for the wrapper
        # feed MEI that loads in-process but make the probe see broken data by
        # calling ensure with a monkeypatched getMEI — simpler: call probe path
        # through ensure by loading valid then patching _probe_verovio_timing.
        render._probe_verovio_timing = lambda mei, options: probe
        render._VRV_TIMING_SAFE_CACHE.clear()
        # Need non-empty MEI in toolkit for ensure to run.
        tk.loadData('''<?xml version="1.0"?>
        <mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1+CMN">
          <music><body><mdiv><score>
            <scoreDef><staffGrp><staffDef n="1" lines="5"><clef shape="G" line="2"/><meterSig count="4" unit="4"/></staffDef></staffGrp></scoreDef>
            <section><measure xml:id="m1" n="1"><staff n="1"><layer n="1">
              <note xml:id="n1" pname="c" oct="4" dur="1"/>
            </layer></staff></measure></section>
          </score></mdiv></body></music></mei>''')
        try:
            vrv_timemap()
            raise SystemExit("expected generic RuntimeError")
        except RuntimeError as exc:
            msg = str(exc)
            assert "<expansion>" not in msg
            assert "probe failed" in msg.lower() or "Probe details" in msg
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_prepared_timing_rebuilds_without_reload_after_parse_or_viewer() -> None:
    fixture = str(FIXTURE.resolve())
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import tempfile
        from pathlib import Path
        import camat.verovio_backend as vb
        import camat.verovio_render as vr
        import camat.facsimile_viewer as fv

        repeat = {PROPER_REPEAT_MEI!r}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repeat.mei"
            path.write_text(repeat, encoding="utf-8")
            crash = Path({fixture!r})
            ann = [{{
                "id": "a",
                "anchor_mode": "tstamp",
                "measure_id": "m1",
                "tstamp": 1.0,
                "staff": [],
                "layer": [],
                "target_ids": [],
            }}]

            def note_ons_no_reload():
                tm = vr.vrv_timemap()
                return sum(len(row.get("on", [])) for row in tm)

            tk = __import__("verovio").toolkit()
            tk.setOptions({{"expandNever": False}})

            vb.parse_files_verovio([str(path)], show_progress=False)
            assert note_ons_no_reload() == 3, note_ons_no_reload()

            fv.render_verovio_pages(
                path,
                initial_page=1,
                options={{"breaks": "auto"}},
                annotations=ann,
            )
            assert note_ons_no_reload() == 3, note_ons_no_reload()

            vb.parse_files_verovio([str(crash)], show_progress=False)
            try:
                vr.vrv_timemap()
                raise SystemExit("expected expansion error after parse")
            except RuntimeError as exc:
                assert "<expansion>" in str(exc)

            fv.render_verovio_pages(
                crash,
                initial_page=1,
                options={{"breaks": "auto"}},
                mei_text=crash.read_text(encoding="utf-8"),
                annotations=[{{
                    "id": "a",
                    "anchor_mode": "tstamp",
                    "measure_id": None,
                    "tstamp": 1.0,
                    "staff": [],
                    "layer": [],
                    "target_ids": [],
                }}],
            )
            try:
                vr.vrv_timemap()
                raise SystemExit("expected expansion error after viewer")
            except RuntimeError as exc:
                assert "<expansion>" in str(exc)
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_user_expand_never_skips_rebuild_after_parse() -> None:
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import tempfile
        from pathlib import Path
        import camat.verovio_backend as vb
        import camat.verovio_render as vr

        repeat = {PROPER_REPEAT_MEI!r}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repeat.mei"
            path.write_text(repeat, encoding="utf-8")
            tk = __import__("verovio").toolkit()
            tk.setOptions({{"expandNever": True}})

            loads = {{"n": 0}}
            real_load = tk.loadData

            def counting_load(data):
                loads["n"] += 1
                return real_load(data)

            tk.loadData = counting_load
            vb.parse_files_verovio([str(path)], show_progress=False)
            after_parse = loads["n"]
            tm = vr.vrv_timemap()
            note_ons = sum(len(row.get("on", [])) for row in tm)
            assert note_ons == 2, note_ons
            assert loads["n"] == after_parse, loads["n"]
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_vrv_load_data_clears_mark_so_timemap_skips_rebuild() -> None:
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import tempfile
        from pathlib import Path
        import camat.verovio_backend as vb
        import camat.verovio_render as vr

        repeat = {PROPER_REPEAT_MEI!r}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repeat.mei"
            path.write_text(repeat, encoding="utf-8")
            tk = vr.get_toolkit()
            tk.setOptions({{"expandNever": False}})
            vb.parse_files_verovio([str(path)], show_progress=False)

            loads = {{"n": 0}}
            real_load = tk.loadData

            def counting_load(data):
                loads["n"] += 1
                return real_load(data)

            tk.loadData = counting_load
            before = loads["n"]
            vr.vrv_load_data(repeat, input_from="mei")
            after_load = loads["n"]
            assert after_load == before + 1, (before, after_load)
            tm = vr.vrv_timemap()
            note_ons = sum(len(row.get("on", [])) for row in tm)
            assert note_ons == 3, note_ons
            # Probe may spawn a child; rebuild would call loadData again in-process.
            assert loads["n"] == after_load, loads["n"]
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_failed_timing_rebuild_raises_generic_error() -> None:
    script = _assert_camat_from_repo_preamble() + textwrap.dedent(
        f"""\
        import tempfile
        from pathlib import Path
        import camat.verovio_backend as vb
        import camat.verovio_render as vr
        import camat.verovio_guard as guard

        repeat = {PROPER_REPEAT_MEI!r}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "repeat.mei"
            path.write_text(repeat, encoding="utf-8")
            tk = vr.get_toolkit()
            tk.setOptions({{"expandNever": False}})
            vb.parse_files_verovio([str(path)], show_progress=False)
            assert guard._has_source_order_timing(tk)

            real_load = tk.loadData

            def fail_load(data):
                return False

            tk.loadData = fail_load
            try:
                vr.vrv_timemap()
                raise SystemExit("expected generic rebuild error")
            except RuntimeError as exc:
                msg = str(exc)
                assert "<expansion>" not in msg
                assert "rebuild" in msg.lower() or "loadData" in msg
            finally:
                tk.loadData = real_load
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout


def test_verovio_guard_imports_without_sigbus() -> None:
    script = textwrap.dedent(
        f"""\
        import importlib
        import signal
        import sys
        from pathlib import Path

        repo = Path({str(REPO_ROOT)!r}).resolve()
        sys.path.insert(0, str(repo))
        if hasattr(signal, "SIGBUS"):
            delattr(signal, "SIGBUS")
        for name in list(sys.modules):
            if name == "camat" or name.startswith("camat."):
                del sys.modules[name]
        import camat.verovio_guard as guard
        assert Path(guard.__file__).resolve().is_relative_to(repo)
        assert guard._is_native_crash_returncode(-11) is True
        assert guard._is_native_crash_returncode(-15) is False
        print("ok")
        """
    )
    result = _run_child(script)
    assert result.returncode == 0, result.stderr or result.stdout
