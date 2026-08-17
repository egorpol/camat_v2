from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET

from music21 import meter, note, stream, tempo
import pytest

from camat.conversion import (
    DownloadOptions,
    MidiImportOptions,
    _file_fingerprint,
    _fetch_source,
    _load_music21_score,
    _music21_to_musicxml_path,
    _midi_voices_to_separate_staves,
    _output_mei_path,
    _prepare_midi_score_for_export,
    convert_sources,
)
from camat.midi_timing import read_midi_timing


def test_output_names_distinguish_sources_with_the_same_basename(tmp_path: Path) -> None:
    prelude = (
        "https://example.org/Bach/Prelude/bwv_846/midi_score.mid"
    )
    fugue = (
        "https://example.org/Bach/Fugue/bwv_846/midi_score.mid"
    )

    prelude_output = _output_mei_path(
        prelude,
        output_dir=tmp_path,
        input_from="midi",
    )
    fugue_output = _output_mei_path(
        fugue,
        output_dir=tmp_path,
        input_from="midi",
    )

    assert prelude_output != fugue_output
    assert prelude_output.name.startswith("midi_score_")
    assert prelude_output.name.endswith("_midi_verovio.mei")


def test_file_fingerprint_reports_sha256_and_size(tmp_path: Path) -> None:
    score = tmp_path / "score.mid"
    score.write_bytes(b"MThd")

    fingerprint = _file_fingerprint(score)

    assert fingerprint["size_bytes"] == 4
    assert fingerprint["sha256"] == (
        "70fad3c7454a1f31935f5a14f71a959010e4ad087bfec6701d5cc66d382e5d05"
    )


def test_midi_export_reconstructs_delayed_note_as_voice_with_rest() -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    measure.insert(0, note.Note("C4", quarterLength=2.0))
    measure.insert(0.25, note.Note("E4", quarterLength=1.75))
    measure.insert(2.0, note.Note("C4", quarterLength=2.0))
    measure.insert(2.25, note.Note("E4", quarterLength=1.75))
    part = stream.Part([measure])
    score = stream.Score([part])

    diagnostics = _prepare_midi_score_for_export(score)

    assert diagnostics == {
        "staggered_overlap_measures": 1,
        "voice_measures_before": 0,
        "voice_measures_after": 1,
        "visible_rests_added": 2,
    }
    assert len(measure.voices) == 2
    assert any(
        any(
            element.isRest
            and float(element.offset) == 0.0
            and float(element.quarterLength) == 0.25
            for element in voice.notesAndRests
        )
        and any(
            getattr(element, "nameWithOctave", None) == "E4"
            and float(element.offset) == 0.25
            for element in voice.notesAndRests
        )
        for voice in measure.voices
    )


def test_midi_import_preserves_sequential_thirty_second_notes(tmp_path: Path) -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    measure.insert(0, note.Note("C4", quarterLength=0.75))
    measure.insert(0.75, note.Note("G4", quarterLength=0.125))
    measure.insert(0.875, note.Note("F4", quarterLength=0.125))
    measure.insert(1.0, note.Note("E4", quarterLength=3.0))
    source_score = stream.Score([stream.Part([measure])])
    midi_path = Path(source_score.write("midi", fp=str(tmp_path / "ornament.mid")))

    imported, diagnostics = _load_music21_score(midi_path)
    pitched = [
        element
        for element in imported.parts[0].flatten().notes
        if not element.isChord
    ]
    ornament = [
        (
            element.nameWithOctave,
            float(element.offset),
            float(element.quarterLength),
        )
        for element in pitched
        if element.nameWithOctave in {"G4", "F4"}
    ]

    assert diagnostics["quantization_quarter_length_divisors"] == [8, 6, 4, 3]
    assert ornament == [
        ("G4", 0.75, 0.125),
        ("F4", 0.875, 0.125),
    ]


def test_custom_midi_grid_preserves_sixty_fourth_notes(tmp_path: Path) -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    measure.insert(0, note.Note("C4", quarterLength=Fraction(1, 16)))
    measure.insert(Fraction(1, 16), note.Note("D4", quarterLength=Fraction(1, 16)))
    measure.insert(Fraction(1, 8), note.Note("E4", quarterLength=Fraction(31, 8)))
    midi_path = Path(
        stream.Score([stream.Part([measure])]).write(
            "midi",
            fp=str(tmp_path / "sixty_fourths.mid"),
        )
    )

    imported, diagnostics = _load_music21_score(
        midi_path,
        MidiImportOptions(quarter_length_divisors=(16, 8, 6, 4, 3)),
    )
    events = [
        (element.nameWithOctave, element.offset, element.quarterLength)
        for element in imported.parts[0].flatten().notes
        if not element.isChord
    ][:2]

    assert events == [
        ("C4", 0.0, Fraction(1, 16)),
        ("D4", Fraction(1, 16), Fraction(1, 16)),
    ]
    assert diagnostics["quantization_quarter_length_divisors"] == [16, 8, 6, 4, 3]


