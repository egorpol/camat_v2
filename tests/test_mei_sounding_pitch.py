"""Sounding pitches read from notation, plus lossless gestural regeneration.

The notation fixtures include DdT's reference cases and the adversarial cases
from the to-do acceptance checks. Expected pitches are written by hand.
"""
from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from camat import AccidGesReport, regenerate_accid_ges_text, resolve_mei_note_alters
from camat.check_mei_consistency import MeiChecker, check_mei_files
from camat.mei_consistency_workflow import apply_safe_cleanup, combine_meis, run_checker, run_editorial_checks

NS = "http://www.music-encoding.org/ns/mei"
NOTE = "{" + NS + "}note"
ACCID = "{" + NS + "}accid"
XID = "{http://www.w3.org/XML/1998/namespace}id"
STRIP = re.compile(r"\s+accid\.ges\s*=\s*(?:\"[^\"]*\"|'[^']*')")


def placement(text):
    return [(n.get(XID), n.get("accid.ges"), tuple(k.get("accid.ges") for k in n if k.tag == ACCID))
            for n in ET.fromstring(text).iter(NOTE)]


def doc(body, score_def):
    return (
        f'<mei xmlns="{NS}"><music><body><mdiv><score>{score_def}<section>{body}</section>'
        "</score></mdiv></body></music></mei>"
    )


def sd(*keys):
    defs = "".join(
        f'<staffDef n="{i}" lines="5">' + (f'<keySig sig="{k}"/>' if k is not None else "") + "</staffDef>"
        for i, k in enumerate(keys, 1)
    )
    return f"<scoreDef><staffGrp>{defs}</staffGrp></scoreDef>"


def n(i, p="f", o=4, x=""):
    return f'<note xml:id="{i}" dur="4" oct="{o}" pname="{p}" {x}/>'


def st(num, *events):
    return f'<staff n="{num}"><layer n="1">{"".join(events)}</layer></staff>'


def bar(*staves, num=1):
    return f'<measure n="{num}">{"".join(staves)}</measure>'


SP = '<space dur="4"/>'
SHARP = 'accid="s"'
BLANK_STAFF = 'staff="  "'
C1, C2, F1, NOKEY = sd("0"), sd("0", "0"), sd("1f"), sd(None)


def gn(i, x=""):
    return f'<note xml:id="{i}" grace="acc" dur="8" oct="4" pname="f" {x}/>'


