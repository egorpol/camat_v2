from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from camat.check_mei_consistency import check_mei_files
from camat.mei_consistency_workflow import MEI_CMN_51_SCHEMA, make_unique_xml_id_copies, run_relaxng_validation
from camat.mei_validation import run_mei_validation
from camat.mei_schematron import extract_schematron, run_schematron_validation
from camat.mei_resources import image_resource_rows

BASE = Path(__file__).parents[1] / 'test_corpus/validation_baseline/minimal-cmn-51.mei'
MEI = 'http://www.music-encoding.org/ns/mei'
ID = '{http://www.w3.org/XML/1998/namespace}id'


def modified(tmp_path, name='score.mei'):
    path = tmp_path / name
    tree = ET.parse(BASE)
    tree.write(path, encoding='utf-8', xml_declaration=True)
    return path, tree


def test_schematron_only_violation_and_svrl_context(tmp_path):
    pytest.importorskip('saxonche')
    path, tree = modified(tmp_path)
    measure = tree.getroot().find(f'.//{{{MEI}}}measure')
    ET.SubElement(measure, f'{{{MEI}}}harm', {ID: 'unanchored-harm'}).text = 'I'
    tree.write(path, encoding='utf-8')
    before = path.read_bytes()
    assert not run_relaxng_validation([path], root=tmp_path).rows
    result = run_schematron_validation([path], schema=MEI_CMN_51_SCHEMA, output_dir=tmp_path / 'sch')
    assert result['failed_assertions'] > 0
    assert any(row['element'] == 'harm' and row['xml_id'] == 'unanchored-harm' and row['line'] for row in result['rows'])
    assert Path(result['svrl'][0]).is_file()
    assert path.read_bytes() == before


def test_embedded_namespace_and_xpath2_rules_execute(tmp_path):
    pytest.importorskip('saxonche')
    schema = tmp_path / 'custom.rng'
    schema.write_text('''<grammar xmlns="http://relaxng.org/ns/structure/1.0" xmlns:s="http://purl.oclc.org/dsdl/schematron">
      <s:pattern xmlns:music="http://www.music-encoding.org/ns/mei" id="custom"><s:rule context="music:mei">
        <s:assert test="every $x in tokenize('1 2', ' ') satisfies xs:integer($x) gt 0" xmlns:xs="http://www.w3.org/2001/XMLSchema">XPath2</s:assert>
        <s:assert test="count(.//music:note) = 5">Five notes</s:assert>
      </s:rule></s:pattern></grammar>''')
    result = run_schematron_validation([BASE], schema=schema, output_dir=tmp_path / 'out')
    assert result['rule_count'] == 2
    assert not result['rows']


def test_zero_rules_and_missing_validator_cannot_pass(tmp_path, monkeypatch):
    schema = tmp_path / 'empty.rng'
    schema.write_text('<grammar xmlns="http://relaxng.org/ns/structure/1.0"/>')
    with pytest.raises(ValueError, match='zero'):
        extract_schematron(schema)
    monkeypatch.setitem(sys.modules, 'saxonche', None)
    result = run_mei_validation([BASE], root=tmp_path, output_dir=tmp_path / 'out', check_relaxng=False)
    assert not result.passed
    assert result.record['executions']['schematron']['status'] == 'execution-error'
    assert result.record['executions']['relaxng']['status'] == 'skipped'
    assert result.record['inputs'][0]['unchanged']
    assert json.loads((tmp_path / 'out/run.json').read_text())['conformance'] == 'incomplete'


def test_missing_xmllint_is_an_execution_error(tmp_path, monkeypatch):
    import camat.mei_consistency_workflow as workflow
    real = workflow.subprocess.run
    def unavailable(command, *args, **kwargs):
        if command[0] == 'xmllint':
            raise FileNotFoundError('missing')
        return real(command, *args, **kwargs)
    monkeypatch.setattr(workflow.subprocess, 'run', unavailable)
    result = run_mei_validation([BASE], root=tmp_path, output_dir=tmp_path / 'out', check_schematron=False)
    assert not result.passed
    assert result.record['executions']['relaxng']['status'] == 'execution-error'


def test_empty_input_and_skipped_required_checks_block_pass(tmp_path):
    result = run_mei_validation([], root=tmp_path, output_dir=tmp_path / 'empty', check_relaxng=False, check_schematron=False)
    assert not result.passed
    result = run_mei_validation([BASE], root=tmp_path, output_dir=tmp_path / 'skipped', check_relaxng=False, check_schematron=False)
    assert not result.passed
    assert result.record['inputs'][0]['sha256_before'] == hashlib.sha256(BASE.read_bytes()).hexdigest()
    assert result.record['camat']['source_tree_sha256']


