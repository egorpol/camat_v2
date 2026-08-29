"""Interactive Jupyter editor for pasting MEI and rendering it with Verovio."""

from __future__ import annotations

from html import escape
from pathlib import Path
import uuid
import xml.etree.ElementTree as ET

from .facsimile_viewer import find_camat_root
from .quiet_utils import suppress_native_output
from .verovio_render import vrv_load_data, vrv_render_page, vrv_set_options

DEFAULT_MEI = """<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.1">
  <meiHead>
    <fileDesc>
      <titleStmt><title>Minimal MEI example</title></titleStmt>
      <pubStmt/>
    </fileDesc>
  </meiHead>
  <music>
    <body>
      <mdiv>
        <score>
          <scoreDef keysig="1s" meter.count="4" meter.unit="4">
            <staffGrp>
              <staffDef n="1" lines="5" clef.shape="G" clef.line="2"/>
            </staffGrp>
          </scoreDef>
          <section>
            <measure n="1">
              <staff n="1">
                <layer n="1">
                  <note pname="g" oct="4" dur="4" xml:id="m1n1"/>
                  <note pname="a" oct="4" dur="4" accid="s" xml:id="m1n2"/>
                  <note pname="b" oct="4" dur="4" xml:id="m1n3"/>
                  <note pname="c" oct="5" dur="4" xml:id="m1n4"/>
                </layer>
              </staff>
              <dynam startid="#m1n2">f</dynam>
            </measure>
          </section>
        </score>
      </mdiv>
    </body>
  </music>
</mei>
"""

DEFAULT_VEROVIO_SCALE = 80
# Keep the Verovio page close to A4 portrait. A much wider page makes the
# staff a thin strip, so CSS zoom only stretches empty width.
DEFAULT_PAGE_WIDTH = 2100
DEFAULT_PAGE_HEIGHT = 2970
DEFAULT_INITIAL_ZOOM_PERCENT = 200
DEFAULT_ZOOM_STEP_PERCENT = 25
DEFAULT_MIN_ZOOM_PERCENT = 50
DEFAULT_MAX_ZOOM_PERCENT = 600
DEFAULT_VIEWER_MAX_HEIGHT = 1100

__all__ = [
    "DEFAULT_MEI",
    "InteractiveMeiRenderer",
    "launch_interactive_mei_renderer",
    "make_mei_renderer_html",
    "validate_mei_text",
]


def validate_mei_text(mei_text: str) -> None:
    """Raise if ``mei_text`` is not well-formed XML with an ``<mei>`` root."""
    xml_root = ET.fromstring(mei_text)
    if xml_root.tag.rsplit("}", 1)[-1] != "mei":
        raise ValueError("The document root must be <mei>. Paste a complete MEI document.")


def _clamp_zoom_settings(
    *,
    initial_zoom_percent: int | float,
    zoom_step_percent: int | float,
    min_zoom_percent: int | float,
    max_zoom_percent: int | float,
) -> None:
    if min_zoom_percent <= 0:
        raise ValueError("min_zoom_percent must be greater than zero")
    if max_zoom_percent < min_zoom_percent:
        raise ValueError("max_zoom_percent must be greater than or equal to min_zoom_percent")
    if zoom_step_percent <= 0:
        raise ValueError("zoom_step_percent must be greater than zero")
    if not min_zoom_percent <= initial_zoom_percent <= max_zoom_percent:
        raise ValueError("initial_zoom_percent must be between min_zoom_percent and max_zoom_percent")


def make_mei_renderer_html(
    svg: str,
    *,
    viewer_id: str,
    zoom_percent: int | float = DEFAULT_INITIAL_ZOOM_PERCENT,
    viewer_max_height: int = DEFAULT_VIEWER_MAX_HEIGHT,
) -> str:
    """Return HTML for one rendered Verovio page at ``zoom_percent`` width."""
    return f"""
<style>
  #{viewer_id} .score-pane {{
    max-height: {viewer_max_height}px;
    overflow: auto;
    scrollbar-gutter: stable;
    border: 1px solid #d7dce2;
    border-radius: 6px;
    background: white;
    padding: 8px;
  }}
  #{viewer_id} .score-pane svg {{
    width: {zoom_percent:g}%;
    max-width: none;
    height: auto;
    display: block;
  }}
</style>
<div id="{viewer_id}">
  <div class="score-pane">{svg}</div>
</div>
"""