TIE = '<tie startid="#a" endid="#b"/>'
RESOLVER = [
    ("cross-staff accidental stays on the printed staff", C2,
     bar(st(1, n("a", x='staff="2" accid="s"'), n("b")), st(2, SP, n("c"))), dict(a=1, b=0, c=1)),
    ("cross-staff note takes the printed staff's carry", C2,
     bar(st(1, SP, n("b", x='staff="2"')), st(2, n("a", x='accid="s"'), SP)), dict(a=1, b=1)),
    ("cross-staff note takes the printed staff's key", sd("1s", "0"),
     bar(st(1, n("b", x='staff="2"'), n("c"))), dict(b=0, c=1)),
    ("beam @staff sets the printed staff", C2,
     bar(st(1, SP, f'<beam staff="2">{n("b")}</beam>'), st(2, n("a", x='accid="s"'), SP)), dict(a=1, b=1)),
    ("chord @staff sets the printed staff", C2,
     bar(st(1, SP, f'<chord dur="4" staff="2">{n("b")}</chord>'), st(2, n("a", x='accid="s"'), SP)), dict(a=1, b=1)),
    ("@staff with two numbers takes the first", C2,
     bar(st(1, SP, n("b", x='staff="2 1"')), st(2, n("a", x='accid="s"'), SP)), dict(a=1, b=1)),
    ("chord tone carries, same octave only", C1,
     bar(st(1, f'<chord dur="4">{n("a", x=SHARP)}{n("b", "a")}</chord>', n("c"), n("d", o=5))),
     dict(a=1, b=0, c=1, d=0)),
    ("plain grace before a sharp main note stays natural", C1,
     bar(st(1, gn("g"), n("m", x=SHARP))), dict(g=0, m=1)),
    ("grace sharp carries to the main note", C1,
     bar(st(1, gn("g", SHARP), n("m"))), dict(g=1, m=1)),
    ("grace with no @dur before a sharp main note", C1,
     bar(st(1, '<note xml:id="g" grace="unacc" oct="4" pname="f"/>', n("m", x='accid="s"'))), dict(g=0, m=1)),
    ("graceGrp is walked and carries", C1,
     bar(st(1, f'<graceGrp>{n("g", x=SHARP)}</graceGrp>', n("m"))), dict(g=1, m=1)),
    ("consecutive graces resolve in order", C1,
     bar(st(1, gn("g1"), gn("g2", SHARP), n("m"))), dict(g1=0, g2=1, m=1)),
    ("a grace does not take a later beat of another layer", C1,
     '<measure n="1"><staff n="1"><layer n="1">' + gn("g").replace('pname="f"', 'pname="c"') + n("m") + n("m2") + "</layer>"
     '<layer n="2">' + n("x", "a", 3) + n("y", x='accid="s"') + "</layer></staff></measure>",
     dict(g=0, m=0, x=0, y=1, m2=1)),
    ("tie carries over the barline, to the tied note only", C1,
     bar(st(1, n("a", x='accid="s"')), TIE) + bar(st(1, n("b"), n("c")), num=2), dict(a=1, b=1, c=0)),
    ("barline ends the carry", C1, bar(st(1, n("a", x='accid="s"'))) + bar(st(1, n("b")), num=2), dict(a=1, b=0)),
    ("mid-layer keySig clears carry", C1,
     bar(st(1, n("a", x='accid="s"'), '<keySig sig="1f"/>', n("b"), n("c", "b"))), dict(a=1, b=0, c=-1)),
    ("no key signature leaves a plain note unresolved", NOKEY,
     bar(st(1, n("a"), n("b", x='accid="s"'), n("c"))), dict(a=None, b=1, c=1)),
    ("keySig after an mRest sets the next bar's key", C1,
     bar(st(1, '<mRest/><keySig sig="1f"/>')) + bar(st(1, n("a", "b")), num=2), dict(a=-1)),
    ("keySig after a multiRest sets the next bar's key", C1,
     bar(st(1, '<multiRest num="2"/><keySig sig="1f"/>')) + bar(st(1, n("a", "b")), num=2), dict(a=-1)),
    ("keySig after an mRest comes after the other layer's notes", C1,
     '<measure n="1"><staff n="1"><layer n="1"><mRest/><keySig sig="1f"/></layer>'
     '<layer n="2">' + n("a", "b") + n("b", "b") + "</layer></staff></measure>" + bar(st(1, n("c", "b")), num=2),
     dict(a=0, b=0, c=-1)),
    ("whitespace-only @staff falls back to the enclosing staff", C1, bar(st(1, n("a", x=BLANK_STAFF))), dict(a=0)),
    ("whitespace-only @staff on a chord tone", C1,
     bar(st(1, f'<chord dur="4">{n("a", x=BLANK_STAFF)}</chord>')), dict(a=0)),
    ("<accid> child counts as written", C1,
     bar(st(1, '<note xml:id="a" dur="4" oct="4" pname="f"><accid accid="s"/></note>', n("b"))), dict(a=1, b=1)),
]
B = '<note xml:id="a" dur="4" oct="4" pname="b"'
WRITER = [  # name, text, {id: (own value, child values)}
    ("flat from the key", doc(bar(st(1, n("a", "b"))), F1), {"a": ("f", ())}),
    ("wrong value corrected", doc(bar(st(1, n("a", "b", x='accid.ges="s"'))), F1), {"a": ("f", ())}),
    ("none beside a written @accid", doc(bar(st(1, n("a", "b", x='accid="f" accid.ges="f"'))), F1), {"a": (None, ())}),
    ("never n", doc(bar(st(1, n("a", "e", x='accid.ges="n"'))), F1), {"a": (None, ())}),
    ("correct value on a child stays there", doc(bar(st(1, B + '><accid accid.ges="f"/></note>')), F1),
     {"a": (None, ("f",))}),
    ("a note with an <accid> child takes the value there", doc(bar(st(1, B + ' accid.ges="f"><accid/></note>')), F1),
     {"a": (None, ("f",))}),
    ("one location remains", doc(bar(st(1, B + ' accid.ges="f"><accid accid.ges="f"/></note>')), F1),
     {"a": (None, ("f",))}),
    ("stale value on a tie predecessor does not spread",
     doc(bar(st(1, n("a", x='accid.ges="s"')), TIE) + bar(st(1, n("b")), num=2), C1),
     {"a": (None, ()), "b": (None, ())}),
    ("tie over the barline gets the value",
     doc(bar(st(1, n("a", x='accid="s"')), TIE) + bar(st(1, n("b")), num=2), C1),
     {"a": (None, ()), "b": ("s", ())}),
    ("unresolved note keeps its value", doc(bar(st(1, n("a", x='accid.ges="s"'))), NOKEY), {"a": ("s", ())}),
    ("carried triple sharp", doc(bar(st(1, n("a", x='accid="ts"'), n("b"))), C1), {"a": (None, ()), "b": ("ts", ())}),
    ("carried triple flat", doc(bar(st(1, n("a", x='accid="tf"'), n("b"))), C1), {"a": (None, ()), "b": ("tf", ())}),
    ("carried double flat", doc(bar(st(1, n("a", x='accid="ff"'), n("b"))), C1), {"a": (None, ()), "b": ("ff", ())}),
]
PLAIN_B = n("a", "b")
FRAME = '<?xml version="1.0" encoding="UTF-8"?>\n'


