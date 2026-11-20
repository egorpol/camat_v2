"""Editorial branch selection for ``<choice>``, ``<app>``, and ``<subst>``."""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from camat.check_mei_consistency import MeiChecker
from camat.mei_editorial import (
    EDITORIAL_CONTAINERS,
    select_editorial_branch,
    unselected_editorial_element_ids,
)
from camat.mei_sounding_pitch import (
    _extract_mei_note_effective_alters,
    _extract_mei_tie_next_map,
    resolve_mei_note_alters,
)
from camat.parser_registry import parse_files
from camat.partitura_backend import (
    _extract_mei_events,
    _extract_mei_symbolic_note_timing,
    _iter_layer_timed_children,
)

NS = "http://www.music-encoding.org/ns/mei"
XID = "{http://www.w3.org/XML/1998/namespace}id"
REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _mei(body: str, *, meter: str = 'meter.count="4" meter.unit="4"') -> str:
    return (
        f'<mei xmlns="{NS}" meiversion="5.1+CMN">'
        "<meiHead><fileDesc><titleStmt><title>Editorial</title></titleStmt>"
        "<pubStmt/></fileDesc></meiHead>"
        f'<music><body><mdiv><score><scoreDef {meter}>'
        '<keySig sig="0"/>'
        '<staffGrp><staffDef n="1" lines="5" ppq="1" clef.shape="G" clef.line="2"/>'
        f"</staffGrp></scoreDef><section>{body}</section>"
        "</score></mdiv></body></music></mei>"
    )


def _bar(content: str, *, n: int = 1, extra: str = "") -> str:
    return (
        f'<measure xml:id="m{n}" n="{n}"{extra}>'
        f'<staff n="1"><layer n="1">{content}</layer></staff>'
        "</measure>"
    )


def _note(xml_id: str, *, pname: str = "c", oct: int = 4, dur: str = "4", extra: str = "") -> str:
    attrs = f'xml:id="{xml_id}" pname="{pname}" oct="{oct}" dur="{dur}"'
    if extra:
        attrs = f"{attrs} {extra}"
    return f"<note {attrs}/>"


def _write(path: Path, body: str, **kwargs) -> Path:
    path.write_text(_mei(body, **kwargs), encoding="utf-8")
    return path


def _parse(path: Path):
    results, _, _ = parse_files(
        [str(path)],
        parsing_backend="verovio",
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        quiet_native_warnings=True,
    )
    assert len(results) == 1
    return results[0]


def _pitch_ids(df):
    return list(df["xml_id"].astype(str))


def _onsets(df, xml_id: str):
    row = df.loc[df["xml_id"].astype(str) == xml_id].iloc[0]
    return float(row["Local Onset"]), float(row["Global Onset"]), int(row["MIDI"])


# ---------------------------------------------------------------------------
# Unit: select_editorial_branch / unselected ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "xml, expected_tag",
    [
        ("<choice><sic/><corr/></choice>", "sic"),
        ("<choice><corr/><sic/></choice>", "corr"),
        ("<choice><orig/><reg/></choice>", "orig"),
        ("<choice><abbr/><expan/></choice>", "abbr"),
        ("<subst><del/><add/></subst>", "del"),
        ("<subst><add/><del/></subst>", "add"),
        ("<app><lem/><rdg/><rdg/></app>", "lem"),
        ("<app><rdg/><rdg/></app>", "rdg"),
        ("<app><note/><rdg/></app>", "rdg"),
        ("<app><note/><space/></app>", "note"),
        ("<choice/>", None),
        ("<app/>", None),
        ("<subst/>", None),
    ],
)
def test_select_editorial_branch_defaults(xml, expected_tag):
    el = ET.fromstring(xml)
    selected = select_editorial_branch(el)
    if expected_tag is None:
        assert selected is None
    else:
        assert selected is not None
        assert selected.tag == expected_tag