def test_eleven_grid_exports_eleven_to_eight_time_modification(tmp_path: Path) -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    for index in range(11):
        measure.insert(
            Fraction(index * 4, 11),
            note.Note("C4", quarterLength=Fraction(4, 11)),
        )
    midi_path = Path(
        stream.Score([stream.Part([measure])]).write(
            "midi",
            fp=str(tmp_path / "eleven.mid"),
        )
    )

    musicxml_path, diagnostics = _music21_to_musicxml_path(
        midi_path,
        tmp_path / "conversion",
        midi_options=MidiImportOptions(
            quarter_length_divisors=(11,),
            reconstruct_voices=False,
        ),
    )
    root = ET.parse(musicxml_path).getroot()
    actual = root.findall(".//time-modification/actual-notes")
    normal = root.findall(".//time-modification/normal-notes")

    assert len(actual) == 11
    assert {element.text for element in actual} == {"11"}
    assert {element.text for element in normal} == {"8"}
    assert diagnostics["quantization_quarter_length_divisors"] == [11]


def test_raw_midi_timing_preserves_ticks_without_chord_grouping(tmp_path: Path) -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    measure.insert(0, note.Note("G4", quarterLength=Fraction(1, 8)))
    measure.insert(Fraction(1, 8), note.Note("F4", quarterLength=Fraction(1, 8)))
    midi_path = Path(
        stream.Score([stream.Part([measure])]).write(
            "midi",
            fp=str(tmp_path / "raw.mid"),
        )
    )

    timing = read_midi_timing(midi_path)
    notes = timing.notes[timing.notes["pitch"].isin([65, 67])]

    assert timing.timing_basis == "ppq"
    assert len(notes) == 2
    assert notes["onset_tick"].nunique() == 2
    assert list(notes["onset_quarter_length"]) == [Fraction(0), Fraction(1, 8)]


def test_raw_midi_timing_integrates_tempo_changes(tmp_path: Path) -> None:
    part = stream.Part()
    part.insert(0, meter.TimeSignature("4/4"))
    part.insert(0, tempo.MetronomeMark(number=60))
    part.insert(0, note.Note("C4", quarterLength=1))
    part.insert(1, tempo.MetronomeMark(number=120))
    part.insert(1, note.Note("D4", quarterLength=1))
    midi_path = Path(
        stream.Score([part]).write(
            "midi",
            fp=str(tmp_path / "tempo_change.mid"),
        )
    )

    timing = read_midi_timing(midi_path)

    assert list(timing.tempo_map["quarter_bpm"]) == [60.0, 120.0]
    assert list(timing.notes["onset_seconds"]) == [0.0, 1.0]
    assert list(timing.notes["offset_seconds"]) == [1.0, 1.5]


def test_conversion_options_reject_invalid_values() -> None:
    with pytest.raises(ValueError):
        MidiImportOptions(quarter_length_divisors=(0, 8))
    with pytest.raises(TypeError):
        MidiImportOptions(quarter_length_divisors=(8, 3.5))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        DownloadOptions(max_bytes=0)
    with pytest.raises(ValueError):
        MidiImportOptions(voice_layout="one_staff_per_voice")


def test_midi_voices_can_be_expanded_to_separate_staves() -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    measure.insert(0, note.Note("C4", quarterLength=2))
    measure.insert(Fraction(1, 4), note.Note("E4", quarterLength=Fraction(7, 4)))
    measure.insert(2, note.Note("D4", quarterLength=2))
    measure.insert(Fraction(9, 4), note.Note("F4", quarterLength=Fraction(7, 4)))
    score = stream.Score([stream.Part([measure])])
    score.parts[0].partName = "Piano"

    _prepare_midi_score_for_export(score)
    separated, diagnostics = _midi_voices_to_separate_staves(score)

    assert len(separated.parts) == 2
    assert diagnostics["source_part_count"] == 1
    assert diagnostics["voice_slots_per_source_part"] == [2]
    assert diagnostics["output_staff_count"] == 2
    assert [part.partName for part in separated.parts] == [
        "Piano — voice slot 1",
        "Piano — voice slot 2",
    ]
    assert all(
        not measure.voices
        for part in separated.parts
        for measure in part.getElementsByClass(stream.Measure)
    )