def lines(text):
    return text.replace("><", ">\n<")


def scanner_cases():
    prefixed = re.sub(r"<(/?)([A-Za-z])", r"<\1mei:\2", doc(bar(st(1, PLAIN_B)), F1)).replace("xmlns=", "xmlns:mei=")
    comment, cdata = '<!-- <note accid.ges="s"/> -->', '<annot><![CDATA[<note accid.ges="s"/>]]></annot>'
    annot, pi = '<annot>set accid.ges="s" here</annot>', '<?x <note accid.ges="s"/> ?>'
    return [  # name, text, literals that must survive
        ("comment", FRAME + doc(comment + bar(st(1, PLAIN_B)), F1), [comment]),
        ("CDATA", FRAME + doc(bar(st(1, PLAIN_B), cdata), F1), [cdata]),
        ("processing instruction", FRAME + doc(pi + bar(st(1, PLAIN_B)), F1), [pi]),
        ("annot text", FRAME + doc(bar(st(1, PLAIN_B), annot), F1), [annot]),
        ("multi-line tag", FRAME + doc(bar(st(1, '<note\n  xml:id="a"\n  dur="4"\n  oct="4"\n  pname="b"\n/>')), F1), []),
        ("> in a value", FRAME + doc(bar(st(1, n("a", "b", x='label="x>y"'))), F1), ['label="x>y"']),
        ("single quotes, stale value",
         FRAME + doc(bar(st(1, "<note xml:id='a' dur='4' oct='4' pname='b' accid.ges='s'/>")), F1), []),
        ("mei: prefix", FRAME + prefixed, []),
        ("self-closing, no space", FRAME + doc(bar(st(1, B + "/>")), F1), []),
        ("open and close tags", FRAME + doc(bar(st(1, B + "></note>")), F1), []),
        ("CRLF", (FRAME + lines(doc(bar(st(1, PLAIN_B)), F1))).replace("\n", "\r\n"), ["\r\n"]),
        ("BOM", "﻿" + FRAME + doc(bar(st(1, PLAIN_B)), F1), ["﻿"]),
        ("no xml:id", FRAME + doc(bar(st(1, '<note dur="4" oct="4" pname="b"/>')), F1), []),
    ]