def test_unselected_editorial_element_ids_nested():
    root = ET.fromstring(
        "<score>"
        "<app>"
        '<lem><choice><sic><note id="a"/></sic><corr><note id="b"/></corr></choice></lem>'
        '<rdg><note id="c"/></rdg>'
        "</app>"
        '<note id="d"/>'
        "</score>"
    )
    unselected = unselected_editorial_element_ids(root)
    notes = {el.get("id"): el for el in root.iter() if el.tag == "note"}
    assert id(notes["a"]) not in unselected
    assert id(notes["b"]) in unselected
    assert id(notes["c"]) in unselected
    assert id(notes["d"]) not in unselected
    assert EDITORIAL_CONTAINERS == frozenset({"choice", "app", "subst"})


# ---------------------------------------------------------------------------
# Invariant 1: parse_files keeps selected reading; no onset shift
# ---------------------------------------------------------------------------


def test_choice_note_matches_plain_control(tmp_path: Path):
    control = _write(
        tmp_path / "control.mei",
        _bar(_note("n1") + _note("n2", pname="d") + _note("n3", pname="e") + _note("n4", pname="f"))
        + _bar(_note("n5", pname="g"), n=2),
    )
    editorial = _write(
        tmp_path / "choice.mei",
        _bar(
            "<choice>"
            f"<sic>{_note('n1')}</sic>"
            f"<corr>{_note('n1b', pname='b')}</corr>"
            "</choice>"
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        )
        + _bar(_note("n5", pname="g"), n=2),
    )
    ctrl = _parse(control)["df_pitch"]
    edit = _parse(editorial)["df_pitch"]
    assert _pitch_ids(edit) == _pitch_ids(ctrl) == ["n1", "n2", "n3", "n4", "n5"]
    for xid in _pitch_ids(ctrl):
        assert _onsets(edit, xid) == _onsets(ctrl, xid)
    # Bar 2 must start at global onset 4.0 (not shifted by a false upbeat).
    assert _onsets(edit, "n5")[1] == pytest.approx(4.0)