def test_separate_staff_layout_reaches_musicxml_export(tmp_path: Path) -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    measure.insert(0, note.Note("C4", quarterLength=2))
    measure.insert(Fraction(1, 4), note.Note("E4", quarterLength=Fraction(7, 4)))
    measure.insert(2, note.Note("D4", quarterLength=2))
    measure.insert(Fraction(9, 4), note.Note("F4", quarterLength=Fraction(7, 4)))
    midi_path = Path(
        stream.Score([stream.Part([measure])]).write(
            "midi",
            fp=str(tmp_path / "voices.mid"),
        )
    )

    musicxml_path, diagnostics = _music21_to_musicxml_path(
        midi_path,
        tmp_path / "conversion",
        midi_options=MidiImportOptions(voice_layout="separate_staves"),
    )
    root = ET.parse(musicxml_path).getroot()

    assert diagnostics["voice_layout"] == "separate_staves"
    assert diagnostics["source_part_count"] == 1
    assert diagnostics["voice_slots_per_source_part"] == [2]
    assert diagnostics["output_staff_count"] == 2
    assert len(root.findall("./part-list/score-part")) == 2


def test_missing_local_source_has_layered_failure_record(tmp_path: Path) -> None:
    record = convert_sources(
        [str(tmp_path / "missing.mid")],
        output_dir=tmp_path / "out",
        show_progress=False,
        expand_txt_sources=False,
    )[0]

    assert record["status"] == "fail"
    assert record["failure_stage"] == "download"
    assert record["failure_code"] == "local_source_missing"
    assert record["validation_stages"]["downloaded"]["status"] == "failed"


def test_unquantized_mode_is_explicit_about_music21_chord_grouping(tmp_path: Path) -> None:
    measure = stream.Measure(number=1)
    measure.insert(0, meter.TimeSignature("4/4"))
    measure.insert(0, note.Note("C4", quarterLength=Fraction(1, 32)))
    measure.insert(Fraction(1, 32), note.Note("D4", quarterLength=Fraction(1, 32)))
    midi_path = Path(
        stream.Score([stream.Part([measure])]).write(
            "midi",
            fp=str(tmp_path / "unquantized.mid"),
        )
    )

    _, diagnostics = _load_music21_score(
        midi_path,
        MidiImportOptions(quantize=False),
    )

    assert diagnostics["quantize_post"] is False
    assert diagnostics["quantization_quarter_length_divisors"] is None
    assert diagnostics["chord_grouping_tolerance_quarter_length"] == Fraction(1, 16)
    assert "read_midi_timing" in diagnostics["microtiming_warning"]


def test_resume_requires_matching_signature_and_output_hash(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "basic.musicxml"
    first = convert_sources(
        [str(source)],
        output_dir=tmp_path,
        render_first_page=False,
        show_progress=False,
        expand_txt_sources=False,
    )[0]
    resumed = convert_sources(
        [str(source)],
        output_dir=tmp_path,
        render_first_page=False,
        show_progress=False,
        expand_txt_sources=False,
        resume_policy="if-unchanged",
    )[0]

    assert first["status"] == "ok"
    assert resumed["status"] == "ok"
    assert resumed["skipped"] is True
    assert resumed["conversion_signature"] == first["conversion_signature"]

    output = Path(resumed["output_mei"])
    output.write_text(output.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    after_tamper = convert_sources(
        [str(source)],
        output_dir=tmp_path,
        render_first_page=False,
        show_progress=False,
        expand_txt_sources=False,
        resume_policy="if-unchanged",
    )[0]
    assert after_tamper["status"] == "ok"
    assert after_tamper["skipped"] is False
    assert after_tamper["overwritten"] is True


def test_streaming_download_rejects_html(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html", "Content-Length": "12"}
        url = "https://example.org/blob/score.mid"
        history: list[object] = []
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield b"<html></html>"

    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: FakeResponse())

    with pytest.raises(Exception) as caught:
        _fetch_source(
            "https://example.org/score.mid",
            tmp_path,
            10,
            options=DownloadOptions(),
        )

    assert getattr(caught.value, "stage", None) == "download"
    assert getattr(caught.value, "code", None) == "html_instead_of_score"


def test_conversion_report_records_provenance_and_validation(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "basic.musicxml"
    record = convert_sources(
        [str(source)],
        output_dir=tmp_path,
        render_first_page=True,
        show_progress=False,
        expand_txt_sources=False,
    )[0]

    assert record["report_schema_version"] == 1
    assert record["source_sha256"]
    assert record["output_sha256"]
    assert record["options_fingerprint"]
    assert record["conversion_signature"]
    assert record["tool_versions"]["verovio"]
    assert record["conversion_duration_seconds"] >= 0
    assert record["stage_durations_seconds"]["verovio_conversion"] >= 0
    assert record["validation_stages"]["valid_mei"]["status"] == "passed"
    assert record["validation_stages"]["rendered"]["status"] == "passed"
    assert record["validation_stages"]["camat_parsed"]["status"] == "not_run"
