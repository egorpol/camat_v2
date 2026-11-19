from __future__ import annotations

import pandas as pd
import pytest

from camat import partitura_backend, verovio_backend
from camat.parser_registry import parse_files
from camat.parser_utils import _grid_measure_labels, reanchor_to_measure_offsets


def _write_score(path, measures, *, two_staves=False):
    staff_defs = '<staffDef n="1" lines="5" clef.shape="G" clef.line="2"/>'
    if two_staves:
        staff_defs += '<staffDef n="2" lines="5" clef.shape="F" clef.line="4"/>'
    path.write_text(
        '<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">'
        '<meiHead><fileDesc><titleStmt><title>Bar labels</title></titleStmt>'
        '<pubStmt/></fileDesc></meiHead>'
        '<music><body><mdiv><score><scoreDef meter.count="2" meter.unit="4">'
        '<meterSig count="2" unit="4"/>'
        f'<staffGrp>{staff_defs}</staffGrp></scoreDef>'
        f'<section>{measures}</section></score></mdiv></body></music></mei>',
        encoding="utf-8",
    )
    return path


def _staff(content, number=1):
    return f'<staff n="{number}"><layer n="1">{content}</layer></staff>'


def _webern_score(path):
    return _write_score(
        path,
        '<measure xml:id="m1" n="0" metcon="false">'
        + _staff('<note xml:id="n1" pname="c" oct="4" dur="4"/>')
        + _staff('<note xml:id="bass1" pname="c" oct="3" dur="4"/>', 2)
        + '</measure><measure xml:id="m2" n="1" left="rptstart">'
        + _staff('<rest xml:id="r2" dur="4"/><note xml:id="n2" pname="d" oct="4" dur="4"/>')
        + _staff('<note xml:id="bass2" pname="d" oct="3" dur="2"/>', 2)
        + '<barLine xml:id="b2" form="single"/>'
        + '</measure><measure xml:id="m3" n="2" right="rptend">'
        + _staff('<note xml:id="n3" pname="e" oct="4" dur="2"/>')
        + _staff('<note xml:id="bass3" pname="e" oct="3" dur="2"/>', 2)
        + '</measure>',
        two_staves=True,
    )


def _numbered_score(path, numbers, *, empty=()):
    measures = []
    for index, number in enumerate(numbers, start=1):
        label = f' n="{number}"' if number is not None else ""
        content = (
            f'<rest xml:id="r{index}" dur="4"/>'
            f'<note xml:id="n{index}" pname="c" oct="4" dur="4"/>'
            if index not in empty else ""
        )
        measures.append(
            f'<measure xml:id="m{index}"{label}>{_staff(content)}'
            f'<dynam xml:id="d{index}" staff="1" tstamp="1">p</dynam>'
            '</measure>'
        )
    return _write_score(path, "".join(measures))


def _parse(path, parser, **kwargs):
    results, _, _ = parse_files(
        [str(path)],
        parsing_backend=parser,
        backend="none",
        display_preview_df_pitch=False,
        display_preview_df_events=False,
        quiet_native_warnings=True,
        **kwargs,
    )
    assert len(results) == 1
    return results[0]


def _event_measures(result, event_type):
    events = result["df_events"]
    return events.loc[events["type"] == event_type].set_index("xml_id")["Measure"].to_dict()


def _numbered_ids(prefix, values):
    return {f"{prefix}{index}": value for index, value in enumerate(values, start=1)}