class InteractiveMeiRenderer:
    """Jupyter widget: edit MEI text and render the selected Verovio page."""

    def __init__(
        self,
        mei_text: str | None = None,
        *,
        initial_zoom_percent: int | float = DEFAULT_INITIAL_ZOOM_PERCENT,
        zoom_step_percent: int | float = DEFAULT_ZOOM_STEP_PERCENT,
        min_zoom_percent: int | float = DEFAULT_MIN_ZOOM_PERCENT,
        max_zoom_percent: int | float = DEFAULT_MAX_ZOOM_PERCENT,
        viewer_max_height: int = DEFAULT_VIEWER_MAX_HEIGHT,
        verovio_scale: int = DEFAULT_VEROVIO_SCALE,
        verovio_page_width: int = DEFAULT_PAGE_WIDTH,
        verovio_page_height: int = DEFAULT_PAGE_HEIGHT,
        show_verovio_warnings: bool = False,
        viewer_id: str | None = None,
    ) -> None:
        _clamp_zoom_settings(
            initial_zoom_percent=initial_zoom_percent,
            zoom_step_percent=zoom_step_percent,
            min_zoom_percent=min_zoom_percent,
            max_zoom_percent=max_zoom_percent,
        )
        self.mei_text = DEFAULT_MEI if mei_text is None else mei_text
        self.initial_zoom_percent = initial_zoom_percent
        self.zoom_step_percent = zoom_step_percent
        self.min_zoom_percent = min_zoom_percent
        self.max_zoom_percent = max_zoom_percent
        self.viewer_max_height = viewer_max_height
        self.verovio_scale = verovio_scale
        self.verovio_page_width = verovio_page_width
        self.verovio_page_height = verovio_page_height
        self.show_verovio_warnings = show_verovio_warnings
        self.viewer_id = viewer_id or f"mei-renderer-{uuid.uuid4().hex}"
        self.current_zoom = initial_zoom_percent
        self._cached_svg: str | None = None
        self._rendering = False
        self.mei_editor = None
        self.page_number = None
        self.status = None
        self.score_output = None
        self.zoom_out_btn = None
        self.zoom_reset_btn = None
        self.zoom_in_btn = None

    def current_mei(self) -> str:
        if self.mei_editor is None:
            return self.mei_text
        return str(self.mei_editor.value)

    def save(self, path: str | Path) -> Path:
        """Write the current editor text to ``path`` and return the resolved file."""
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = find_camat_root() / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.current_mei(), encoding="utf-8")
        return target.resolve()

    def _clamp_zoom(self, value: int | float) -> float:
        return min(self.max_zoom_percent, max(self.min_zoom_percent, float(value)))

    def _sync_zoom_buttons(self) -> None:
        if self.zoom_reset_btn is None:
            return
        self.zoom_reset_btn.description = f"{self.current_zoom:g}%"
        self.zoom_out_btn.disabled = self.current_zoom <= self.min_zoom_percent
        self.zoom_in_btn.disabled = self.current_zoom >= self.max_zoom_percent

    def _show_cached_score(self) -> None:
        if self._cached_svg is None or self.score_output is None:
            return
        from IPython.display import HTML, clear_output, display

        html = make_mei_renderer_html(
            self._cached_svg,
            viewer_id=f"{self.viewer_id}-{uuid.uuid4().hex[:8]}",
            zoom_percent=self.current_zoom,
            viewer_max_height=self.viewer_max_height,
        )
        with self.score_output:
            clear_output(wait=True)
            display(HTML(html))

    def _apply_zoom(self, value: int | float) -> None:
        self.current_zoom = self._clamp_zoom(value)
        self._sync_zoom_buttons()
        self._show_cached_score()

    def display(self) -> InteractiveMeiRenderer:
        import ipywidgets as widgets
        from IPython.display import clear_output, display

        self.mei_editor = widgets.Textarea(
            value=self.mei_text,
            layout=widgets.Layout(width="100%", height="430px"),
        )
        render_button = widgets.Button(
            description="Render MEI", button_style="primary", icon="music"
        )
        self.page_number = widgets.BoundedIntText(
            value=1,
            min=1,
            max=1,
            description="Page:",
            layout=widgets.Layout(width="150px"),
        )
        zoom_label = widgets.Label("Score zoom")
        self.zoom_out_btn = widgets.Button(
            description="−",
            tooltip="Zoom score out",
            layout=widgets.Layout(width="40px"),
        )
        self.zoom_reset_btn = widgets.Button(
            description=f"{self.current_zoom:g}%",
            tooltip="Reset score zoom",
            layout=widgets.Layout(width="70px"),
        )
        self.zoom_in_btn = widgets.Button(
            description="+",
            tooltip="Zoom score in",
            layout=widgets.Layout(width="40px"),
        )
        self._sync_zoom_buttons()
        self.status = widgets.HTML()
        self.score_output = widgets.Output()

        def render_mei(_=None) -> None:
            if self._rendering:
                return
            self._rendering = True
            try:
                mei_text = self.current_mei()
                validate_mei_text(mei_text)
                with suppress_native_output(enabled=not self.show_verovio_warnings):
                    vrv_set_options(
                        pageWidth=self.verovio_page_width,
                        pageHeight=self.verovio_page_height,
                        scale=self.verovio_scale,
                        breaks="auto",
                        adjustPageHeight=True,
                        footer="none",
                        svgViewBox=True,
                    )
                    page_count = vrv_load_data(mei_text, input_from="mei")
                if page_count < 1:
                    raise RuntimeError("Verovio loaded no renderable score pages.")
                self.page_number.max = page_count
                if self.page_number.value > page_count:
                    self.page_number.value = page_count
                with suppress_native_output(enabled=not self.show_verovio_warnings):
                    self._cached_svg = vrv_render_page(int(self.page_number.value))
                self._show_cached_score()
                self.status.value = (
                    f'<span style="color:#1a7f37">Rendered page {self.page_number.value} '
                    f"of {page_count}.</span>"
                )
            except Exception as exc:
                self._cached_svg = None
                with self.score_output:
                    clear_output(wait=True)
                self.status.value = (
                    '<span style="color:#cf222e"><strong>Could not render MEI:</strong> '
                    f"{escape(str(exc))}</span>"
                )
            finally:
                self._rendering = False

        render_button.on_click(render_mei)
        self.page_number.observe(render_mei, names="value")
        self.zoom_out_btn.on_click(
            lambda _: self._apply_zoom(self.current_zoom - self.zoom_step_percent)
        )
        self.zoom_reset_btn.on_click(
            lambda _: self._apply_zoom(self.initial_zoom_percent)
        )
        self.zoom_in_btn.on_click(
            lambda _: self._apply_zoom(self.current_zoom + self.zoom_step_percent)
        )
        display(
            widgets.VBox(
                [
                    self.mei_editor,
                    widgets.HBox(
                        [
                            render_button,
                            self.page_number,
                            zoom_label,
                            self.zoom_out_btn,
                            self.zoom_reset_btn,
                            self.zoom_in_btn,
                        ]
                    ),
                    self.status,
                    self.score_output,
                ]
            )
        )
        render_mei()
        return self


def launch_interactive_mei_renderer(
    mei_text: str | None = None,
    **kwargs,
) -> InteractiveMeiRenderer:
    """Construct and display a Jupyter MEI paste-and-render editor."""
    return InteractiveMeiRenderer(mei_text, **kwargs).display()
