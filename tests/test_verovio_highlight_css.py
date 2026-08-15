import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from camat.verovio_render import (
    vrv_crop_svg_to_ids,
    vrv_crop_svgs_to_ids,
    vrv_inject_highlight_css,
    vrv_mask_mei_to_ids,
)


SVG = '<svg xmlns="http://www.w3.org/2000/svg"><g id="n1"><path d="M0 0"/></g></svg>'
CROPPABLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="100px" height="50px">
  <svg class="definition-scale" viewBox="0 0 1000 500">
    <g class="page-margin" transform="translate(100, 50)">
      <g id="staff-1" class="staff">
        <g id="bbox-staff-1" class="staff bounding-box">
          <rect x="0" y="100" width="800" height="100"/>
        </g>
        <g id="n1" class="note">
          <g id="bbox-n1" class="note bounding-box">
            <rect x="300" y="120" width="40" height="60"/>
          </g>
        </g>
      </g>
    </g>
  </svg>
</svg>"""
FIXTURE_MEI = Path(__file__).parent / "fixtures" / "basic.mei"
DURATION_FIXTURE_MEI = Path(__file__).parent / "fixtures" / "duration_semantics.mei"
CLEF_CHANGE_MEI = """<mei xmlns="http://www.music-encoding.org/ns/mei">
  <music><body><mdiv><score>
    <scoreDef meter.count="4" meter.unit="4">
      <staffGrp><staffDef n="1" clef.shape="G" clef.line="2"/></staffGrp>
    </scoreDef>
    <section>
      <measure n="1"><staff n="1"><layer n="1">
        <clef shape="F" line="4"/>
        <note xml:id="before" pname="c" oct="3" dur="4"/>
      </layer></staff></measure>
      <measure n="2"><staff n="1"><layer n="1">
        <note xml:id="selected" pname="d" oct="3" dur="4"/>
      </layer></staff></measure>
    </section>
  </score></mdiv></body></music>
</mei>"""


class VerovioHighlightCssTests(unittest.TestCase):
    def test_highlight_css_is_scoped_per_svg_output(self):
        first = vrv_inject_highlight_css(SVG, ["#n1"], scope_id="cell-one")
        second = vrv_inject_highlight_css(SVG, ["#n1"], scope_id="cell-two")

        self.assertIn('data-camat-vrv-scope="cell-one"', first)
        self.assertIn('svg[data-camat-vrv-scope="cell-one"] #n1 path', first)
        self.assertIn('data-camat-vrv-scope="cell-two"', second)
        self.assertNotIn('svg[data-camat-vrv-scope="cell-one"]', second)

    def test_mei_friend_style_uses_familiar_blue_pulse(self):
        highlighted = vrv_inject_highlight_css(
            SVG,
            ["#n1"],
            color="#4e8bed",
            highlight_style="mei-friend",
            scope_id="mei-friend-demo",
        )

        self.assertIn("#4e8bed", highlighted)
        self.assertIn("#0e4bad", highlighted)
        self.assertIn(
            "animation: camatVrvPulse-mei-friend-demo 0.6s ease", highlighted
        )
        self.assertNotIn("#4e8bed !important", highlighted)

    def test_unknown_highlight_style_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "highlight_style"):
            vrv_inject_highlight_css(SVG, ["#n1"], highlight_style="unknown")

    def test_crop_uses_selected_horizontal_span_and_staff_height(self):
        cropped = vrv_crop_svg_to_ids(
            CROPPABLE_SVG, ["#n1"], x_padding=20, y_padding=10
        )

        self.assertIn('viewBox="380 140 80 120"', cropped)
        self.assertIn('width="8px"', cropped)
        self.assertIn('height="12px"', cropped)

    def test_context_crop_retains_staff_start_for_clef_and_signatures(self):
        cropped = vrv_crop_svg_to_ids(
            CROPPABLE_SVG,
            ["#n1"],
            x_padding=20,
            y_padding=10,
            include_staff_context=True,
        )

        self.assertIn('viewBox="80 140 380 120"', cropped)

    def test_multi_page_crop_omits_pages_without_selection(self):
        cropped = vrv_crop_svgs_to_ids(
            [SVG.replace('id="n1"', 'id="other"'), CROPPABLE_SVG], ["#n1"]
        )

        self.assertEqual(len(cropped), 1)
        self.assertIn("definition-scale", cropped[0])

    def test_masked_mei_keeps_selected_note_and_duration_spaces(self):
        masked = vrv_mask_mei_to_ids(
            FIXTURE_MEI.read_text(encoding="utf-8"), ["#note-d4"]
        )
        root = ET.fromstring(masked)
        namespace = {"mei": "http://www.music-encoding.org/ns/mei"}
        xml_id = "{http://www.w3.org/XML/1998/namespace}id"

        measures = root.findall(".//mei:measure", namespace)
        notes = root.findall(".//mei:note", namespace)
        spaces = root.findall(".//mei:space", namespace)
        staff_defs = root.findall(".//mei:staffDef", namespace)

        self.assertEqual(len(measures), 1)
        self.assertEqual([note.get(xml_id) for note in notes], ["note-d4"])
        self.assertEqual(len(spaces), 3)
        self.assertEqual({space.get("dur") for space in spaces}, {"4"})
        self.assertIn("note-c4", {space.get(xml_id) for space in spaces})
        self.assertEqual(len(staff_defs), 1)

    def test_masked_mei_rejects_unknown_ids(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            vrv_mask_mei_to_ids(
                FIXTURE_MEI.read_text(encoding="utf-8"), ["#does-not-exist"]
            )

    def test_masked_mei_preserves_partial_tuplet_span_ratio(self):
        masked = vrv_mask_mei_to_ids(
            DURATION_FIXTURE_MEI.read_text(encoding="utf-8"), ["#quintuplet-3"]
        )
        root = ET.fromstring(masked)
        namespace = {"mei": "http://www.music-encoding.org/ns/mei"}
        xml_id = "{http://www.w3.org/XML/1998/namespace}id"
        tuplets = root.findall(".//mei:tuplet", namespace)
        notes = root.findall(".//mei:note", namespace)

        self.assertEqual(len(tuplets), 1)
        self.assertEqual(tuplets[0].get("num"), "5")
        self.assertEqual(tuplets[0].get("numbase"), "3")
        self.assertEqual([note.get(xml_id) for note in notes], ["quintuplet-3"])
        self.assertEqual(notes[0].get("dur"), "8")
        self.assertEqual(len(tuplets[0].findall("mei:space", namespace)), 4)

    def test_masked_mei_promotes_active_inline_clef(self):
        masked = vrv_mask_mei_to_ids(CLEF_CHANGE_MEI, ["#selected"])
        root = ET.fromstring(masked)
        namespace = {"mei": "http://www.music-encoding.org/ns/mei"}
        staff_def = root.find(".//mei:scoreDef/mei:staffGrp/mei:staffDef", namespace)

        self.assertIsNotNone(staff_def)
        self.assertEqual(staff_def.get("clef.shape"), "F")
        self.assertEqual(staff_def.get("clef.line"), "4")


if __name__ == "__main__":
    unittest.main()