def test_webern_pickup_labels_match_notes_and_events(tmp_path):
    path = _webern_score(tmp_path / "webern.mei")
    verovio = _parse(path, "verovio")
    partitura = _parse(path, "partitura")
    pitch = verovio["df_pitch"].set_index("xml_id")
    partitura_pitch = partitura["df_pitch"].set_index("xml_id")
    expected = {"n1": 0, "bass1": 0, "n2": 1, "bass2": 1, "n3": 2, "bass3": 2}
    assert pitch["Measure"].to_dict() == partitura_pitch["Measure"].to_dict() == expected
    assert pitch["Measure"].dtype == partitura_pitch["Measure"].dtype == pd.Int64Dtype()
    for result in (verovio, partitura):
        assert _event_measures(result, "measure") == {"m1": 0, "m2": 1, "m3": 2}
        assert _event_measures(result, "barline") == {"b2": 1}
        assert result["measure_offsets"] == [-1.0, 0.0, 2.0]
        first = result["df_pitch"].set_index("xml_id").loc["n1"]
        assert first[["Global Onset", "Local Onset", "Duration"]].tolist() == [-1.0, 1.0, 1.0]
    assert _event_measures(verovio, "rest") == {"r2": 1}
    assert verovio["df_events"].set_index("xml_id").at["r2", "measure_n"] == "1"
    assert _event_measures(partitura, "rest") == {"r2": 1}
    assert pd.isna(partitura["df_events"].set_index("xml_id").at["r2", "measure_n"])


@pytest.mark.parametrize(
    ("numbers", "expected", "parser"),
    [
        (("1", "2", "2", "3"), (1, 2, 3, 4), "verovio"),
        (("1", "2", "1", "2"), (1, 2, 3, 4), "verovio"),
        (("1", None, "3"), (1, 2, 3), "verovio"),
        (("1", "2a", "3"), (1, 2, 3), "verovio"),
        (("1", "+2", "5"), (1, 2, 3), "verovio"),
        ((" -2 ", "000", "5"), (-2, 0, 5), "verovio"),
        (("1", "2", "2", "3"), (1, 2, 3, 4), "partitura"),
        *[
            (numbers, tuple(map(int, numbers)), parser)
            for numbers in (("1", "2", "3"), ("1", "2", "5"), ("2", "3", "4"))
            for parser in ("verovio", "partitura")
        ],
    ],
)
def test_numbering_is_decided_for_the_whole_file(tmp_path, numbers, expected, parser):
    result = _parse(_numbered_score(tmp_path / "numbered.mei", numbers), parser)
    pitch = result["df_pitch"].set_index("xml_id")
    assert pitch["Measure"].to_dict() == _numbered_ids("n", expected)
    assert result["measure_offsets"] == [2.0 * index for index in range(len(numbers))]
    assert pitch["Global Onset"].tolist() == [offset + 1.0 for offset in result["measure_offsets"]]
    assert pitch["Local Onset"].tolist() == pitch["Duration"].tolist() == [1.0] * len(numbers)
    assert _event_measures(result, "measure") == _numbered_ids("m", expected)
    assert _event_measures(result, "dynamic") == _numbered_ids("d", expected)
    if parser == "verovio":
        assert _event_measures(result, "rest") == _numbered_ids("r", expected)
        rests = result["df_events"].query("type == 'rest'")
        assert rests["measure_n"].fillna("").tolist() == [number or "" for number in numbers]


@pytest.mark.parametrize(
    ("numbers", "empty", "notes", "events"),
    [
        (("1", "2", "3"), (2,), {"n1": 1, "n3": 3}, (1, 2, 3)),
        (("1", "1", "2", "3"), (2,), {"n1": 1, "n3": 2, "n4": 3}, (1, 2, 2, 3)),
        (("1", "1", "2"), (3,), {"n1": 1, "n2": 2}, (1, 2, 2)),
    ],
)
def test_untimed_bars_in_event_numbering(tmp_path, numbers, empty, notes, events):
    path = _numbered_score(tmp_path / "untimed.mei", numbers, empty=empty)
    result = _parse(path, "verovio")
    assert result["df_pitch"].set_index("xml_id")["Measure"].to_dict() == notes
    assert _event_measures(result, "measure") == _numbered_ids("m", events)
    assert _event_measures(result, "dynamic") == _numbered_ids("d", events)