@pytest.mark.parametrize(
    "wrapper, selected_id, rejected_id",
    [
        (
            lambda s, r: f"<choice><corr>{s}</corr><sic>{r}</sic></choice>",
            "sel",
            "rej",
        ),
        (
            lambda s, r: f"<app><lem>{s}</lem><rdg>{r}</rdg></app>",
            "sel",
            "rej",
        ),
        (
            lambda s, r: f"<app><rdg>{s}</rdg><rdg>{r}</rdg></app>",
            "sel",
            "rej",
        ),
        (
            lambda s, r: f"<subst><add>{s}</add><del>{r}</del></subst>",
            "sel",
            "rej",
        ),
    ],
)
def test_editorial_wrappers_select_first_reading(tmp_path: Path, wrapper, selected_id, rejected_id):
    selected = _note(selected_id, pname="c")
    rejected = _note(rejected_id, pname="b")
    path = _write(
        tmp_path / "wrap.mei",
        _bar(
            wrapper(selected, rejected)
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
    )
    df = _parse(path)["df_pitch"]
    ids = _pitch_ids(df)
    assert selected_id in ids
    assert rejected_id not in ids
    assert _onsets(df, selected_id)[0] == pytest.approx(0.0)


def test_nested_app_choice_selects_inner_first_child(tmp_path: Path):
    path = _write(
        tmp_path / "nested.mei",
        _bar(
            "<app><lem><choice>"
            f"<sic>{_note('keep')}</sic>"
            f"<corr>{_note('drop-inner', pname='b')}</corr>"
            "</choice></lem>"
            f"<rdg>{_note('drop-outer', pname='a')}</rdg></app>"
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
    )
    ids = _pitch_ids(_parse(path)["df_pitch"])
    assert ids == ["keep", "n2", "n3", "n4"]


def test_editorial_inside_beam_and_tuplet(tmp_path: Path):
    path = _write(
        tmp_path / "beam-tuplet.mei",
        _bar(
            "<beam>"
            "<choice>"
            f"<sic>{_note('b1', dur='8')}</sic>"
            f"<corr>{_note('b1x', pname='b', dur='8')}</corr>"
            "</choice>"
            + _note("b2", pname="d", dur="8")
            + "</beam>"
            '<tuplet num="3" numbase="2">'
            "<subst>"
            f"<add>{_note('t1', pname='e', dur='8')}</add>"
            f"<del>{_note('t1x', pname='f', dur='8')}</del>"
            "</subst>"
            + _note("t2", pname="g", dur="8")
            + _note("t3", pname="a", dur="8")
            + "</tuplet>"
            + _note("n4", pname="b")
        ),
    )
    df = _parse(path)["df_pitch"]
    ids = _pitch_ids(df)
    assert "b1" in ids and "b1x" not in ids
    assert "t1" in ids and "t1x" not in ids
    assert set(ids) == {"b1", "b2", "t1", "t2", "t3", "n4"}


# ---------------------------------------------------------------------------
# Invariant 2: accidental carryover isolation
# ---------------------------------------------------------------------------


def test_unselected_accidental_does_not_carry(tmp_path: Path):
    text = _mei(
        _bar(
            "<choice>"
            + "<sic>" + _note("n1") + "</sic>"
            + "<corr>" + _note("n1x", extra='accid="s"') + "</corr>"
            + "</choice>"
            + _note("n2")
            + _note("n3", pname="d")
            + _note("n4", pname="e")
        )
    )
    alters = resolve_mei_note_alters(text)
    assert alters["n1"] == 0
    assert alters["n2"] == 0
    assert "n1x" not in alters

    selected_sharp = _mei(
        _bar(
            "<choice>"
            + "<sic>" + _note("n1", extra='accid="s"') + "</sic>"
            + "<corr>" + _note("n1x") + "</corr>"
            + "</choice>"
            + _note("n2")
            + _note("n3", pname="d")
            + _note("n4", pname="e")
        )
    )
    alters_sel = resolve_mei_note_alters(selected_sharp)
    assert alters_sel["n1"] == 1
    assert alters_sel["n2"] == 1


def test_effective_alters_ignore_unselected_notes():
    root = ET.fromstring(
        _mei(
            _bar(
                "<app><lem>"
                + _note("keep")
                + "</lem><rdg>"
                + _note("drop", extra='accid="s"')
                + "</rdg></app>"
                + _note("later")
                + _note("n3", pname="d")
                + _note("n4", pname="e")
            )
        )
    )
    effective = _extract_mei_note_effective_alters(root)
    notes = {el.get(XID): el for el in root.iter() if el.tag.endswith("note")}
    assert id(notes["keep"]) in effective
    assert id(notes["drop"]) not in effective
    assert effective[id(notes["later"])] == 0


# ---------------------------------------------------------------------------
# Invariant 3: tie isolation
# ---------------------------------------------------------------------------


def test_unselected_tie_element_does_not_attach(tmp_path: Path):
    path = _write(
        tmp_path / "tie-el.mei",
        _bar(
            _note("a", extra='tie="i"')
            + "<choice>"
            + "<sic>" + _note("b", extra='tie="t"') + "</sic>"
            + "<corr>" + _note("bx", pname="b", extra='tie="t"') + '<tie startid="#a" endid="#bx"/></corr>'
            + "</choice>"
            + _note("c", pname="d")
            + _note("d", pname="e")
        )
    )
    root = ET.parse(path).getroot()
    tie_next = _extract_mei_tie_next_map(root)
    assert tie_next.get("a") == "b"
    assert "bx" not in tie_next.values()


def test_unselected_tie_attr_does_not_leak_across_bars(tmp_path: Path):
    path = _write(
        tmp_path / "tie-attr.mei",
        _bar(
            "<choice>"
            + "<sic>" + _note("a") + "</sic>"
            + "<corr>" + _note("ax", pname="b", extra='tie="i"') + "</corr>"
            + "</choice>"
            + _note("b2", pname="d")
            + _note("b3", pname="e")
            + _note("b4", pname="f")
        )
        + _bar(_note("c", pname="b", extra='tie="t"') + _note("d", pname="d") + _note("e", pname="e") + _note("f", pname="f"), n=2),
    )
    root = ET.parse(path).getroot()
    tie_next = _extract_mei_tie_next_map(root)
    assert "ax" not in tie_next
    assert tie_next.get("ax") is None
    # Selected branch has no open tie; bar-2 stop must not attach to anything.
    assert "a" not in tie_next


# ---------------------------------------------------------------------------
# Invariant 4: no double-counting in timing / rhythm checks
# ---------------------------------------------------------------------------


def test_symbolic_timing_sums_selected_branch_only(tmp_path: Path):
    path = _write(
        tmp_path / "timing.mei",
        _bar(
            "<choice>"
            f"<sic>{_note('n1')}</sic>"
            f"<corr>{_note('n1x', pname='b')}</corr>"
            "</choice>"
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        )
    )
    timing, offsets = _extract_mei_symbolic_note_timing(str(path))
    assert set(timing) == {"n1", "n2", "n3", "n4"}
    assert "n1x" not in timing
    assert offsets[0] == pytest.approx(0.0)
    # Selected branch spans exactly one 4/4 bar (not 5.0 from double-counting).
    assert timing["n4"]["Global Onset"] + timing["n4"]["Duration"] == pytest.approx(4.0)


@pytest.mark.parametrize(
    "body",
    [
        _bar(
            "<choice>"
            f"<sic>{_note('n1')}</sic>"
            f"<corr>{_note('n1x', pname='b')}</corr>"
            "</choice>"
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
        _bar(
            "<app><lem>"
            f"{_note('n1')}"
            "</lem><rdg>"
            f"{_note('n1x', pname='b')}"
            "</rdg></app>"
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
        _bar(
            "<subst><add>"
            f"{_note('n1')}"
            "</add><del>"
            f"{_note('n1x', pname='b')}"
            "</del></subst>"
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
    ],
)
def test_layer_rhythm_no_false_overfull(tmp_path: Path, body: str):
    path = _write(tmp_path / "rhythm.mei", body)
    findings, _, _ = MeiChecker(path, tmp_path).run()
    rhythm = [f for f in findings if f.check.startswith("layer_duration_")]
    assert rhythm == []


# ---------------------------------------------------------------------------
# Invariant 5: event extraction / layer indexing isolation
# ---------------------------------------------------------------------------


def test_events_ignore_unselected_control_events(tmp_path: Path):
    path = _write(
        tmp_path / "events.mei",
        '<measure xml:id="m1" n="1">'
        '<staff n="1"><layer n="1">'
        + _note("n1")
        + _note("n2", pname="d")
        + _note("n3", pname="e")
        + _note("n4", pname="f")
        + "</layer></staff>"
        "<choice>"
        '<sic><dynam xml:id="dyn-keep" staff="1" tstamp="1">p</dynam></sic>'
        '<corr><dynam xml:id="dyn-drop" staff="1" tstamp="1">f</dynam></corr>'
        "</choice>"
        "</measure>",
    )
    events = _extract_mei_events(str(path))
    dynam_ids = [e.get("xml_id") for e in events if e.get("event") == "dynamic"]
    assert "dyn-keep" in dynam_ids
    assert "dyn-drop" not in dynam_ids


def test_iter_layer_timed_children_skips_unselected(tmp_path: Path):
    path = _write(
        tmp_path / "iter.mei",
        _bar(
            "<choice>"
            f"<sic>{_note('keep')}</sic>"
            f"<corr>{_note('drop', pname='b')}</corr>"
            "</choice>"
            + _note("n2", pname="d")
        ),
    )
    root = ET.parse(path).getroot()
    layer = next(el for el in root.iter() if el.tag.endswith("layer"))
    timed = list(_iter_layer_timed_children(layer))
    ids = [el.get(XID) for el, _mult, _grace in timed]
    assert ids == ["keep", "n2"]


# ---------------------------------------------------------------------------
# Invariant 6: standalone consistency checker script
# ---------------------------------------------------------------------------


def test_check_mei_consistency_standalone_help():
    script = REPO / "camat" / "check_mei_consistency.py"
    result = subprocess.run(
        [PYTHON, str(script), "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    assert result.returncode == 0, result.stderr
    assert "usage" in result.stdout.lower() or "mei" in result.stdout.lower()


def test_check_mei_consistency_standalone_on_editorial_file(tmp_path: Path):
    path = _write(
        tmp_path / "standalone.mei",
        _bar(
            "<choice>"
            f"<sic>{_note('n1')}</sic>"
            f"<corr>{_note('n1x', pname='b')}</corr>"
            "</choice>"
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
    )
    script = REPO / "camat" / "check_mei_consistency.py"
    result = subprocess.run(
        [PYTHON, str(script), str(path)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "layer_duration_overfull" not in result.stdout
    assert "layer_duration_overfull" not in result.stderr


# ---------------------------------------------------------------------------
# Invariant 7: non-editorial files unchanged vs control shape
# ---------------------------------------------------------------------------


def test_non_editorial_file_unchanged(tmp_path: Path):
    body = _bar(
        _note("n1") + _note("n2", pname="d") + _note("n3", pname="e") + _note("n4", pname="f")
    ) + _bar(
        _note("n5", pname="g")
        + _note("n6", pname="a")
        + _note("n7", pname="b")
        + _note("n8", pname="c", oct=5),
        n=2,
    )
    path = _write(tmp_path / "plain.mei", body)
    df = _parse(path)["df_pitch"]
    assert _pitch_ids(df) == ["n1", "n2", "n3", "n4", "n5", "n6", "n7", "n8"]
    assert _onsets(df, "n5")[1] == pytest.approx(4.0)
    findings, _, _ = MeiChecker(path, tmp_path).run()
    assert not any(f.check.startswith("layer_duration_") for f in findings)


def test_mei_editorial_not_exported():
    import camat

    assert "mei_editorial" not in camat.__all__
    assert not hasattr(camat, "select_editorial_branch")
    assert not hasattr(camat, "EDITORIAL_CONTAINERS")


# ---------------------------------------------------------------------------
# Round 2 findings
# ---------------------------------------------------------------------------


def test_standalone_supplied_not_expanded(tmp_path: Path):
    """Invariant 7: standalone reading wrappers must not be unwrapped."""
    from camat.mei_editorial import iter_selected_children

    root = ET.fromstring(
        "<layer>"
        '<supplied><note xml:id="sup1" dur="4"/></supplied>'
        '<note xml:id="n2" dur="4"/>'
        "</layer>"
    )
    kids = list(iter_selected_children(root))
    assert [c.tag for c in kids] == ["supplied", "note"]
    path = _write(
        tmp_path / "supplied.mei",
        _bar(
            '<supplied><note xml:id="sup1" pname="c" oct="4" dur="4"/></supplied>'
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
    )
    ids = _pitch_ids(_parse(path)["df_pitch"])
    assert "sup1" not in ids


def test_selected_itertext_skips_unselected_branch():
    from camat.mei_editorial import selected_itertext, unselected_editorial_element_ids

    el = ET.fromstring(
        "<dir>pre <choice><sic>Allegro</sic><corr>Adagio</corr></choice> post</dir>"
    )
    unselected = unselected_editorial_element_ids(el)
    text = " ".join(selected_itertext(el, unselected).split())
    assert text == "pre Allegro post"


def test_unselected_scoredef_meter_does_not_shift(tmp_path: Path):
    body = (
        '<measure xml:id="m1" n="1"><staff n="1"><layer n="1">'
        '<mRest xml:id="mr1"/></layer></staff></measure>'
        '<choice><sic/><corr><scoreDef meter.count="3" meter.unit="4"/></corr></choice>'
        '<measure xml:id="m2" n="2"><staff n="1"><layer n="1">'
        '<mRest xml:id="mr2"/></layer></staff></measure>'
        '<measure xml:id="m3" n="3"><staff n="1"><layer n="1">'
        '<note xml:id="m3n1" pname="c" oct="4" dur="1"/>'
        "</layer></staff></measure>"
    )
    path = _write(tmp_path / "meter.mei", body)
    df = _parse(path)["df_pitch"]
    assert _onsets(df, "m3n1")[1] == pytest.approx(8.0)


def test_note_internal_choice_accid_and_carry(tmp_path: Path):
    text = _mei(
        _bar(
            '<note xml:id="f1" pname="f" oct="4" dur="4">'
            '<choice><sic><accid accid="s"/></sic><corr><accid accid="n"/></corr></choice>'
            "</note>"
            + _note("f2", pname="f")
            + _note("n3", pname="d")
            + _note("n4", pname="e")
        )
    )
    alters = resolve_mei_note_alters(text)
    assert alters["f1"] == 1
    assert alters["f2"] == 1
    path = tmp_path / "note_accid.mei"
    path.write_text(text, encoding="utf-8")
    df = _parse(path)["df_pitch"]
    midis = [int(df.loc[df["xml_id"] == xid, "MIDI"].iloc[0]) for xid in ("f1", "f2")]
    assert midis == [66, 66]


def test_choice_inside_chord(tmp_path: Path):
    path = _write(
        tmp_path / "chord_choice.mei",
        _bar(
            '<chord xml:id="ch1" dur="4">'
            '<note xml:id="cn1" pname="c" oct="4"/>'
            '<choice><sic><note xml:id="cn2" pname="e" oct="4">'
            '<accid accid="f"/></note></sic>'
            '<corr><note xml:id="cn2x" pname="e" oct="4"/></corr></choice>'
            "</chord>"
            + _note("e2", pname="e")
            + _note("n3", pname="d")
            + _note("n4", pname="f")
        ),
    )
    df = _parse(path)["df_pitch"]
    ids = _pitch_ids(df)
    assert "cn2" in ids and "cn2x" not in ids
    assert int(df.loc[df["xml_id"] == "e2", "MIDI"].iloc[0]) == 63
    findings, _, _ = MeiChecker(path, tmp_path).run()
    assert not any(f.check.startswith("layer_duration_") for f in findings)


def test_unselected_tie_element_does_not_stamp_df_pitch_tied(tmp_path: Path):
    path = _write(
        tmp_path / "tie_stamp.mei",
        '<measure xml:id="m1" n="1"><staff n="1"><layer n="1">'
        + _note("b_end", pname="b", oct=3)
        + _note("n2", pname="d")
        + _note("n3", pname="e")
        + _note("n4", pname="f")
        + "</layer></staff>"
        '<choice><sic/><corr><tie startid="#b_end" endid="#b_next"/></corr></choice>'
        "</measure>"
        '<measure xml:id="m2" n="2"><staff n="1"><layer n="1">'
        + _note("b_next", pname="b", oct=3)
        + _note("n6", pname="g")
        + _note("n7", pname="a")
        + _note("n8", pname="b")
        + "</layer></staff></measure>",
    )
    df = _parse(path)["df_pitch"]
    if "tied" in df.columns:
        stamped = df.loc[df["xml_id"].isin(["b_end", "b_next"]), "tied"].dropna()
        assert list(stamped) == [] or all(not str(v).strip() for v in stamped)


def test_dir_text_selected_branch_only(tmp_path: Path):
    path = _write(
        tmp_path / "dir_text.mei",
        '<measure xml:id="m1" n="1"><staff n="1"><layer n="1">'
        + _note("n1")
        + _note("n2", pname="d")
        + _note("n3", pname="e")
        + _note("n4", pname="f")
        + "</layer></staff>"
        '<dir xml:id="d1" staff="1" tstamp="1">'
        "<choice><sic>Allegro</sic><corr>Adagio</corr></choice></dir>"
        "</measure>",
    )
    events = _extract_mei_events(str(path))
    texts = [e.get("text") for e in events if e.get("xml_id") == "d1"]
    assert texts == ["Allegro"]


def test_partitura_backend_loads_choice_mei(tmp_path: Path):
    path = _write(
        tmp_path / "partitura_choice.mei",
        _bar(
            _note("n1")
            + "<choice>"
            f"<sic>{_note('sic', pname='b', oct=3)}</sic>"
            f"<corr>{_note('corr', pname='b', oct=3)}</corr>"
            "</choice>"
            + _note("n3", pname="d")
            + _note("n4", pname="e")
        ),
    )
    results, _, _ = parse_files(
        [str(path)],
        parsing_backend="partitura",
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        quiet_native_warnings=True,
    )
    ids = list(results[0]["df_pitch"]["xml_id"].astype(str))
    assert ids == ["n1", "sic", "n3", "n4"]


def test_gracegrp_inside_choice_no_rhythm_error(tmp_path: Path):
    path = _write(
        tmp_path / "grace_choice.mei",
        _bar(
            "<choice>"
            '<sic><graceGrp grace="acc">'
            '<note xml:id="g1" pname="b" oct="3" dur="8"/>'
            "</graceGrp></sic>"
            '<corr><graceGrp grace="acc">'
            '<note xml:id="g2" pname="a" oct="3" dur="8"/>'
            "</graceGrp></corr>"
            "</choice>"
            + _note("n1")
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
    )
    timing, _ = _extract_mei_symbolic_note_timing(str(path))
    assert timing["n4"]["Local Onset"] == pytest.approx(3.0)
    findings, _, _ = MeiChecker(path, tmp_path).run()
    assert not any(
        f.category == "rhythm" and f.severity in ("error", "warning") for f in findings
    )


def test_unselected_broken_source_still_flagged(tmp_path: Path):
    path = _write(
        tmp_path / "badref.mei",
        _bar(
            _note("n1")
            + '<app><lem source="#srcA">'
            + _note("keep", pname="b", oct=3)
            + '</lem><rdg source="#missing_src">'
            + _note("drop", pname="a", oct=3)
            + "</rdg></app>"
            + _note("n3", pname="d")
            + _note("n4", pname="e")
        ),
    )
    # Inject sourceDesc ids referenced by lem only.
    text = path.read_text(encoding="utf-8").replace(
        "<pubStmt/>",
        '<pubStmt/><sourceDesc><source xml:id="srcA"/></sourceDesc>',
        1,
    )
    path.write_text(text, encoding="utf-8")
    findings, _, _ = MeiChecker(path, tmp_path).run()
    ref_hits = [
        f
        for f in findings
        if "missing_src" in (f.actual or "")
        or "missing_src" in (f.message or "")
        or f.category == "references"
    ]
    assert ref_hits


def test_note_internal_choice_accid_does_not_leak_event(tmp_path: Path):
    path = _write(
        tmp_path / "note-choice-accid.mei",
        _bar(
            '<note xml:id="f1" pname="f" oct="4" dur="4">'
            '<choice><sic><accid xml:id="ac1" accid="s"/></sic>'
            '<corr><accid xml:id="ac2" accid="n"/></corr></choice>'
            "</note>"
            + _note("n2", pname="g")
            + _note("n3", pname="a")
            + _note("n4", pname="b")
        ),
    )
    events = _extract_mei_events(str(path))
    assert not any(ev.get("xml_id") in {"ac1", "ac2"} for ev in events)


def test_gracegrp_chord_keeps_zero_duration_and_bar_onsets(tmp_path: Path):
    path = _write(
        tmp_path / "grace-chord.mei",
        _bar(
            '<choice>'
            '<sic><graceGrp grace="acc"><chord xml:id="gc1" dur="8">'
            '<note xml:id="gn1" pname="c" oct="4"/><note xml:id="gn2" pname="e" oct="4"/>'
            "</chord></graceGrp></sic>"
            '<corr><graceGrp grace="acc"><note xml:id="gn3" pname="d" oct="4" dur="8"/></graceGrp></corr>'
            "</choice>"
            + _note("n1")
            + _note("n2", pname="d")
            + _note("n3", pname="e")
            + _note("n4", pname="f")
        ),
    )
    df = _parse(path)["df_pitch"]
    assert _pitch_ids(df) == ["n1", "n2", "n3", "n4"]
    assert [float(x) for x in df["Local Onset"]] == [0.0, 1.0, 2.0, 3.0]


def test_resolve_editorial_containers_preserves_leading_text_outside_child():
    from camat.mei_editorial import resolve_editorial_containers_in_tree

    root = ET.fromstring(
        "<dir>Fast <choice><sic>molto <rend>allegro</rend></sic>"
        "<corr>adagio</corr></choice>!</dir>"
    )
    assert resolve_editorial_containers_in_tree(root) is True
    rend = root.find("rend")
    assert rend is not None
    assert root.text == "Fast molto "
    assert rend.text == "allegro"
    assert rend.tail == "!"
