# Demo F: merged overlays across measures, selectable color, optional labels
# - Color: set fill/stroke
# - Merge: on each page, contiguous windows (x2 == next.x1 and same y/height) are joined into one
# - Labels: optional text drawn above each merged overlay box in the same color
import html
import inspect
from collections import defaultdict

# Global debug storage for Demo F rendering

demo_f_last_svgs = {}
demo_f_last_windows_by_page = {}
demo_f_last_merged_by_page = {}
demo_f_last_params = {}

def _demo_f_copy(data):
    """Return a shallow JSON-friendly copy of nested structures."""
    if isinstance(data, dict):
        return {key: _demo_f_copy(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_demo_f_copy(value) for value in data]
    if isinstance(data, tuple):
        return [_demo_f_copy(value) for value in data]
    return data

try:
    # Parameters
    selections = [
        (2.0, 1.5),
        (5.25, 0.75),
    ]
    padding = 14.0
    overlay_fill = "#faad14"   # selectable color
    overlay_stroke = "#d48806"
    overlay_stroke_width = 12.0
    overlay_opacity = 0.54
    labels: list[str | None] = ["Theme A", None]  # optional labels per selection; None = no label
    label_offset = 60.0         # vertical offset above the overlay bbox top
    label_font_size = 220.0
    label_fill_color = "#fff8dc"
    label_stroke_color = overlay_stroke
    label_stroke_width = 8.0

    overlays_by_page, measures_by_page = vrv_measure_inventory(padding=padding)
    if not measures_by_page:
        raise RuntimeError("No measures found in current layout.")

    def _find_measure_bbox(measure_no_int: int):
        for page, labels_nums in measures_by_page.items():
            for idx, label_no in enumerate(labels_nums):
                if label_no == int(measure_no_int):
                    bbox = overlays_by_page.get(page, [])[idx]
                    return page, bbox
        return None

    def _interp_x(bbox: dict, frac: float) -> float:
        x1 = float(bbox['x']); x2 = float(bbox['x'] + bbox['width'])
        return x1 + (x2 - x1) * max(0.0, min(1.0, float(frac)))

    # Build raw windows per page from selections
    windows_by_page: dict[int, list[tuple[float, float, float, float, str | None, int]]] = {}

    for sel_index, (start_float, length_float) in enumerate(selections):
        label_text = labels[sel_index] if sel_index < len(labels) else None
        start_int = int(start_float); start_frac = float(start_float - start_int)
        end_float = start_float + float(length_float)
        end_int = int(end_float); end_frac = float(end_float - end_int)

        if start_frac < 1e-9:
            current = start_int
            while True:
                loc = _find_measure_bbox(current)
                if not loc:
                    break
                page, bbox = loc
                x1 = float(bbox['x']); x2 = float(bbox['x'] + bbox['width'])
                y = float(bbox['y']); h = float(bbox['height'])
                if current == end_int and end_frac > 1e-6:
                    x2 = _interp_x(bbox, end_frac)
                windows_by_page.setdefault(page, []).append((x1, y, x2 - x1, h, label_text, sel_index))
                if current >= end_int:
                    break
                current += 1
        else:
            loc = _find_measure_bbox(start_int)
            if not loc:
                continue
            page, bbox = loc
            x1 = _interp_x(bbox, start_frac)
            x2 = float(bbox['x'] + bbox['width'])
            y = float(bbox['y']); h = float(bbox['height'])
            if end_int == start_int:
                x2 = _interp_x(bbox, end_frac) if end_frac > 1e-6 else x2
                windows_by_page.setdefault(page, []).append((x1, y, x2 - x1, h, label_text, sel_index))
            else:
                windows_by_page.setdefault(page, []).append((x1, y, x2 - x1, h, label_text, sel_index))
                current = start_int + 1
                while current < end_int:
                    loc2 = _find_measure_bbox(current)
                    if not loc2:
                        break
                    page2, bbox2 = loc2
                    x1m = float(bbox2['x']); x2m = float(bbox2['x'] + bbox2['width'])
                    ym = float(bbox2['y']); hm = float(bbox2['height'])
                    windows_by_page.setdefault(page2, []).append((x1m, ym, x2m - x1m, hm, label_text, sel_index))
                    current += 1
                end_loc = _find_measure_bbox(end_int)
                if end_loc:
                    page3, bbox3 = end_loc
                    x1e = float(bbox3['x'])
                    x2e = _interp_x(bbox3, end_frac) if end_frac > 1e-6 else float(bbox3['x'] + bbox3['width'])
                    ye = float(bbox3['y']); he = float(bbox3['height'])
                    windows_by_page.setdefault(page3, []).append((x1e, ye, x2e - x1e, he, label_text, sel_index))

    # Merge contiguous windows per page by selection
    overlays_by_page: dict[int, list[tuple[float, float, float, float, str | None, int]]] = {}
    for page, wins in windows_by_page.items():
        if not wins:
            continue
        grouped: defaultdict[int, list[tuple[float, float, float, float, str | None]]] = defaultdict(list)
        for x, y, w, h, label_text, sel_id in wins:
            grouped[sel_id].append((x, y, w, h, label_text))
        overlays: list[tuple[float, float, float, float, str | None, int]] = []
        for sel_id, segments in grouped.items():
            min_x = min(seg[0] for seg in segments)
            min_y = min(seg[1] for seg in segments)
            max_x = max(seg[0] + seg[2] for seg in segments)
            max_y = max(seg[1] + seg[3] for seg in segments)
            label_text = next((seg[4] for seg in segments if seg[4]), None)
            overlays.append((min_x, min_y, max_x - min_x, max_y - min_y, label_text, sel_id))
        overlays.sort(key=lambda item: (item[0], item[1]))
        overlays_by_page[page] = overlays

    overlay_sig = inspect.signature(vrv_apply_measure_overlays_inline)
    supports_stroke_width = 'stroke_width' in overlay_sig.parameters

    demo_f_last_windows_by_page = _demo_f_copy(windows_by_page)
    demo_f_last_merged_by_page = _demo_f_copy(overlays_by_page)
    demo_f_last_params = {
        "selections": selections,
        "padding": padding,
        "overlay_fill": overlay_fill,
        "overlay_stroke": overlay_stroke,
        "overlay_stroke_width": overlay_stroke_width,
        "overlay_opacity": overlay_opacity,
        "labels": labels,
        "label_offset": label_offset,
        "label_font_size": label_font_size,
        "label_fill_color": label_fill_color,
        "label_stroke_color": label_stroke_color,
        "label_stroke_width": label_stroke_width,
        "supports_stroke_width": supports_stroke_width,
    }

    # Render overlays and labels
    page_total = _vrv_toolkit.getPageCount()
    for page in range(1, page_total + 1):
        svg_page = _vrv_toolkit.renderToSVG(page)
        svg_page = inject_css(svg_page)
        rects = [
            {'x': x, 'y': y, 'width': w, 'height': h}
            for (x, y, w, h, _label_text, _sel_id) in overlays_by_page.get(page, [])
        ]

        overlay_kwargs = dict(fill=overlay_fill, opacity=overlay_opacity, stroke=overlay_stroke)
        if supports_stroke_width:
            overlay_kwargs['stroke_width'] = overlay_stroke_width
        svg_page = vrv_apply_measure_overlays_inline(svg_page, rects, **overlay_kwargs)

        overlays_for_page = overlays_by_page.get(page, [])
        svg_text = svg_page.decode('utf-8') if isinstance(svg_page, (bytes, bytearray)) else str(svg_page)
        final_svg = svg_text
        if overlays_for_page:
            outer_close = svg_text.rfind('</svg>')
            insert_pos = svg_text.rfind('</svg>', 0, outer_close) if outer_close != -1 else -1
            if insert_pos == -1:
                insert_pos = outer_close
            if insert_pos != -1:
                texts: list[str] = []
                for (x, y, w, h, label_text, _sel_id) in overlays_for_page:
                    if not label_text:
                        continue
                    tx = x + w / 2.0
                    ty = max(0.0, y - label_offset)
                    label = html.escape(label_text)
                    texts.append(
                        (
                            f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="middle" '
                            f'style="fill:{label_fill_color};stroke:{label_stroke_color};stroke-width:{label_stroke_width:.1f};'
                            f'paint-order:stroke fill;font-size:{label_font_size:.1f};font-family:sans-serif;'
                            'dominant-baseline:middle;pointer-events:none;vector-effect:non-scaling-stroke">'
                            f'{label}</text>'
                        )
                    )
                if texts:
                    final_svg = svg_text[:insert_pos] + "\n" + "\n".join(texts) + "\n" + svg_text[insert_pos:]
        demo_f_last_svgs[page] = final_svg
        vrv_display_svg(final_svg)

except Exception as exc:
    print(f"Demo F failed: {exc}")