def test_verovio_shared_rounded_start_uses_later_label(tmp_path, monkeypatch):
    path = _write_score(
        tmp_path / "shared-start.mei",
        '<measure n="4">' + _staff('<note xml:id="grace" grace="unacc" pname="c" oct="4" dur="8"/>')
        + '</measure><measure n="9">'
        + _staff('<note xml:id="note" pname="d" oct="4" dur="2"/>') + '</measure>',
    )
    monkeypatch.setattr(
        verovio_backend,
        "_mei_measure_meter_spans",
        lambda root, measures, **kwargs: {id(measures[0]): 2e-10, id(measures[1]): 2.0},
    )
    *_, offsets, _, _, labels = verovio_backend._verovio_common_mei_dataframes(
        str(path), quiet_native_warnings=True,
    )
    assert offsets == [0.0, 2e-10]
    assert labels == {0.0: 9}
    result = _parse(path, "verovio", filter_zero_duration=False)
    assert result["df_pitch"].set_index("xml_id")["Measure"].to_dict() == {"grace": 9, "note": 9}


def test_partitura_grid_mismatch_keeps_positions(tmp_path, monkeypatch, capsys):
    path = _numbered_score(tmp_path / "mismatch.mei", ("2", "3", "4"))
    monkeypatch.setattr(partitura_backend, "_partitura_measure_offsets", lambda score: [0.0, 2.0])
    result = _parse(path, "partitura", include_xml_ids=False)
    assert result["measure_offsets"] == [0.0, 2.0]
    assert result["df_pitch"]["Measure"].tolist() == [1, 2, 2]
    assert _event_measures(result, "measure") == {"m1": 2, "m2": 3, "m3": 4}
    assert capsys.readouterr().out.count("Partitura kept measure positions for mismatch.mei") == 1


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [(("2", "3", "4"), (2, 3, 4)), (("1", "2", "2", "3"), (1, 2, 3, 4))],
)
def test_partitura_conversion_uses_original_bar_numbers(tmp_path, monkeypatch, numbers, expected):
    source = _numbered_score(tmp_path / "source.mei", numbers)
    converted = _numbered_score(tmp_path / "converted.mei", tuple(range(5, 5 + len(numbers))))
    load_score = partitura_backend._load_partitura_score

    def load_after_conversion(path):
        if path != str(converted):
            raise ValueError("element is not yet supported")
        return load_score(path)

    monkeypatch.setattr(partitura_backend, "_load_partitura_score", load_after_conversion)
    monkeypatch.setattr(
        partitura_backend,
        "_convert_mei_with_verovio_for_partitura",
        lambda *args, **kwargs: (str(converted), None, 0, 0),
    )
    result = _parse(source, "partitura")
    assert result["df_pitch"].set_index("xml_id")["Measure"].to_dict() == _numbered_ids("n", expected)
    events = result["df_events"].set_index("xml_id")
    for index, number in enumerate(expected, start=1):
        assert set(events.loc[[f"m{index}"], "Measure"].tolist()) == {number}
        assert set(events.loc[[f"d{index}"], "Measure"].tolist()) == {number}


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"measure_labels": {-1.0: 0, 0.0: 1, 2.0: 5}}, [0, 1, 5, pd.NA]),
        ({"measure_labels": {-1.0: 0, 2.0: 5}}, [1, 2, 3, pd.NA]),
        ({}, [1, 2, 3, pd.NA]),
    ],
)
def test_reanchor_applies_only_complete_labels(kwargs, expected):
    frame = pd.DataFrame({"Global Onset": [-1.0, 1.0, 2.0, float("nan")], "Duration": [1.0] * 4})
    result = reanchor_to_measure_offsets(frame, [-1.0, 0.0, 2.0], **kwargs)
    pd.testing.assert_series_equal(result["Measure"], pd.Series(expected, name="Measure", dtype="Int64"))
    pd.testing.assert_frame_equal(result[frame.columns], frame)
    assert result["Local Onset"].iloc[:3].tolist() == [1.0, 1.0, 0.0]
    assert pd.isna(result["Local Onset"].iloc[3])


@pytest.mark.parametrize(
    ("offsets", "labels", "expected"),
    [
        ([4, 0, 2, float("inf")], [0, 1, 5], {0.0: 0, 2.0: 1, 4.0: 5}),
        ([0, 2], [0, 1, 5], None),
        ([0, 2, 2.0000000001], [0, 1, 5], None),
        ([0, 2], None, None),
    ],
)
def test_grid_measure_labels_uses_normalised_offsets(offsets, labels, expected):
    assert _grid_measure_labels(offsets, labels) == expected
