from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camat.parser_registry import parse_files
from camat.timeline_backend import (
    add_timeline_rhythm_analysis,
    build_timeline_duration_counts,
    build_timeline_onset_position_counts,
    find_duplicate_mei_xml_ids,
    load_timeline_mei_with_verovio,
    timeline_to_mei,
)


SAMPLE_RAP = """!!!OTL: Timeline Test
!!!COM: CAMAT
**recip\t**lyrics\t**ipa\t**stress\t**break\t**rhyme
*M4/4\t*clefX\t*clefX\t*clefX\t*clefX\t*clefX
*>Verse1
=0
16\t.\tR\t.\t.\t.
16\tHis\thIz\t0\t5\t.
8\tpalms\tpalmz\t1\t.\t(A
=1
4\tare\tar\t0\t.\t.
4\tswea-\tswE\t1\t.\tB
4\t.\tR\t.\t.\t.
4\t-ty.\tti\t0\t.\tb)
=2
2\tKnees\tniz\t1\t3\t.
2\tweak.\twik\t1\t.\t.
*-\t*-\t*-\t*-\t*-\t*-
"""


def test_timeline_parse_rhythm_schema_and_mei() -> None:
    with TemporaryDirectory() as tmpdir:
        source_path = Path(tmpdir) / "sample.rap"
        source_path.write_text(SAMPLE_RAP, encoding="utf-8")
        results, _dfs_by_name, _last_df = parse_files(
            [str(source_path)],
            parsing_backend="timeline",
            add_rhythm_analysis=True,
        )
    df = results[0]["df_timeline"]
    metadata = results[0]["metadata"]

    assert metadata["OTL"] == "Timeline Test"
    assert len(df) == 9
    assert {"duration_count_raw", "onset_position", "onset_position_share"}.issubset(df.columns)
    assert pd.isna(df.loc[df["is_rest"].astype(bool), "onset_position"]).all()
    assert df["duration_share"].dropna().sum() > 0

    duration_counts = build_timeline_duration_counts(df, normalize=True)
    assert set(duration_counts.columns) == {"source", "duration", "count_raw", "share", "count"}
    assert abs(float(duration_counts["share"].sum()) - 1.0) < 1e-9

    onset_counts, onset_summary = build_timeline_onset_position_counts(df)
    assert onset_summary["regular_span_quarters"] == 4.0
    assert onset_summary["bin_size"] == 0.25
    assert 3.25 in set(onset_counts["onset_position"])
    assert abs(float(onset_counts.groupby("meter_group")["share"].sum().iloc[0]) - 1.0) < 1e-9

    auto_counts, auto_summary = build_timeline_onset_position_counts(df, bin_size="auto")
    assert auto_summary["bin_size"] == 0.25
    assert set(auto_counts["onset_position"]) == set(onset_counts["onset_position"])

    rest_filtered_span_df = pd.DataFrame(
        {
            "measure_index": [0, 0, 0, 0],
            "local_onset": [0.0, 1.0, 2.0, 3.0],
            "duration": [1.0, 1.0, 1.0, 1.0],
            "meter": ["4/4", "4/4", "4/4", "4/4"],
            "is_rest": [False, False, False, True],
        }
    )
    rest_filtered_counts, _ = build_timeline_onset_position_counts(
        rest_filtered_span_df,
        include_rests=False,
    )
    assert set(rest_filtered_counts["meter_group"]) == {"4 quarter lengths"}

    enriched = add_timeline_rhythm_analysis(df, onset_bin_size="auto")
    assert "onset_position_count_raw" in enriched.columns

    mei = timeline_to_mei(
        enriched,
        metadata=metadata,
        staff_lines=1,
        show_clef=False,
        note_position="staff",
        measures_per_system=2,
        lyric_info_fields=["stress", "duration_share", "onset_position_share"],
        lyric_info_labels={"stress": "S", "duration_share": "DurShare", "onset_position_share": "BeatShare"},
        lyric_info_value_formats={"duration_share": ".0%", "onset_position_share": ".0%"},
        lyric_info_max_value_chars=4,
        lyric_info_layout="separate",
        include_annotations=True,
    )
    assert "<sb/>" in mei
    assert "DurShare:22%" in mei
    assert "BeatShare:14%" in mei
    assert ".222222" not in mei
    assert find_duplicate_mei_xml_ids(mei).empty

    root = ET.fromstring(mei)
    ns = {"mei": "http://www.music-encoding.org/ns/mei"}
    assert len(root.findall(".//mei:measure", ns)) == 3
    assert len(root.findall(".//mei:annot[@type='rap-token']", ns)) >= 1
    assert load_timeline_mei_with_verovio(
        mei,
        breaks="encoded",
        pageWidth=2400,
        pageHeight=1600,
        scale=35,
        adjustPageHeight=True,
    ) >= 1


if __name__ == "__main__":
    test_timeline_parse_rhythm_schema_and_mei()
    print("timeline backend test passed")
