"""Unit tests for scripts/strip_facsimile.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "strip_facsimile.py"


def run_strip(source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), str(output)],
        capture_output=True,
        text=True,
    )


def test_strip_removes_facsimile_and_keeps_other_facs_token(tmp_path: Path) -> None:
    source = tmp_path / "in.mei"
    source.write_text(
        '<?xml version="1.0"?>\n'
        '<mei xmlns="http://www.music-encoding.org/ns/mei">\n'
        "  <music>\n"
        '    <facsimile>\n'
        '      <surface xml:id="surf1">\n'
        '        <zone xml:id="zone1"/>\n'
        "      </surface>\n"
        "    </facsimile>\n"
        "    <body>\n"
        '      <measure xml:id="m1" facs="#zone1 #other"/>\n'
        '      <measure xml:id="m2" facs="#zone1"/>\n'
        "    </body>\n"
        "  </music>\n"
        "</mei>\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.mei"
    result = run_strip(source, output)
    assert result.returncode == 0, result.stderr
    text = output.read_text(encoding="utf-8")
    assert "<facsimile>" not in text
    assert '<measure xml:id="m1" facs="#other"/>' in text
    assert '<measure xml:id="m2"/>' in text


def test_strip_refuses_second_facsimile(tmp_path: Path) -> None:
    source = tmp_path / "in.mei"
    source.write_text(
        '<mei xmlns="http://www.music-encoding.org/ns/mei">\n'
        "  <music>\n"
        "    <facsimile>\n"
        '      <surface xml:id="a"/>\n'
        "    </facsimile>\n"
        "    <facsimile>\n"
        '      <surface xml:id="b"/>\n'
        "    </facsimile>\n"
        "  </music>\n"
        "</mei>\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.mei"
    result = run_strip(source, output)
    assert result.returncode != 0
    assert "2 <facsimile>" in result.stderr
    assert not output.exists()


def test_strip_refuses_dangling_corresp(tmp_path: Path) -> None:
    source = tmp_path / "in.mei"
    source.write_text(
        '<mei xmlns="http://www.music-encoding.org/ns/mei">\n'
        "  <music>\n"
        '    <facsimile>\n'
        '      <surface xml:id="surf1"/>\n'
        "    </facsimile>\n"
        '    <body><annot corresp="#surf1"/></body>\n'
        "  </music>\n"
        "</mei>\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.mei"
    result = run_strip(source, output)
    assert result.returncode != 0
    assert "surf1" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("attr", ["target", "plist", "startid", "sameas", "endid"])
def test_strip_refuses_other_ref_attrs(tmp_path: Path, attr: str) -> None:
    source = tmp_path / "in.mei"
    source.write_text(
        '<mei xmlns="http://www.music-encoding.org/ns/mei">\n'
        "  <music>\n"
        '    <facsimile>\n'
        '      <zone xml:id="zoneX"/>\n'
        "    </facsimile>\n"
        f'    <body><annot {attr}="#zoneX"/></body>\n'
        "  </music>\n"
        "</mei>\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.mei"
    result = run_strip(source, output)
    assert result.returncode != 0
    assert "zoneX" in result.stderr
    assert not output.exists()


def test_strip_keeps_crlf_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "in.mei"
    source.write_bytes(
        b'<mei xmlns="http://www.music-encoding.org/ns/mei">\r\n'
        b"  <music>\r\n"
        b"    <facsimile>\r\n"
        b'      <zone xml:id="zoneX"/>\r\n'
        b"    </facsimile>\r\n"
        b'    <body><measure n="1" facs="#zoneX"/></body>\r\n'
        b"  </music>\r\n"
        b"</mei>\r\n"
    )
    output = tmp_path / "out.mei"
    assert run_strip(source, output).returncode == 0
    assert output.read_bytes() == (
        b'<mei xmlns="http://www.music-encoding.org/ns/mei">\r\n'
        b"  <music>\r\n"
        b'    <body><measure n="1"/></body>\r\n'
        b"  </music>\r\n"
        b"</mei>\r\n"
    )


def _mei(facsimile: str, body: str) -> str:
    return (
        '<mei xmlns="http://www.music-encoding.org/ns/mei">\n'
        "  <music>\n"
        f"{facsimile}"
        f"    <body>{body}</body>\n"
        "  </music>\n"
        "</mei>\n"
    )


FACSIMILE = "    <facsimile>\n      <zone xml:id=\"zoneX\"/>\n    </facsimile>\n"


@pytest.mark.parametrize("reference", ["corresp = '#zoneX'", 'endid ="#zoneX"', "facs='#zoneX' corresp='#a #zoneX'"])
def test_strip_refuses_references_in_any_quoting(tmp_path: Path, reference: str) -> None:
    source = tmp_path / "in.mei"
    source.write_text(_mei(FACSIMILE, f"<annot {reference}/>"), encoding="utf-8")
    output = tmp_path / "out.mei"
    result = run_strip(source, output)
    assert result.returncode != 0
    assert "zoneX" in result.stderr
    assert not output.exists()


def test_strip_leaves_unrelated_facs_byte_identical(tmp_path: Path) -> None:
    source = tmp_path / "in.mei"
    source.write_text(
        _mei(FACSIMILE, "<measure facs='#zoneX'/><measure facs=\"#elsewhere   #another\"/>"),
        encoding="utf-8",
    )
    output = tmp_path / "out.mei"
    assert run_strip(source, output).returncode == 0
    assert output.read_text(encoding="utf-8") == _mei(
        "", "<measure/><measure facs=\"#elsewhere   #another\"/>"
    )


def test_strip_refuses_second_facsimile_on_a_shared_line(tmp_path: Path) -> None:
    source = tmp_path / "in.mei"
    source.write_text(
        _mei(FACSIMILE + "    <!-- other --><facsimile><zone xml:id=\"zoneY\"/></facsimile>\n", ""),
        encoding="utf-8",
    )
    output = tmp_path / "out.mei"
    result = run_strip(source, output)
    assert result.returncode != 0
    assert "2 <facsimile>" in result.stderr
    assert not output.exists()
