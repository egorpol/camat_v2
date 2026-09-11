from xml.etree import ElementTree as ET

import pytest

from camat.verovio_backend import _extract_mei_note_effective_alters, _verovio_common_mei_dataframes


def document(definition, measures):
    return f'''<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">
<meiHead><fileDesc><titleStmt><title>Pitch semantics</title></titleStmt><pubStmt/></fileDesc></meiHead>
<music><body><mdiv><score>{definition}<section>{measures}</section></score></mdiv></body></music></mei>'''


def staff(n, body, layer=1):
    return f'<staff n="{n}"><layer n="{layer}">{body}</layer></staff>'


@pytest.mark.parametrize("key_declaration", ['keysig="2s"', 'key.sig="2s"', ''])
def test_keys_measure_carry_octave_and_staff_scope(tmp_path, key_declaration):
    child_key = '<keySig sig="2s"/>' if not key_declaration else ''
    definition = f'''<scoreDef meter.count="4" meter.unit="4" {key_declaration}>{child_key}<staffGrp>
<staffDef n="1" lines="5" clef.shape="G" clef.line="2"/>
<staffDef n="2" lines="5" clef.shape="G" clef.line="2" keysig="1f"/>
</staffGrp></scoreDef>'''
    layer_one = '''<note xml:id="f-key" pname="f" oct="4" dur="4"/>
<note xml:id="f-natural" pname="f" oct="4" dur="4" accid="n"/>
<note xml:id="f-carry" pname="f" oct="4" dur="4"/>
<note xml:id="f-other-octave" pname="f" oct="5" dur="4"/>'''
    layer_two = '<rest dur="2"/><note xml:id="f-other-layer" pname="f" oct="4" dur="4"/><rest dur="4"/>'
    measures = '<measure n="1"><staff n="1"><layer n="1">'+layer_one+'</layer><layer n="2">'+layer_two+'</layer></staff>'
    measures += staff(2, '<note xml:id="staff-flat" pname="b" oct="4" dur="1"/>')+'</measure>'
    measures += '<measure n="2">'+staff(1, '''<note xml:id="bar-reset" pname="f" oct="4" dur="4"/>
<note xml:id="c-key" pname="c" oct="4" dur="4"/>
<note xml:id="c-ges" pname="c" oct="4" dur="4" accid.ges="n"/>
<note xml:id="c-after-ges" pname="c" oct="4" dur="4"/>''')+staff(2,'<mRest/>')+'</measure>'
    measures += '<scoreDef keysig="0"/><measure n="3">'+staff(1,'<note xml:id="new-key" pname="f" oct="4" dur="1"/>')+staff(2,'<note xml:id="new-staff-key" pname="b" oct="4" dur="1"/>')+'</measure>'
    xml = document(definition, measures)
    path = tmp_path/'pitches.mei'
    path.write_text(xml)
    frame, *_ = _verovio_common_mei_dataframes(str(path), parse_enharmonic=True, quiet_native_warnings=True)
    frame = frame.set_index('xml_id')
    expected = {'f-key':66, 'f-natural':65, 'f-carry':65, 'f-other-octave':78,
                'f-other-layer':65, 'staff-flat':70, 'bar-reset':66, 'c-key':61,
                'c-ges':60, 'c-after-ges':61, 'new-key':65, 'new-staff-key':71}
    assert frame['MIDI'].to_dict() == expected
    assert frame.at['f-key','Pitch Enharmonic'] == 'F#4'
    assert frame.at['f-carry','Pitch Enharmonic'] == 'F4'


def test_inline_keys_ties_and_notes_without_ids():
    definition = '<scoreDef meter.count="4" meter.unit="4" keysig="0"><staffGrp><staffDef n="1" lines="5"/></staffGrp></scoreDef>'
    measures = '<measure n="1">'+staff(1, '<note xml:id="tie-start" pname="f" oct="4" dur="1" accid="s"/>')+'<tie startid="#tie-start" endid="#tie-end"/></measure>'
    measures += '<measure n="2">'+staff(1, '''<note xml:id="tie-end" pname="f" oct="4" dur="4"/>
<note xml:id="after-tie" pname="f" oct="4" dur="4"/>
<keySig sig="1f"/><note xml:id="inline-key" pname="b" oct="4" dur="4"/>
<note pname="b" oct="4" dur="4"/>''')+'</measure>'
    measures += '<measure n="3">'+staff(1,'<note xml:id="key-persists" pname="b" oct="4" dur="1"/>')+'</measure>'
    root = ET.fromstring(document(definition, measures))
    effective = _extract_mei_note_effective_alters(root)
    notes = root.findall('.//{http://www.music-encoding.org/ns/mei}note')
    assert [effective[id(note)] for note in notes] == [1, 1, 0, -1, -1, -1]