@pytest.mark.parametrize("name,score_def,body,want", RESOLVER, ids=[row[0] for row in RESOLVER])
def test_resolver_notation(name, score_def, body, want):
    got = resolve_mei_note_alters(doc(body, score_def))
    assert got == {key: value for key, value in want.items() if value is not None}, name


@pytest.mark.parametrize("name,text,want", WRITER, ids=[row[0] for row in WRITER])
def test_writer_notation(name, text, want):
    out, report = regenerate_accid_ges_text(text)
    assert isinstance(report, AccidGesReport)
    assert {i: (own, kids) for i, own, kids in placement(out)} == want, name
    assert STRIP.sub("", out) == STRIP.sub("", text)
    again, second = regenerate_accid_ges_text(out)
    assert again == out
    assert second.added == second.removed == 0
    assert second.changes == []


@pytest.mark.parametrize("name,text,literals", scanner_cases(), ids=[row[0] for row in scanner_cases()])
def test_scanner_literals_and_bytes(name, text, literals):
    out, _ = regenerate_accid_ges_text(text)
    assert [own for _, own, _ in placement(out)] == ["f"], name
    for literal in literals:
        assert out.count(literal) == text.count(literal)
    assert STRIP.sub("", out).encode() == STRIP.sub("", text).encode()
    assert regenerate_accid_ges_text(out)[0] == out


def test_honor_and_stale_tie_predecessor():
    text = doc(bar(st(1, n("a", x='accid.ges="s"')), TIE) + bar(st(1, n("b")), num=2), C1)
    assert resolve_mei_note_alters(text) == {"a": 0, "b": 0}
    assert resolve_mei_note_alters(text, honor_accid_ges=True) == {"a": 1, "b": 1}
    assert "accid.ges" not in regenerate_accid_ges_text(text)[0]


def test_ddt_f_major_octave_carry():
    text = doc(bar(st(1, n("b1", "b"), n("b2", "b", x='accid="n"'), n("b3", "b"), n("b4", "b", 5))), F1)
    assert resolve_mei_note_alters(text) == dict(b1=-1, b2=0, b3=0, b4=-1)
    out, report = regenerate_accid_ges_text(text)
    assert placement(out) == [("b1", "f", ()), ("b2", None, ()), ("b3", None, ()), ("b4", "f", ())]
    assert (report.kept, report.added, report.removed) == (0, 2, 0)


def test_ddt_stale_and_duplicate_removed_child_kept():
    body = bar(st(1, n("stale", "c", x='accid.ges="s"'), n("dup", x='accid="s" accid.ges="s"'),
                  '<note xml:id="child" dur="4" oct="4" pname="b"><accid xml:id="ca" accid.ges="f"/></note>'))
    out, report = regenerate_accid_ges_text(doc(body, F1))
    assert placement(out) == [("stale", None, ()), ("dup", None, ()), ("child", None, ("f",))]
    assert (report.kept, report.added, report.removed) == (1, 0, 2)
    assert [row["id"] for row in report.changes] == ["stale", "dup"]


def test_ddt_child_precedence_and_duplicate_locations():
    body = bar(st(1, B + ' accid.ges="f"><accid xml:id="stale" accid.ges="n"/></note>',
                  B.replace('xml:id="a"', 'xml:id="b"') + ' accid.ges="n"><accid xml:id="good" accid.ges="f"/></note>'))
    out, report = regenerate_accid_ges_text(doc(body, F1))
    assert placement(out) == [("a", None, ("f",)), ("b", None, ("f",))]
    assert (report.kept, report.added, report.removed) == (1, 1, 3)


