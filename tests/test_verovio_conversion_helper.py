from pathlib import Path

from music21 import meter, note, stream

from camat.conversion import (
    _file_fingerprint,
    _load_music21_score,
    _output_mei_path,
    _prepare_midi_score_for_export,
)


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
