"""Synthetic, offline checks of the conservative MEI version text edits."""
from __future__ import annotations

from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import pytest

from camat.conversion import _rewrite_output_mei_version
from camat.mei_consistency_workflow import run_relaxng_validation
from camat.mei_version import rewrite_mei_version


def mei_text(events: str = '<mRest xml:id="rest" />', *, controls: str = "", section: str = "", metadata: str = "") -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="6.0-dev">
   <meiHead>
      <fileDesc><titleStmt><title>Étude</title></titleStmt><pubStmt /></fileDesc>
      {metadata}
   </meiHead>
   <music><body><mdiv><score>
      <scoreDef meter.count="4" meter.unit="4">
         <staffGrp><staffDef n="1" lines="5" clef.shape="G" clef.line="2" /></staffGrp>
      </scoreDef>
      <section xml:id="section">
         {section}
         <measure xml:id="measure" n="1">
            <staff n="1"><layer n="1">
               {events}
            </layer></staff>
            {controls}
         </measure>
      </section>
   </score></mdiv></body></music>
</mei>
'''


REPEAT_CHOICE = '''<choice xml:id="choice">
            <orig xml:id="original">
               <expansion xml:id="repeat" plist="#section #section" />
            </orig>
            <reg xml:id="regular" type="norep">
               <expansion xml:id="norepeat" plist="#section" type="norep" />
            </reg>
         </choice>'''
EDITORIAL = '''<supplied xml:id="supplied">
               <dynam xml:id="dynamic" type="editorial" staff="1" tstamp="1" enclose="paren" vgrp="100">p</dynam>
            </supplied>'''
requires_xmllint = pytest.mark.skipif(shutil.which("xmllint") is None, reason="xmllint is unavailable")


@requires_xmllint
@pytest.mark.parametrize("text,key", [
    (mei_text(), "meiversion"),
    (mei_text('<mRest xml:id="hidden" visible="false" />'), "mrest_to_mspace"),
    (mei_text(section=REPEAT_CHOICE), "choice_unwrapped"),
    (mei_text(controls=EDITORIAL), "dynam_enclose_dropped"),
])
def test_each_rewrite_prepares_valid_mei_51(text: str, key: str, tmp_path: Path) -> None:
    result = rewrite_mei_version(text)
    assert result.text is not None
    assert not result.unrewritable
    assert result.rewrites[key] == 1
    candidate = tmp_path / "candidate.mei"
    candidate.write_bytes(result.text.encode("utf-8"))
    assert not run_relaxng_validation([candidate], root=tmp_path).rows


@pytest.mark.parametrize("rest", [
    '<mRest xml:id="hidden" visible="false" dur="4" />',
    '<mRest xml:id="hidden" dur="4" visible="false"></mRest>',
])
def test_hidden_rest_keeps_all_other_attributes_and_closing_tag(rest: str) -> None:
    text = mei_text(rest)
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"').replace(
        ' visible="false"', "",
    ).replace("mRest", "mSpace")


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_repeat_lists_keep_source_order_and_sibling_indentation(newline: str) -> None:
    text = '''<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="6.0-dev">
   <section xml:id="section">
      <choice xml:id="choice">
         <orig xml:id="original">
            <expansion xml:id="repeat" plist="#section #section" />
         </orig>
         <reg xml:id="regular" type="norep">
            <expansion xml:id="norepeat" plist="#section" type="norep" />
         </reg>
      </choice>
   </section>
</mei>
'''.replace("\n", newline)
    expected = '''<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">
   <section xml:id="section">
      <expansion xml:id="repeat" plist="#section #section" />
      <expansion xml:id="norepeat" plist="#section" type="norep" />
   </section>
</mei>
'''.replace("\n", newline)
    result = rewrite_mei_version(text)
    assert result.text == expected
    assert all(line.strip() for line in result.text.splitlines())
    expansions = ET.fromstring(result.text).findall(".//{http://www.music-encoding.org/ns/mei}expansion")
    assert [e.get("{http://www.w3.org/XML/1998/namespace}id") for e in expansions] == ["repeat", "norepeat"]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_compact_repeat_choice_only_removes_tags(newline: str) -> None:
    text = '''<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="6.0-dev">
   <section xml:id="section">
      <choice xml:id="choice"><orig xml:id="original"><expansion xml:id="repeat" plist="#section #section" /></orig><reg xml:id="regular" type="norep"><expansion xml:id="norepeat" plist="#section" type="norep" /></reg></choice>
   </section>