def test_later_correct_child_stays_exactly_in_place():
    text = doc(bar(st(1, B + ' accid.ges="f"><accid accid.ges="n"/><accid accid.ges=\'f\'/></note>')), F1)
    out, report = regenerate_accid_ges_text(text)
    assert placement(out) == [("a", None, (None, "f"))]
    assert "<accid accid.ges='f'/>" in out
    assert (report.kept, report.added, report.removed) == (1, 0, 2)


def test_ddt_empty_child_receives_value():
    text = doc(bar(st(1, B + '><accid xml:id="empty" glyph.auth="smufl" /></note>')), F1)
    out, _ = regenerate_accid_ges_text(text)
    assert '<accid xml:id="empty" glyph.auth="smufl" accid.ges="f" />' in out
    assert placement(out) == [("a", None, ("f",))]


def test_no_id_still_resolves_and_establishes_carry():
    text = doc(bar(st(1, '<note dur="4" oct="4" pname="f" accid="s"/>', n("b"))), C1)
    assert resolve_mei_note_alters(text) == {"b": 1}
    assert placement(regenerate_accid_ges_text(text)[0]) == [(None, None, ()), ("b", "s", ())]
    text = doc(bar(st(1, '<note dur="4" oct="4" pname="b"/>')), F1)
    assert resolve_mei_note_alters(text) == {}
    assert placement(regenerate_accid_ges_text(text)[0]) == [(None, "f", ())]


def test_no_key_is_unresolved_and_preserves_every_location():
    text = doc(bar(st(1, B + ' accid.ges="s"><accid accid.ges="f"/></note>')), NOKEY)
    out, report = regenerate_accid_ges_text(text)
    assert out == text
    assert resolve_mei_note_alters(text) == {}
    assert len(report.unresolved) == 1
    assert report.unresolved[0]["id"] == "a"
    assert report.changes == []


@pytest.mark.parametrize("accidental,alter", [("s", 1), ("f", -1), ("ss", 2), ("ff", -2), ("ts", 3), ("tf", -3)])
def test_all_supported_gestural_alterations(accidental, alter):
    text = doc(bar(st(1, n("a", x=f'accid="{accidental}"'), n("b"))), C1)
    assert resolve_mei_note_alters(text) == {"a": alter, "b": alter}
    assert placement(regenerate_accid_ges_text(text)[0]) == [("a", None, ()), ("b", accidental, ())]


def test_tuplet_and_chord_staff_precedence_with_graces():
    body = bar(st(1, '<tuplet staff="2" num="3" numbase="2"><graceGrp>' + gn("g") +
                  '</graceGrp><chord staff="1" dur="4">' + n("a") + n("b", x='staff="2 1"') +
                  '</chord></tuplet>'))
    assert resolve_mei_note_alters(doc(body, sd("1s", "0"))) == {"g": 0, "a": 1, "b": 0}


def test_simultaneous_conflicts_establish_no_carry():
    body = '<measure><staff n="1"><layer n="1">' + n("a", x='accid="s"') + n("c") + \
           '</layer><layer n="2">' + n("b", x='accid="f"') + '</layer></staff></measure>'
    assert resolve_mei_note_alters(doc(body, C1)) == {"a": 1, "b": -1, "c": 0}


def test_written_child_blocks_gestural_value():
    text = doc(bar(st(1, B + ' accid.ges="s"><accid accid="f" accid.ges="f"/></note>', n("b", "b"))), C1)
    assert resolve_mei_note_alters(text) == {"a": -1, "b": -1}
    assert placement(regenerate_accid_ges_text(text)[0]) == [("a", None, (None,)), ("b", "f", ())]


def test_scanner_does_not_touch_other_attributes_or_elements():
    text = doc(bar(st(1, B + ''' label='a accid.ges="s" >' accid.ges = 's'  />''')) +
               '<annot accid.ges="s">literal accid.ges="s"</annot>', F1)
    out, _ = regenerate_accid_ges_text(text)
    assert out == text.replace(" accid.ges = 's'", ' accid.ges="f"')


