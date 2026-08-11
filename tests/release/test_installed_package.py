from __future__ import annotations

from importlib.metadata import version as distribution_version
from importlib.resources import files
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

import camat
from camat.parser_registry import normalize_backend_name, parse_files


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MEI_FIXTURE = FIXTURES / "basic.mei"
MUSICXML_FIXTURE = FIXTURES / "basic.musicxml"
DURATION_FIXTURE = FIXTURES / "duration_semantics.mei"

SAMPLE_TIMELINE = """!!!OTL: Release smoke test
**recip\t**lyrics\t**ipa\t**stress
*M4/4\t*\t*\t*
*>Verse1
=1
4\tHel-\thEl\t1
4\t-lo\tloU\t0
2\t.\tR\t.
=2
1\tCAMAT\tkamat\t1
*-\t*-\t*-\t*-
"""


def _parse_kwargs() -> dict[str, object]:
    return {
        "backend": "none",
        "display_preview_df_pitch": False,
        "display_preview_df_events": False,
        "show_progress": False,
        "quiet_native_warnings": True,
    }


def test_wheel_is_installed_and_public_api_is_complete() -> None:
    repo_root = Path(os.environ["CAMAT_REPO_ROOT"]).resolve()
    imported_from = Path(camat.__file__).resolve()
    assert not imported_from.is_relative_to(repo_root / "camat"), (
        f"Imported source checkout instead of installed wheel: {imported_from}"
    )
    assert distribution_version("camat") == camat.__version__
    assert all(hasattr(camat, name) for name in camat.__all__)
    assert camat.parse_files is parse_files
    packaged_example = files("camat").joinpath("examples", "duration_semantics.mei")
    assert packaged_example.is_file()
    assert packaged_example.read_bytes() == DURATION_FIXTURE.read_bytes()


def test_parser_registry_and_default_verovio_mei_parser() -> None:
    assert normalize_backend_name(None) == "verovio"
    assert normalize_backend_name("vrv") == "verovio"
    assert set(camat.list_parsers()) == {"mensural", "music21", "partitura", "timeline", "verovio"}

    results, frames, last_df = parse_files([str(MEI_FIXTURE)], **_parse_kwargs())
    result = results[0]
    assert result["parser_backend"] == "verovio"
    assert len(result["df_pitch"]) == 5
    assert set(result["df_pitch"]["xml_id"].dropna()) == {
        "note-c4", "note-d4", "note-e4", "note-f4", "note-g4"
    }
    assert "rest" in set(result["df_events"]["type"].dropna())
    assert result["measure_offsets"] == [0.0, 4.0]
    assert result["df_name_pitch"] in frames
    assert last_df is not None and len(last_df) == 5


def test_compatibility_parsers() -> None:
    partitura_results, _, _ = parse_files(
        [str(MEI_FIXTURE)],
        parsing_backend="partitura",
        allow_music21_fallback=False,
        normalize_mensural_durations=False,
        inject_missing_meter_signature=False,
        **_parse_kwargs(),
    )
    assert len(partitura_results[0]["df_pitch"]) == 5

    music21_results, _, _ = parse_files(
        [str(MUSICXML_FIXTURE)],
        parsing_backend="music21",
        **_parse_kwargs(),
    )
    assert len(music21_results[0]["df_pitch"]) == 5


def test_verovio_conversion_and_rendering() -> None:
    mei = camat.vrv_convert_to_mei(str(MUSICXML_FIXTURE))
    root = ET.fromstring(mei)
    assert root.tag.rsplit("}", 1)[-1] == "mei"
    assert len([element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "note"]) == 5

    assert camat.vrv_load_from_file(str(MEI_FIXTURE)) >= 1
    svg = camat.vrv_render_page(1)
    assert "<svg" in svg


def test_analysis_and_pattern_search() -> None:
    notes = pd.DataFrame(
        {
            "Global Onset": [0.0, 1.0, 2.0, 3.0],
            "Duration": [1.0, 1.0, 1.0, 1.0],
            "Pitch": ["C4", "D4", "E4", "G4"],
            "Pitch Enharmonic": ["C4", "D4", "E4", "G4"],
            "MIDI": [60, 62, 64, 67],
            "Voice": ["Voice 1"] * 4,
        }
    )
    pitch_counts, pitch_col = camat.build_pitch_counts(notes, "midi")
    duration_counts, duration_col = camat.build_duration_counts(notes)
    pc_real, pc_enharmonic, _, _ = camat.build_pitch_class_distributions(notes)
    interval_counts, intervals = camat.melodic_interval_distribution(notes)
    assert pitch_col == "MIDI" and int(pitch_counts["count"].sum()) == 4
    assert duration_col == "Duration" and int(duration_counts["count"].sum()) == 4
    assert pc_real is not None and pc_enharmonic is not None
    assert intervals.tolist() == [2.0, 2.0, 3.0]
    assert int(interval_counts["count"].sum()) == 3

    matrix = np.array([[1, 0, 1, 0], [0, 1, 0, 1]], dtype=float)
    kernel = np.array([[1, 0], [0, 1]], dtype=float)
    results, scaled, variant, raw = camat.run_pattern_search(
        matrix,
        kernel,
        metrics_to_run=["normalized_overlap", "normalized_cross_correlation"],
        backend="none",
        top_n_matches=1,
    )
    assert variant is not None and "axis=x" in variant and "factor=1" in variant
    assert variant in results and variant in scaled
    assert raw is not None and raw.shape == (1, 3)


def test_timeline_roundtrip_and_rhythm_analysis() -> None:
    timeline, metadata = camat.humdrum_rap_to_timeline(SAMPLE_TIMELINE)
    enriched = camat.add_timeline_rhythm_analysis(timeline)
    duration_counts = camat.build_timeline_duration_counts(enriched, normalize=True)
    onset_counts, onset_summary = camat.build_timeline_onset_position_counts(enriched)
    mei = camat.timeline_to_mei(enriched, metadata=metadata)
    assert len(timeline) == 4
    assert abs(float(duration_counts["share"].sum()) - 1.0) < 1e-9
    assert not onset_counts.empty and onset_summary["regular_span_quarters"] == 4.0
    assert camat.find_duplicate_mei_xml_ids(mei).empty
    assert camat.load_timeline_mei_with_verovio(mei) >= 1


def test_mensural_text_normalization_helpers() -> None:
    source = '<mei><music><scoreDef/><note dur="semibrevis"/></music></mei>'
    normalized, count, replacements = camat.normalize_mensural_durations_in_mei_text(source)
    with_meter, meter_count = camat.inject_default_meter_signature_in_mei_text(normalized)
    assert 'dur="1"' in normalized
    assert count == 1 and replacements == {"semibrevis": 1}
    assert meter_count == 1
    assert 'meter.count="4"' in with_meter and 'meter.unit="4"' in with_meter