</mei>
'''.replace("\n", newline)
    expected = '''<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">
   <section xml:id="section">
      <expansion xml:id="repeat" plist="#section #section" /><expansion xml:id="norepeat" plist="#section" type="norep" />
   </section>
</mei>
'''.replace("\n", newline)
    result = rewrite_mei_version(text)
    assert result.text == expected
    assert not result.unrewritable


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_wrapper_lines_with_comments_are_kept_without_reindenting(newline: str) -> None:
    text = '''<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="6.0-dev">
   <section xml:id="section">
      <choice xml:id="choice"><!-- choice comment -->
         <orig xml:id="original"><!-- orig comment -->
            <expansion xml:id="repeat" plist="#section #section" />
         </orig>
         <reg xml:id="regular" type="norep">
            <expansion xml:id="norepeat" plist="#section" type="norep" />
         </reg>
      </choice><!-- following comment -->
   </section>
</mei>
'''.replace("\n", newline)
    expected = '''<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">
   <section xml:id="section">
      <!-- choice comment -->
         <!-- orig comment -->
            <expansion xml:id="repeat" plist="#section #section" />
            <expansion xml:id="norepeat" plist="#section" type="norep" />
      <!-- following comment -->
   </section>
</mei>
'''.replace("\n", newline)
    result = rewrite_mei_version(text)
    assert result.text == expected
    assert not result.unrewritable


def test_editorial_dynamic_reports_text_and_old_value() -> None:
    text = mei_text(controls=EDITORIAL.replace(">p</dynam>", ">p &amp; f</dynam>"))
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"').replace(' enclose="paren"', "")
    assert result.dynam_enclose_dropped == [{"xml_id": "dynamic", "text": "p & f", "enclose": "paren"}]


@requires_xmllint
@pytest.mark.parametrize("text,element,error", [
    (mei_text(controls='<dynam xml:id="dynamic" staff="1" tstamp="1" enclose="paren">p</dynam>'), "dynam", "enclose"),
    (mei_text('<note xml:id="note" pname="c" oct="4" dur="1" tab.course="0" />'), "note", "tab.course"),
])
def test_remaining_errors_preserve_file_exactly(text: str, element: str, error: str, tmp_path: Path) -> None:
    output = tmp_path / "score.mei"
    original = text.replace("\n", "\r\n").encode("utf-8")
    output.write_bytes(original)
    report = _rewrite_output_mei_version(output, "5.1")
    assert report["status"] == "incomplete"
    assert output.read_bytes() == original
    assert any(row["element"] == element and error in row["message"] for row in report["remaining_errors"])
    if element == "dynam":
        assert report["unrewritable"][0]["xml_id"] == "dynamic"
    assert not any("meiversion" in row["message"] for row in report["remaining_errors"])


@requires_xmllint
def test_refusal_and_other_invalid_content_validate_all_safe_edits(tmp_path: Path) -> None:
    text = mei_text(
        '<note xml:id="note" pname="c" oct="4" dur="1" tab.course="0" />\n'
        '               <mRest xml:id="hidden" visible="false" />',
        controls='<dynam xml:id="dynamic" staff="1" tstamp="1" enclose="paren">p</dynam>',
    )
    candidate = rewrite_mei_version(text)
    assert candidate.text is not None
    assert 'meiversion="5.1"' in candidate.text
    assert '<mSpace xml:id="hidden" />' in candidate.text
    assert 'enclose="paren"' in candidate.text
    output = tmp_path / "score.mei"
    original = text.encode("utf-8")
    output.write_bytes(original)
    report = _rewrite_output_mei_version(output, "5.1")
    assert report["status"] == "incomplete"
    assert output.read_bytes() == original
    assert any(row["element"] == "dynam" and "enclose" in row["message"] for row in report["remaining_errors"])
    assert any(row["element"] == "note" and "tab.course" in row["message"] for row in report["remaining_errors"])
    assert not any("meiversion" in row["message"] for row in report["remaining_errors"])


@pytest.mark.parametrize("references", ['target="#original"', 'plist="#other #original #last"'])
def test_referenced_wrapper_is_refused_in_any_attribute(references: str) -> None:
    text = mei_text(section=REPEAT_CHOICE, metadata=f'<extMeta><external xmlns="urn:metadata" {references} /></extMeta>')
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    assert result.status == "incomplete"
    assert any(row["xml_id"] == "original" and "references" in row["reason"] for row in result.unrewritable)


@pytest.mark.parametrize("choice", [
    REPEAT_CHOICE.replace('<orig xml:id="original">', '<orig xml:id="original" type="other">'),
    REPEAT_CHOICE.replace('<choice xml:id="choice">', '<choice xml:id="choice" type="norep">'),
])
def test_wrapper_attribute_information_cannot_be_lost(choice: str) -> None:
    text = mei_text(section=choice)
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    assert any("attribute information" in row["reason"] for row in result.unrewritable)


def test_wrapper_namespace_information_cannot_be_lost() -> None:
    choice = REPEAT_CHOICE.replace('<orig xml:id="original">', '<orig xml:id="original" xmlns:meta="urn:metadata">')
    result = rewrite_mei_version(mei_text(section=choice))
    assert result.text is not None
    assert '<orig xml:id="original" xmlns:meta="urn:metadata">' in result.text
    assert any("namespace information" in row["reason"] for row in result.unrewritable)


def test_shared_wrapper_attributes_already_on_expansions_are_safe() -> None:
    choice = REPEAT_CHOICE.replace('<choice xml:id="choice">', '<choice xml:id="choice" xml:lang="de">')
    choice = choice.replace('<expansion xml:id=', '<expansion xml:lang="de" xml:id=')
    result = rewrite_mei_version(mei_text(section=choice))
    assert result.text is not None
    assert not result.unrewritable


@pytest.mark.parametrize("extra", ["text", "<note />", "<?extra data?>"])
def test_repeat_choice_with_other_content_is_refused(extra: str) -> None:
    result = rewrite_mei_version(mei_text(section=REPEAT_CHOICE.replace('<orig xml:id="original">', f'<orig xml:id="original">{extra}')))
    assert result.text is not None
    assert REPEAT_CHOICE.replace('<orig xml:id="original">', f'<orig xml:id="original">{extra}') in result.text
    assert result.unrewritable


@pytest.mark.parametrize("duplicate", [
    '<!-- <mRest xml:id="hidden" visible="false" /> -->',
    '<![CDATA[<mRest xml:id="hidden" visible="false" />]]>',
    '<external xmlns="urn:metadata"><mRest xml:id="hidden" visible="false" /></external>',
])
def test_duplicate_anchor_in_comment_cdata_or_extmeta_is_refused(duplicate: str) -> None:
    text = mei_text('<mRest xml:id="hidden" visible="false" />', metadata=f'<extMeta><frames xmlns="http://www.humdrum.org/ns/humxml" />{duplicate}</extMeta>')
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    assert any(row["xml_id"] == "hidden" and "2 matches" in row["reason"] for row in result.unrewritable)


@pytest.mark.parametrize("text", [
    mei_text('<mRest visible="false" />'),
    mei_text(controls=EDITORIAL.replace(' xml:id="dynamic"', "")),
    mei_text(section=REPEAT_CHOICE.replace(' xml:id="original"', "")),
])
def test_targets_without_ids_are_refused(text: str) -> None:
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    assert any("no xml:id" in row["reason"] for row in result.unrewritable)


def test_anchor_with_zero_matches_is_refused() -> None:
    # XML normalizes literal attribute newlines; the raw-text anchor then differs.
    text = mei_text('<mRest xml:id="hidden\nrest" visible="false" />')
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    assert any("0 matches" in row["reason"] for row in result.unrewritable)


def test_embedded_default_namespace_and_crlf_are_preserved() -> None:
    metadata = '<extMeta><frames xmlns="http://www.humdrum.org/ns/humxml"><frame xml:id="frame">é</frame></frames><mads xmlns="http://www.loc.gov/mads/v2" /></extMeta>'
    text = mei_text('<mRest xml:id="hidden" visible="false" />', metadata=metadata).replace("\n", "\r\n")
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"').replace(
        '<mRest xml:id="hidden" visible="false" />', '<mSpace xml:id="hidden" />',
    )
    assert "ns0:" not in result.text


def test_foreign_elements_are_not_rewritten() -> None:
    metadata = '<extMeta><frames xmlns="http://www.humdrum.org/ns/humxml"><mRest xml:id="foreign" visible="false" /></frames></extMeta>'
    text = mei_text(metadata=metadata)
    result = rewrite_mei_version(text)
    assert result.text == text.replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    assert result.rewrites["mrest_to_mspace"] == 0


def test_prefixed_tags_keep_existing_prefixes() -> None:
    text = '''<m:mei xmlns:m="http://www.music-encoding.org/ns/mei" meiversion='6.0-dev'>
   <m:mRest xml:id='hidden' visible='false'></m:mRest>