def test_document_lists_xmlbase_and_id_rewrite(tmp_path):
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    first, tree = modified(bundle, 'first.mei')
    second, _ = modified(bundle, 'second score.mei')
    tree.getroot().set('{http://www.w3.org/XML/1998/namespace}base', 'first.mei')
    note = tree.getroot().find(f'.//{{{MEI}}}note')
    note.set('corresp', '#note-d4 second%20score.mei#note-c4')
    tree.write(first, encoding='utf-8')
    assert not [f for f in check_mei_files([first], root_dir=bundle) if f.category == 'references']
    prepared = make_unique_xml_id_copies([first, second], tmp_path / 'prepared')
    assert not [f for f in check_mei_files(prepared.files, root_dir=tmp_path) if f.category == 'references']
    note.set('source', 'second%20score.mei#missing')
    tree.write(first, encoding='utf-8')
    assert any(f.check == 'broken_document_reference' for f in check_mei_files([first], root_dir=bundle))


def test_inherited_base_changes_fragment_document(tmp_path):
    first, tree = modified(tmp_path, 'first.mei')
    second, other = modified(tmp_path, 'second.mei')
    other.getroot().find(f'.//{{{MEI}}}note').set(ID, 'foreign')
    other.write(second, encoding='utf-8')
    note = tree.getroot().find(f'.//{{{MEI}}}note')
    note.set('{http://www.w3.org/XML/1998/namespace}base', 'second.mei')
    note.set('corresp', '#foreign')
    tree.write(first, encoding='utf-8')
    assert not [f for f in check_mei_files([first], root_dir=tmp_path) if f.category == 'references']


def test_image_resources_local_direct_http_and_multiple_resolutions(tmp_path):
    from PIL import Image
    path, tree = modified(tmp_path)
    music = tree.getroot().find(f'{{{MEI}}}music')
    surface = ET.SubElement(ET.SubElement(music, f'{{{MEI}}}facsimile'), f'{{{MEI}}}surface',
                            {ID:'surface', 'n':'iii', 'ulx':'100', 'uly':'100', 'lrx':'1100', 'lry':'2100'})
    ET.SubElement(surface, f'{{{MEI}}}zone', {'ulx':'200','uly':'300','lrx':'900','lry':'1500'})
    for name, size in [('large.png', (1000,2000)), ('small.png', (100,200))]:
        Image.new('RGB', size).save(tmp_path / name)
        ET.SubElement(surface, f'{{{MEI}}}graphic', {'target':name, 'width':str(size[0]), 'height':str(size[1])})
    ET.SubElement(surface, f'{{{MEI}}}graphic', {'target':'https://example.org/page.jpg'})
    tree.write(path, encoding='utf-8')
    result = image_resource_rows([path])
    assert not result['rows']
    assert [r['status'] for r in result['resources']] == ['passed','passed','skipped']
    (tmp_path / 'small.png').write_text('not an image')
    assert any(r['check'] == 'local_graphic' for r in image_resource_rows([path])['rows'])
    surface.find(f'{{{MEI}}}zone').set('lrx','1200')
    tree.write(path, encoding='utf-8')
    assert any(r['check'] == 'zone_surface_bounds' for r in image_resource_rows([path])['rows'])


def test_requested_network_without_images_is_not_applicable(tmp_path, monkeypatch):
    pytest.importorskip('saxonche')
    import camat.mei_resources as resources
    def unexpected_request(*args, **kwargs):
        pytest.fail('A facsimile-free score must not make image requests')
    monkeypatch.setattr(resources, 'urlopen', unexpected_request)
    result = run_mei_validation([BASE], root=tmp_path, output_dir=tmp_path / 'out', check_network=True)
    entry = result.record['executions']['image_network']
    assert entry['status'] == 'not-applicable'
    assert entry['requested'] and not entry['required']
    assert entry['images_linked'] == entry['requests_attempted'] == 0
    assert 'No images are linked' in entry['reason']
    assert result.passed

    # A caller explicitly requiring connectivity must not get a false pass.
    from camat.mei_validation import DEFAULT_REQUIRED
    required = run_mei_validation(
        [BASE], root=tmp_path, output_dir=tmp_path / 'required', check_network=True,
        required_checks=(*DEFAULT_REQUIRED, 'image_network'),
    )
    assert required.record['conformance'] == 'passed'
    assert required.record['required_checks_status'] == 'incomplete'
    assert not required.passed


def test_network_local_only_does_not_repeat_offline_failures(tmp_path, monkeypatch):
    import camat.mei_resources as resources
    def unexpected_request(*args, **kwargs):
        pytest.fail('Local image files must not make HTTP requests')
    monkeypatch.setattr(resources, 'urlopen', unexpected_request)
    path, tree = modified(tmp_path)
    music = tree.getroot().find(f'{{{MEI}}}music')
    surface = ET.SubElement(ET.SubElement(music, f'{{{MEI}}}facsimile'), f'{{{MEI}}}surface')
    ET.SubElement(surface, f'{{{MEI}}}graphic', {'target': 'missing.png'})
    tree.write(path, encoding='utf-8')
    network = image_resource_rows([path], check_network=True, network_only=True)
    assert not network['applicable']
    assert network['images_linked'] == 1
    assert network['requests_attempted'] == 0
    assert 'Only local images' in network['reason']
    assert not network['rows']
    assert any(r['check'] == 'local_graphic' for r in image_resource_rows([path])['rows'])


