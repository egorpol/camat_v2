"""Tests for :func:`camat.add_facsimile_columns`."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import camat
from camat.facsimile_table import add_facsimile_columns
from camat.facsimile_viewer import FacsimileUnavailableError


ZONE_FIELDS = (
    "zone_id",
    "surface_id",
    "page",
    "image",
    "zone_ulx",
    "zone_uly",
    "zone_lrx",
    "zone_lry",
)
COLUMNS = ZONE_FIELDS + ("zone_status",)


def _write_basic_mei(
    path: Path,
    *,
    include_facsimile: bool = True,
    zone_ulx: int = 10,
    zone_lrx: int = 80,
    measure_facs: str | None = "#zone-1",
    measure_id: str | None = "measure-1",
    extra_body: str = "",
    extra_score_def: str = "",
) -> None:
    facsimile = f'''
  <facsimile>
    <surface xml:id="surface-1" n="1">
      <graphic target="scan.svg" width="100" height="200"/>
      <zone xml:id="zone-1" type="measure" ulx="{zone_ulx}" uly="20" lrx="{zone_lrx}" lry="180"/>
    </surface>
  </facsimile>''' if include_facsimile else ""
    if include_facsimile and measure_facs is not None:
        facs_attr = f' facs="{measure_facs}"'
    else:
        facs_attr = ""
    measure_id_attr = f' xml:id="{measure_id}"' if measure_id else ""
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">
  <meiHead><fileDesc><titleStmt><title>Fixture</title></titleStmt>
    <pubStmt><p>Test fixture</p></pubStmt></fileDesc></meiHead>
  {facsimile}
  <music><body><mdiv><score>
    <scoreDef meter.count="4" meter.unit="4"><staffGrp><staffDef n="1" lines="5">
      {extra_score_def}
    </staffDef></staffGrp></scoreDef>
    <section>
      <measure{measure_id_attr} n="1"{facs_attr}>
        <staff n="1"><layer n="1">
          <note xml:id="note-1" pname="c" oct="4" dur="1"/>
        </layer></staff>
      </measure>
      {extra_body}
    </section>
  </score></mdiv></body></music>
</mei>
''',
        encoding="utf-8",
    )


def _write_split_mei(path: Path) -> None:
    path.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0">
  <meiHead><fileDesc><titleStmt><title>Split</title></titleStmt>
    <pubStmt><p>Test fixture</p></pubStmt></fileDesc></meiHead>
  <facsimile>
    <surface xml:id="s1" n="3">
      <graphic target="a.png" width="100" height="100"/>
      <zone xml:id="z1" type="measure" ulx="10" uly="11" lrx="19" lry="20"/>
      <zone xml:id="z2" type="measure" ulx="40" uly="41" lrx="49" lry="50"/>
      <zone xml:id="z4" type="measure" ulx="1" uly="2" lrx="3" lry="4"/>
    </surface>
    <surface xml:id="s2" n="4">
      <graphic target="b.png" width="100" height="100"/>
      <zone xml:id="z3" type="measure" ulx="70" uly="71" lrx="79" lry="80"/>
    </surface>
  </facsimile>
  <music><body><mdiv><score>
    <scoreDef meter.count="4" meter.unit="4"><staffGrp><staffDef n="1" lines="5"/></staffGrp></scoreDef>
    <section>
      <measure xml:id="m1" n="1" facs="#z1 #z2 #z3">
        <staff n="1"><layer n="1"><note xml:id="n1" pname="c" oct="4" dur="4"/></layer></staff>
      </measure>
      <measure n="2" facs="#z4">
        <staff n="1"><layer n="1"><note xml:id="n2" pname="d" oct="4" dur="4"/></layer></staff>
      </measure>
      <measure xml:id="m3" n="3">
        <staff n="1"><layer n="1"><note xml:id="n3" pname="e" oct="4" dur="4"/></layer></staff>
      </measure>
    </section>
  </score></mdiv></body></music>
</mei>
''',
        encoding="utf-8",
    )


def test_public_access_via_camat() -> None:
    assert camat.add_facsimile_columns is add_facsimile_columns


def test_linked_single_zone_and_int_corners_csv(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei)
    table = pd.DataFrame({"xml_id": ["note-1"], "Voice": [1]})

    result = add_facsimile_columns(table, mei)

    assert list(result.columns[-9:]) == list(COLUMNS)
    assert result["zone_status"].iloc[0] == "linked"
    assert result["zone_id"].iloc[0] == "zone-1"
    assert result["surface_id"].iloc[0] == "surface-1"
    assert result["page"].iloc[0] == "1"
    assert result["image"].iloc[0] == "scan.svg"
    assert result["zone_ulx"].dtype == "Int64"
    assert int(result["zone_ulx"].iloc[0]) == 10
    csv_text = result.to_csv(index=False)
    assert ",10," in csv_text or csv_text.endswith(",10\n") or ",10\n" in csv_text
    assert "10.0" not in csv_text


def test_all_six_statuses(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(
        mei,
        extra_score_def='<clef xml:id="clef-1" shape="G" line="2"/>',
        extra_body='''
      <measure xml:id="measure-2" n="2">
        <staff n="1"><layer n="1">
          <note xml:id="note-2" pname="d" oct="4" dur="1"/>
        </layer></staff>
      </measure>''',
    )
    table = pd.DataFrame(
        {
            "xml_id": [
                "note-1",
                float("nan"),
                "absent-id",
                "clef-1",
                "note-2",
            ]
        }
    )

    result = add_facsimile_columns(table, mei)

    assert list(result["zone_status"]) == [
        "linked",
        "no xml_id",
        "id not in file",
        "outside measure",
        "missing facs",
    ]
    assert int(result["zone_id"].notna().sum()) == 1
    for name in ZONE_FIELDS:
        assert result.loc[result["zone_status"] != "linked", name].isna().all()


def test_facsimile_unavailable_status_with_allow_missing(tmp_path: Path) -> None:
    mei = tmp_path / "plain.mei"
    _write_basic_mei(mei, include_facsimile=False)
    table = pd.DataFrame({"xml_id": ["note-1", None]})

    result = add_facsimile_columns(table, mei, allow_missing_facsimile=True)

    assert set(result["zone_status"]) == {"facsimile unavailable"}
    assert result["zone_id"].isna().all()


def test_split_bar_token_alignment(tmp_path: Path) -> None:
    mei = tmp_path / "split.mei"
    _write_split_mei(mei)
    table = pd.DataFrame(
        {"xml_id": ["n1", "n2", "n1", "n3"], "Voice": [1, 1, 2, 1]},
        index=[7, 3, 3, 9],
    )

    result = add_facsimile_columns(table, mei)

    row = result.iloc[0]
    assert row["zone_id"] == "z1 z2 z3"
    assert row["surface_id"] == "s1 s1 s2"
    assert row["page"] == "3 3 4"
    assert row["image"] == "a.png a.png b.png"
    assert row["zone_ulx"] == "10 40 70"
    assert row["zone_uly"] == "11 41 71"
    assert row["zone_lrx"] == "19 49 79"
    assert row["zone_lry"] == "20 50 80"
    assert result["zone_ulx"].dtype == object
    # Same page twice (z1, z2 on page 3) and a cross-page fragment (z3 on 4).
    assert row["page"].split() == ["3", "3", "4"]
    # Single-zone row still string once any split exists in the table.
    assert result["zone_ulx"].iloc[1] == "1"
    assert result["zone_id"].iloc[1] == "z4"
    assert result["zone_status"].iloc[1] == "linked"
    assert result["zone_status"].iloc[3] == "missing facs"


def test_missing_xml_id_variants(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei)
    table = pd.DataFrame({"xml_id": [float("nan"), None, pd.NA, ""]})

    result = add_facsimile_columns(table, mei)

    assert list(result["zone_status"]) == ["no xml_id"] * 4
    assert result["zone_id"].isna().all()


def test_repeated_ids_and_index_labels_and_no_mutation(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei)
    table = pd.DataFrame(
        {"xml_id": ["note-1", "note-1"], "Voice": [1, 2]},
        index=[5, 5],
    )
    before = table.copy(deep=True)

    result = add_facsimile_columns(table, mei)

    assert table.equals(before)
    assert result.index.equals(table.index)
    assert list(result["zone_id"]) == ["zone-1", "zone-1"]
    assert list(result["zone_status"]) == ["linked", "linked"]
    assert list(result["Voice"]) == [1, 2]


def test_measure_without_xml_id_still_links(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei, measure_id=None)
    table = pd.DataFrame({"xml_id": ["note-1"]})

    result = add_facsimile_columns(table, mei)

    assert result["zone_status"].iloc[0] == "linked"
    assert result["zone_id"].iloc[0] == "zone-1"


def test_element_in_nested_ending(tmp_path: Path) -> None:
    mei = tmp_path / "ending.mei"
    _write_basic_mei(
        mei,
        extra_body='''
      <ending n="1">
        <measure xml:id="measure-end" n="2" facs="#zone-1">
          <staff n="1"><layer n="1">
            <note xml:id="note-end" pname="e" oct="4" dur="1"/>
          </layer></staff>
        </measure>
      </ending>''',
    )
    # Reuse zone-1 on a second measure: valid for this synthetic fixture.
    table = pd.DataFrame({"xml_id": ["note-end"]})

    result = add_facsimile_columns(table, mei)

    assert result["zone_status"].iloc[0] == "linked"
    assert result["zone_id"].iloc[0] == "zone-1"


def test_row_xml_id_is_the_measure_itself(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei)
    table = pd.DataFrame({"xml_id": ["measure-1"]})

    result = add_facsimile_columns(table, mei)

    assert result["zone_status"].iloc[0] == "linked"
    assert result["zone_id"].iloc[0] == "zone-1"


def test_no_facsimile_raises_by_default(tmp_path: Path) -> None:
    mei = tmp_path / "plain.mei"
    _write_basic_mei(mei, include_facsimile=False)
    table = pd.DataFrame({"xml_id": ["note-1"]})

    with pytest.raises(FacsimileUnavailableError):
        add_facsimile_columns(table, mei)


def test_invalid_zone_raises_in_both_modes(tmp_path: Path) -> None:
    mei = tmp_path / "broken.mei"
    _write_basic_mei(mei, zone_lrx=500)
    table = pd.DataFrame({"xml_id": ["note-1"]})

    with pytest.raises(RuntimeError, match="outside|Zone"):
        add_facsimile_columns(table, mei)
    with pytest.raises(RuntimeError, match="outside|Zone"):
        add_facsimile_columns(table, mei, allow_missing_facsimile=True)


def test_missing_xml_id_column_raises(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei)
    table = pd.DataFrame({"Voice": [1]})

    with pytest.raises(ValueError, match="xml_id"):
        add_facsimile_columns(table, mei)


def test_empty_table_keeps_new_columns(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei)
    table = pd.DataFrame({"xml_id": pd.Series(dtype=object), "Voice": pd.Series(dtype=int)})

    result = add_facsimile_columns(table, mei)

    assert len(result) == 0
    assert list(result.columns[-9:]) == list(COLUMNS)
    assert result["zone_ulx"].dtype == "Int64"


def _write_two_zone_mei(path: Path, *, target: str = "a.png", n: str = "3", facs: str = "#z1 #z2") -> None:
    path.write_text(
        f'''<mei xmlns="http://www.music-encoding.org/ns/mei"><music><facsimile>
<surface xml:id="s1" n="{n}"><graphic target="{target}" width="100" height="100"/>
<zone xml:id="z1" type="measure" ulx="1" uly="1" lrx="9" lry="9"/>
<zone xml:id="z2" type="measure" ulx="11" uly="1" lrx="19" lry="9"/></surface>
</facsimile><body><mdiv><score><section>
<measure xml:id="m1" n="1" facs="{facs}"><staff n="1"><layer n="1"><note xml:id="n1"/></layer></staff></measure>
</section></score></mdiv></body></music></mei>
''',
        encoding="utf-8",
    )


@pytest.mark.parametrize("name", COLUMNS)
@pytest.mark.parametrize("allow_missing", (False, True))
def test_existing_output_column_is_refused_not_overwritten(
    tmp_path: Path, name: str, allow_missing: bool
) -> None:
    mei = tmp_path / "plain.mei"
    _write_basic_mei(mei, include_facsimile=False)
    table = pd.DataFrame({"xml_id": ["note-1"], name: ["keep me"]})
    before = table.copy(deep=True)

    with pytest.raises(ValueError, match=name):
        add_facsimile_columns(table, mei, allow_missing_facsimile=allow_missing)

    pd.testing.assert_frame_equal(table, before)


def test_second_pass_over_an_enriched_table_is_refused(tmp_path: Path) -> None:
    mei = tmp_path / "page.mei"
    _write_basic_mei(mei)
    once = add_facsimile_columns(pd.DataFrame({"xml_id": ["note-1"]}), mei)

    with pytest.raises(ValueError, match="zone_id"):
        add_facsimile_columns(once, mei)


@pytest.mark.parametrize(
    ("target", "n"),
    (("a.png b.png", "3"), ("a b.png", "3"), ("a.png", "3 4")),
)
def test_split_bar_with_a_space_in_a_value_is_refused(tmp_path: Path, target: str, n: str) -> None:
    mei = tmp_path / "split.mei"
    _write_two_zone_mei(mei, target=target, n=n)

    with pytest.raises(ValueError, match="contains a space"):
        add_facsimile_columns(pd.DataFrame({"xml_id": ["n1"]}), mei)


def test_single_zone_bar_keeps_a_raw_target_with_a_space(tmp_path: Path) -> None:
    mei = tmp_path / "single.mei"
    _write_two_zone_mei(mei, target="a.png b.png", facs="#z1")

    result = add_facsimile_columns(pd.DataFrame({"xml_id": ["n1"]}), mei)

    assert result["image"].iloc[0] == "a.png b.png"
    assert result["zone_status"].iloc[0] == "linked"
    assert result["zone_id"].iloc[0] == "z1"


def test_split_bar_elsewhere_in_the_file_does_not_stop_other_rows(tmp_path: Path) -> None:
    mei = tmp_path / "split.mei"
    _write_two_zone_mei(mei, target="a.png b.png")

    result = add_facsimile_columns(pd.DataFrame({"xml_id": ["no-such-id"]}), mei)

    assert result["zone_status"].iloc[0] == "id not in file"
