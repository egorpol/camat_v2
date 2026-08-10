from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("verovio")

from camat.analysis_utils import build_duration_counts
from camat.verovio_backend import _verovio_common_mei_dataframes


FIXTURE = Path(__file__).parent / "fixtures" / "duration_semantics.mei"


def _parse(*, collapse: bool) -> pd.DataFrame:
    df_pitch, *_ = _verovio_common_mei_dataframes(
        str(FIXTURE),
        parse_enharmonic=True,
        include_xml_ids=True,
        include_note_attachments=True,
        collapse_tied_pitch_events=collapse,
        quiet_native_warnings=True,
    )
    return df_pitch.set_index("xml_id", drop=False)


def test_metric_durations_include_dots_and_tuplet_ratios_once() -> None:
    df = _parse(collapse=False)

    assert df.at["dotted", "Duration"] == pytest.approx(1.5)
    assert df.loc[["triplet-1", "triplet-2", "triplet-3"], "Duration"].tolist() == pytest.approx(
        [1 / 3, 1 / 3, 1 / 3]
    )
    assert df.loc[
        [f"quintuplet-{index}" for index in range(1, 6)], "Duration"
    ].tolist() == pytest.approx([0.3] * 5)
    assert df.loc[
        [f"quintuplet-{index}" for index in range(1, 6)], "tuplet"
    ].tolist() == ["start", "member", "member", "member", "stop"]


def test_grace_and_expressive_attachments_do_not_change_metric_duration() -> None:
    df = _parse(collapse=False)

    assert df.at["grace", "Duration"] == 0.0
    assert df.at["grace", "Global Onset"] == pytest.approx(
        df.at["measure-1-tail", "Global Onset"]
    )
    assert df.at["grace", "grace"] is True

    assert df.at["dotted", "Duration"] == pytest.approx(1.5)
    assert df.at["dotted", "fermata"] is True
    assert df.at["dotted", "articulations"] == "stacc"
    assert df.at["dotted", "ornaments"] == "trill"
    assert df.at["dotted", "technical"] == "bend"
    assert df.at["dotted", "slurred"] == "start"
    assert pd.isna(df.at["dotted", "Performed Duration"])


def test_uncollapsed_ties_keep_segments_and_count_one_logical_duration() -> None:
    df = _parse(collapse=False)

    assert df.loc[["tie-a", "tie-b", "tie-c"], "Duration"].tolist() == pytest.approx(
        [1.0, 0.5, 0.75]
    )
    assert df.at["tie-a", "Logical Duration"] == pytest.approx(2.25)
    assert pd.isna(df.at["tie-b", "Logical Duration"])
    assert pd.isna(df.at["tie-c", "Logical Duration"])
    assert df.at["attr-tie-a", "tied"] == "start"
    assert df.at["attr-tie-b", "tied"] == "stop"
    assert df.at["attr-tie-a", "Logical Duration"] == pytest.approx(4.0)
    assert pd.isna(df.at["attr-tie-b", "Logical Duration"])


def test_collapsed_ties_sum_segments_once_without_overwriting_metric_duration() -> None:
    uncollapsed = _parse(collapse=False)
    collapsed = _parse(collapse=True)

    assert "tie-a" in collapsed.index
    assert "tie-b" not in collapsed.index
    assert "tie-c" not in collapsed.index
    assert collapsed.at["tie-a", "Duration"] == pytest.approx(1.0)
    assert collapsed.at["tie-a", "Logical Duration"] == pytest.approx(
        uncollapsed.loc[["tie-a", "tie-b", "tie-c"], "Duration"].sum()
    )
    assert collapsed["Logical Duration"].sum() == pytest.approx(
        uncollapsed["Logical Duration"].sum()
    )
    assert collapsed.at["attr-tie-a", "Duration"] == pytest.approx(2.0)
    assert collapsed.at["attr-tie-a", "Logical Duration"] == pytest.approx(4.0)
    assert "attr-tie-b" not in collapsed.index


def test_duration_distribution_requires_an_explicit_concept_when_requested() -> None:
    df = _parse(collapse=False)

    metric_counts, metric_column = build_duration_counts(
        df,
        drop_zero=False,
        round_decimals=None,
        duration_column="Duration",
    )
    logical_counts, logical_column = build_duration_counts(
        df,
        drop_zero=False,
        round_decimals=None,
        duration_column="Logical Duration",
    )

    assert metric_column == "Duration"
    assert logical_column == "Logical Duration"
    assert int(metric_counts["count"].sum()) == len(df)
    assert int(logical_counts["count"].sum()) == int(df["Logical Duration"].notna().sum())