</m:mei>'''
    result = rewrite_mei_version(text)
    assert result.text == text.replace("meiversion='6.0-dev'", "meiversion='5.1'").replace(
        "m:mRest", "m:mSpace",
    ).replace(" visible='false'", "")


def test_root_already_51_is_not_needed_even_with_invalid_artefacts() -> None:
    text = mei_text('<mRest visible="false" />').replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    result = rewrite_mei_version(text)
    assert result.status == "not_needed"
    assert result.text is None
    assert not any(result.rewrites.values())


def test_not_needed_preserves_bytes_and_does_not_validate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def unexpected(*_args, **_kwargs):
        pytest.fail("Already-5.1 output should be untouched.")

    monkeypatch.setattr("camat.mei_consistency_workflow.run_relaxng_validation", unexpected)
    text = mei_text().replace('meiversion="6.0-dev"', 'meiversion="5.1"')
    original = text.replace("\n", "\r\n").encode("utf-8")
    output = tmp_path / "score.mei"
    output.write_bytes(original)
    report = _rewrite_output_mei_version(output, "5.1")
    assert report["status"] == "not_needed"
    assert output.read_bytes() == original


@pytest.mark.parametrize("version", ["5.0", "6.0", "5.1+CMN", ""])
def test_other_source_versions_are_not_relabelled(version: str) -> None:
    result = rewrite_mei_version(mei_text().replace("6.0-dev", version))
    assert result.text is None
    assert result.status == "incomplete"
    assert result.remaining_errors


def test_invalid_target_and_malformed_xml() -> None:
    with pytest.raises(ValueError):
        rewrite_mei_version(mei_text(), "6.0")
    result = rewrite_mei_version("<mei>")
    assert result.text is None
    assert result.remaining_errors


def test_duplicate_root_tag_is_refused() -> None:
    text = mei_text()
    start_tag = text.splitlines()[1]
    text = text.replace("<meiHead>", f"<!-- {start_tag} -->\n   <meiHead>")
    result = rewrite_mei_version(text)
    assert result.text == text
    assert result.unrewritable[0]["element"] == "mei"


@pytest.mark.parametrize("text", ["<mei>", mei_text().replace("6.0-dev", "5.0")])
def test_no_candidate_reports_own_errors_without_validation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> None:
    def unexpected(*_args, **_kwargs):
        pytest.fail("No candidate can be built; the original must not be schema validated.")

    monkeypatch.setattr("camat.mei_consistency_workflow.run_relaxng_validation", unexpected)
    output = tmp_path / "score.mei"
    original = text.encode("utf-8")
    output.write_bytes(original)
    report = _rewrite_output_mei_version(output, "5.1")
    assert report["status"] == "incomplete"
    assert report["remaining_errors"]
    assert output.read_bytes() == original


def test_missing_xmllint_preserves_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def missing(*_args, **_kwargs):
        raise RuntimeError("xmllint is required for the pinned RELAX NG validation pass.")

    monkeypatch.setattr("camat.mei_consistency_workflow.run_relaxng_validation", missing)
    output = tmp_path / "score.mei"
    original = mei_text().encode("utf-8")
    output.write_bytes(original)
    report = _rewrite_output_mei_version(output, "5.1")
    assert report["status"] == "incomplete"
    assert "xmllint" in report["remaining_errors"][0]["message"]
    assert output.read_bytes() == original
    assert list(tmp_path.iterdir()) == [output]


def test_schema_errors_are_capped_with_total(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from camat.mei_consistency_workflow import SchemaValidationResult

    monkeypatch.setattr("camat.mei_consistency_workflow.run_relaxng_validation", lambda *_args, **_kwargs: SchemaValidationResult(
        schema=Path("schema.rng"), files_checked=1,
        rows=[{"element": "note", "message": f"error {n}"} for n in range(75)],
    ))
    output = tmp_path / "score.mei"
    output.write_text(mei_text(), encoding="utf-8")
    report = _rewrite_output_mei_version(output, "5.1")
    assert len(report["remaining_errors"]) == 50
    assert report["remaining_errors_total"] == 75