def test_entity_expansion_inventory_disagreement():
    text = '<!DOCTYPE mei [<!ENTITY e \'<note dur="4" oct="4" pname="b"/>\'>]>' + doc(bar(st(1, PLAIN_B, '&e;')), F1)
    with pytest.raises(ValueError, match="count differs"):
        regenerate_accid_ges_text(text)


def test_entity_expansion_child_disagreement():
    text = '<!DOCTYPE mei [<!ENTITY e \'<accid/>\'>]>' + doc(bar(st(1, B + '>&e;</note>')), F1)
    with pytest.raises(ValueError, match="inventory differs"):
        regenerate_accid_ges_text(text)


@pytest.mark.parametrize("fn", [resolve_mei_note_alters, regenerate_accid_ges_text])
def test_unsupported_key_is_value_error(fn):
    with pytest.raises(ValueError, match="Unsupported MEI key signature"):
        fn(doc(bar(st(1, PLAIN_B)), sd("9s")))


def save(tmp_path, text, name="score.mei"):
    path = tmp_path / name
    path.write_bytes(text.encode())
    return path


def test_check_gate_context_expected_actual_and_review_message(tmp_path):
    text = doc(bar(st(1, PLAIN_B, n("b", "b", x='accid="f" accid.ges="f"'))), F1)
    path = save(tmp_path, text)
    assert not [f for f in check_mei_files([path]) if f.check.startswith("accid_ges")]
    assert not [f for f in check_mei_files([path], editorial_diagnostics=True) if f.check.startswith("accid_ges")]
    for kwargs in ({"check_accid_ges": True}, {"publication_profile": True}):
        rows = [f for f in check_mei_files([path], root_dir=tmp_path, **kwargs) if f.check == "accid_ges_mismatch"]
        assert len(rows) == 2
        assert [(f.xml_id, f.measure_n, f.staff_n, f.layer_n) for f in rows] == [("a", "1", "1", "1"), ("b", "1", "1", "1")]
        assert all(f.severity == "warning" and f.expected and f.actual and "review" in f.message.lower() for f in rows)
    assert path.read_bytes() == text.encode()
    save(tmp_path, regenerate_accid_ges_text(text)[0])
    assert not [f for f in check_mei_files([path], check_accid_ges=True) if f.check == "accid_ges_mismatch"]


def test_check_no_id_and_unresolved(tmp_path):
    path = save(tmp_path, doc(bar(st(1, '<note dur="4" oct="4" pname="b"/>')), F1))
    rows = [f for f in MeiChecker(path, tmp_path, check_accid_ges=True).run()[0] if f.check == "accid_ges_mismatch"]
    assert len(rows) == 1 and rows[0].xml_id == "" and rows[0].measure_n == "1"
    save(tmp_path, doc(bar(st(1, n("a", x='accid.ges="s"'))), NOKEY))
    assert not [f for f in check_mei_files([path], check_accid_ges=True) if f.check.startswith("accid_ges")]


def test_check_unsupported_key_warns_once(tmp_path):
    path = save(tmp_path, doc(bar(st(1, PLAIN_B)), sd("9s")))
    rows = [f for f in check_mei_files([path], check_accid_ges=True) if f.check.startswith("accid_ges")]
    assert [f.check for f in rows] == ["accid_ges_check_skipped"]
    assert rows[0].severity == "warning"


def test_workflow_check_flags(tmp_path):
    path = save(tmp_path, doc(bar(st(1, PLAIN_B)), F1))
    rows = run_checker([path], root=tmp_path, csv_out=tmp_path / "simple.csv", check_accid_ges=True)
    assert sum(f.check == "accid_ges_mismatch" for f in rows) == 1
    df = run_editorial_checks([path], root=tmp_path, csv_out=tmp_path / "editorial.csv", check_accid_ges=True,
                              publication_profile=False, check_relaxng=False, check_verovio=False)
    assert sum(df["check"] == "accid_ges_mismatch") == 1


