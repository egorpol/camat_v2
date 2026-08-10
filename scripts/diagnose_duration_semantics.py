#!/usr/bin/env python3
"""Diagnose CAMAT metric, tied-logical, and performed duration semantics."""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/camat-matplotlib")

from camat.verovio_backend import _verovio_common_mei_dataframes  # noqa: E402


DEFAULT_SOURCE = REPO_ROOT / "tests" / "fixtures" / "duration_semantics.mei"
ATTACHMENT_COLUMNS = (
    "grace",
    "tied",
    "slurred",
    "tuplet",
    "fermata",
    "articulations",
    "ornaments",
    "technical",
)


def parse_pitch_rows(source: Path, *, collapse: bool) -> pd.DataFrame:
    df_pitch, *_ = _verovio_common_mei_dataframes(
        str(source),
        parse_enharmonic=True,
        include_xml_ids=True,
        include_note_attachments=True,
        collapse_tied_pitch_events=collapse,
        quiet_native_warnings=True,
    )
    return df_pitch


def _assert_fixture_semantics(uncollapsed: pd.DataFrame, collapsed: pd.DataFrame) -> None:
    uncollapsed = uncollapsed.set_index("xml_id", drop=False)
    collapsed = collapsed.set_index("xml_id", drop=False)

    assert math.isclose(float(uncollapsed.at["dotted", "Duration"]), 1.5)
    for xml_id in ("triplet-1", "triplet-2", "triplet-3"):
        assert math.isclose(float(uncollapsed.at[xml_id, "Duration"]), 1 / 3)
    for index in range(1, 6):
        assert math.isclose(float(uncollapsed.at[f"quintuplet-{index}", "Duration"]), 0.3)

    assert float(uncollapsed.at["grace", "Duration"]) == 0.0
    assert math.isclose(
        float(uncollapsed.at["grace", "Global Onset"]),
        float(uncollapsed.at["measure-1-tail", "Global Onset"]),
    )

    tie_ids = ["tie-a", "tie-b", "tie-c"]
    segment_sum = float(uncollapsed.loc[tie_ids, "Duration"].sum())
    assert math.isclose(segment_sum, 2.25)
    assert math.isclose(float(uncollapsed.at["tie-a", "Logical Duration"]), segment_sum)
    assert pd.isna(uncollapsed.at["tie-b", "Logical Duration"])
    assert pd.isna(uncollapsed.at["tie-c", "Logical Duration"])
    assert "tie-b" not in collapsed.index and "tie-c" not in collapsed.index
    assert math.isclose(float(collapsed.at["tie-a", "Duration"]), 1.0)
    assert math.isclose(float(collapsed.at["tie-a", "Logical Duration"]), segment_sum)
    assert pd.isna(collapsed.at["tie-a", "Performed Duration"])
    assert math.isclose(float(uncollapsed.at["attr-tie-a", "Logical Duration"]), 4.0)
    assert pd.isna(uncollapsed.at["attr-tie-b", "Logical Duration"])
    assert "attr-tie-b" not in collapsed.index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    source = args.source.expanduser().resolve()

    uncollapsed = parse_pitch_rows(source, collapse=False)
    collapsed = parse_pitch_rows(source, collapse=True)

    print(f"source: {source}")
    print(f"rows: uncollapsed={len(uncollapsed)} collapsed={len(collapsed)}")
    for label, frame in (("uncollapsed", uncollapsed), ("collapsed", collapsed)):
        print(
            f"{label}: metric_sum={frame['Duration'].sum():.12g} "
            f"logical_sum={frame['Logical Duration'].sum():.12g}"
        )
    for column in ATTACHMENT_COLUMNS:
        values = uncollapsed[column].dropna()
        print(f"{column}: rows={len(values)} values={sorted(map(str, values.unique()))}")

    if source == DEFAULT_SOURCE.resolve():
        _assert_fixture_semantics(uncollapsed, collapsed)
        print("OK: fixture duration invariants passed")
    else:
        print("INFO: custom source reported; fixture-specific assertions skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