def test_network_reports_actual_http_attempts_and_failure(tmp_path, monkeypatch):
    import camat.mei_resources as resources
    path, tree = modified(tmp_path)
    music = tree.getroot().find(f'{{{MEI}}}music')
    facsimile = ET.Element(f'{{{MEI}}}facsimile')
    music.insert(0, facsimile)
    surface = ET.SubElement(facsimile, f'{{{MEI}}}surface', {ID: 'surface'})
    ET.SubElement(surface, f'{{{MEI}}}graphic', {'target': 'https://example.org/image.jpg'})
    tree.write(path, encoding='utf-8')
    calls = []
    class Response:
        headers = {'Content-Type': 'image/jpeg'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def reachable(request, **kwargs):
        assert request.get_method() == 'HEAD'
        calls.append(request.full_url)
        return Response()
    monkeypatch.setattr(resources, 'urlopen', reachable)
    result = run_mei_validation([path], root=tmp_path, output_dir=tmp_path / 'reachable',
                                check_relaxng=False, check_schematron=False, check_network=True)
    entry = result.record['executions']['image_network']
    assert entry['status'] == 'passed'
    assert entry['http_targets'] == entry['requests_attempted'] == len(calls) == 1
    def unavailable(*args, **kwargs):
        raise OSError('simulated offline connection')
    monkeypatch.setattr(resources, 'urlopen', unavailable)
    failed = run_mei_validation([path], root=tmp_path, output_dir=tmp_path / 'unreachable',
                                check_relaxng=False, check_schematron=False, check_network=True)
    assert failed.record['executions']['image_network']['status'] == 'failed'
    assert failed.record['executions']['image_network']['requests_attempted'] == 1
    assert any(r['check'] == 'graphic_connectivity' for r in failed.findings)


def test_complete_run_is_read_only_and_consumers_are_separate(tmp_path):
    pytest.importorskip('saxonche')
    before = BASE.read_bytes()
    result = run_mei_validation([BASE], root=tmp_path, output_dir=tmp_path / 'out')
    assert result.passed
    assert result.record['consumer_diagnostics'] == 'incomplete'
    assert result.record['executions']['verovio']['status'] == 'skipped'
    assert before == BASE.read_bytes()


def test_consumer_validation_never_opens_a_plot(tmp_path, monkeypatch):
    pytest.importorskip('verovio')
    import camat.verovio_backend as backend
    def unexpected_plot(*args, **kwargs):
        pytest.fail('A validation pass must not open a plotting window')
    monkeypatch.setattr(backend, 'draw_piano_roll', unexpected_plot)
    result = run_mei_validation(
        [BASE], root=tmp_path, output_dir=tmp_path / 'out',
        check_relaxng=False, check_schematron=False, check_camat_parse=True,
    )
    assert result.record['executions']['camat_parse']['status'] == 'passed'
    assert result.record['executions']['camat_parse']['counts'][0]['event_rows'] > 0


def test_schema_warning_is_preserved_without_becoming_conformance_error(tmp_path):
    pytest.importorskip('saxonche')
    schema = tmp_path / 'warning.sch'
    schema.write_text('''<schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">
      <ns prefix="mei" uri="http://www.music-encoding.org/ns/mei"/>
      <pattern><rule context="mei:mei"><assert role="warning" test="false()">Advisory</assert></rule></pattern>
    </schema>''')
    result = run_schematron_validation([BASE], schema=schema, output_dir=tmp_path / 'out')
    assert result['failed_assertions'] == 1
    assert result['error_assertions'] == 0
    assert result['rows'][0]['severity'] == 'warning'
    assert result['rows'][0]['check'].startswith('mei.sch.')


def test_explicit_page_references_survive_combining_and_copy_removal(tmp_path):
    import shutil
    from camat.mei_consistency_workflow import combine_meis
    first, tree = modified(tmp_path, 'first.mei')
    second, _ = modified(tmp_path, 'second.mei')
    tree.getroot().find(f'.//{{{MEI}}}note').set('corresp','second.mei#note-c4')
    tree.write(first, encoding='utf-8')
    prepared = make_unique_xml_id_copies([first,second], tmp_path / 'prepared')
    combined = combine_meis(prepared.files, tmp_path / 'combined.mei')
    shutil.rmtree(tmp_path / 'prepared')
    assert not [f for f in check_mei_files([combined.path], root_dir=tmp_path) if f.category == 'references']


def test_interruption_cannot_leave_previous_success_visible(tmp_path, monkeypatch):
    pytest.importorskip('saxonche')
    import camat.mei_validation as engine
    output = tmp_path / 'reused'
    assert engine.run_mei_validation([BASE], root=tmp_path, output_dir=output).passed
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt('simulated interruption')
    monkeypatch.setattr(engine, 'image_resource_rows', interrupted)
    with pytest.raises(KeyboardInterrupt):
        engine.run_mei_validation([BASE], root=tmp_path, output_dir=output)
    record = json.loads((output / 'run.json').read_text())
    assert record['completion_status'] == 'running'
    assert record['conformance'] == 'incomplete'
    assert record['active_check'] == 'resources'
    assert record['executions']['resources']['status'] == 'execution-error'
    assert record['executions']['resources']['running']