def test_direct_script_without_consumer_stack(tmp_path):
    blocker = tmp_path / "block"
    blocker.mkdir()
    for mod in ("numpy", "pandas"):
        (blocker / f"{mod}.py").write_text('raise ImportError("consumer stack blocked")\n')
    import os
    path = save(tmp_path, FRAME + doc(bar(st(1, PLAIN_B)), F1))
    checker = Path(__file__).resolve().parents[1] / "camat/check_mei_consistency.py"
    result = subprocess.run([sys.executable, str(checker), str(path), "--check-accid-ges", "--output", str(tmp_path / "out.csv")],
                            env={**os.environ, "PYTHONPATH": str(blocker)}, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "accid_ges_mismatch" in (tmp_path / "out.csv").read_text()


def test_combine_default_and_opt_out(tmp_path):
    path = save(tmp_path, FRAME + doc(bar(st(1, PLAIN_B)), F1))
    on = combine_meis([path], tmp_path / "on.mei")
    off = combine_meis([path], tmp_path / "off.mei", regenerate_accid_ges=False)
    assert on.accid_ges_report.added == 1 and on.accid_ges_error is None
    assert placement(on.path.read_bytes().decode()) == [("a", "f", ())]
    assert off.accid_ges_report is off.accid_ges_error is None
    assert placement(off.path.read_bytes().decode()) == [("a", None, ())]


def test_combine_unsupported_key_keeps_joined_file(tmp_path):
    path = save(tmp_path, FRAME + doc(bar(st(1, PLAIN_B)), sd("9s")))
    on = combine_meis([path], tmp_path / "on.mei")
    off = combine_meis([path], tmp_path / "off.mei", regenerate_accid_ges=False)
    assert on.accid_ges_report is None and "Unsupported" in on.accid_ges_error
    assert on.path.read_bytes() == off.path.read_bytes()


def test_cleanup_regenerates_without_other_flags_and_preserves_bytes(tmp_path):
    text = '\ufeff' + (FRAME + doc(bar(st(1, PLAIN_B, n("b", "e", x='accid.ges="n"'))), F1)).replace('\n', '\r\n')
    path = save(tmp_path, text)
    assert apply_safe_cleanup([path], root=tmp_path).changed == 0
    assert path.read_bytes() == text.encode()
    result = apply_safe_cleanup([path], root=tmp_path, clean_accid_ges=True)
    assert result.changed == 2
    assert placement(path.read_bytes().decode()) == [("a", "f", ()), ("b", None, ())]
    assert STRIP.sub("", path.read_bytes().decode()) == STRIP.sub("", text)
    assert apply_safe_cleanup([path], root=tmp_path, clean_accid_ges=True).changed == 0


def test_cleanup_runs_after_accid_and_tie_fixes(tmp_path):
    # Removing this empty child changes the writer's required attribute location.
    text = FRAME + doc(bar(st(1, B + '><accid/></note>')), F1)
    path = save(tmp_path, text)
    result = apply_safe_cleanup([path], root=tmp_path, clean_accid=True, fix_ties=True, clean_accid_ges=True)
    assert result.changed == 2
    assert placement(path.read_bytes().decode()) == [("a", "f", ())]


def test_cleanup_unsupported_key_is_review_row(tmp_path):
    text = FRAME + doc(bar(st(1, n("a", "b", x='accid.ges="s"'))), sd("9s"))
    path = save(tmp_path, text)
    result = apply_safe_cleanup([path], root=tmp_path, clean_accid_ges=True)
    assert path.read_bytes() == text.encode()
    assert result.changed == 0 and len(result.rows) == 1
    assert result.rows[0]["severity"] == "warning" and "review" in result.rows[0]["message"]
