"""Offline graphic/geometry checks; HTTP connectivity is an explicit opt-in."""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import Request, urlopen

from .mei_references import resolve_pointer

MEI = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def image_resource_rows(files, *, check_network: bool = False, timeout: float = 10,
                        network_only: bool = False) -> dict:
    """Check supplied graphics, or just HTTP targets for the network pass.

    A requested network-only pass without HTTP targets is not applicable;
    local decoding and geometry remain the separate offline pass's work.
    """
    if network_only and not check_network:
        raise ValueError("network_only requires check_network=True")
    if not network_only:
        from PIL import Image

    rows, resources = [], []
    graphics_found = 0
    file_network_counts = []
    for path in map(Path, files):
        root = ET.parse(path).getroot()
        parents = {child: parent for parent in root.iter() for child in parent}
        http_targets = 0

        def add(element, check, message, *, severity="error", actual=""):
            rows.append({"severity": severity, "category": "resources", "origin": "CAMAT resources",
                         "check": check, "file": str(path.resolve()), "xml_id": element.get(XML_ID, ""),
                         "element": element.tag.rsplit("}", 1)[-1], "message": message, "actual": actual})

        def bounds(element):
            names = ("ulx", "uly", "lrx", "lry")
            if not all(element.get(name) is not None for name in names):
                return None  # Polygon zones and undeclared coordinate spaces are valid.
            try:
                values = tuple(float(element.get(name)) for name in names)
                if not all(math.isfinite(v) for v in values) or values[2] <= values[0] or values[3] <= values[1]:
                    raise ValueError
                return values
            except ValueError:
                add(element, "coordinate_bounds", "Declared rectangle must have finite coordinates and positive area.")
                return None

        for surface in root.iter(f"{{{MEI}}}surface"):
            surface_bounds = None if network_only else bounds(surface)
            for zone in (() if network_only else surface.iter(f"{{{MEI}}}zone")):
                zone_bounds = bounds(zone)
                if zone_bounds and surface_bounds:
                    u, v, x, y = zone_bounds
                    a, b, c, d = surface_bounds
                    if u < a or v < b or x > c or y > d:
                        add(zone, "zone_surface_bounds", "Zone extends outside the declared surface coordinate space.",
                            actual=str(zone_bounds))
            # Multiple graphics and different resolutions are allowed. Do not
            # compare zone coordinates against a guessed first graphic's pixels.
            for graphic in surface.iter(f"{{{MEI}}}graphic"):
                graphics_found += 1
                target = graphic.get("target", "")
                if not target:
                    if not network_only:
                        add(graphic, "graphic_target", "Supplied graphic has no target.")
                    continue
                pointer = resolve_pointer(target, graphic, path, parents)
                resource = {"file": str(path.resolve()), "target": target, "resolved_uri": pointer.uri,
                            "kind": "local" if pointer.document else "remote", "status": "skipped"}
                resources.append(resource)
                if pointer.document:
                    if network_only:
                        resource.update(status="not-applicable", reason="Local image; checked by the offline resources pass.")
                        continue
                    try:
                        if pointer.document.suffix.lower() == ".svg":
                            svg = ET.parse(pointer.document).getroot()
                            if svg.tag != "{http://www.w3.org/2000/svg}svg":
                                raise ValueError("not an SVG document")
                            size = None
                        else:
                            with Image.open(pointer.document) as image:
                                size = image.size
                                image.verify()
                        resource.update(status="passed", dimensions=size)
                        if size:
                            for attr, expected in zip(("width", "height"), size):
                                raw = graphic.get(attr, "")
                                if re.fullmatch(r"\d+(?:\.\d+)?(?:px)?", raw) and float(raw.removesuffix("px")) != expected:
                                    add(graphic, "graphic_dimensions", f"Declared {attr} disagrees with the local image.",
                                        severity="warning", actual=f"declared={raw}, image={expected}")
                    except (OSError, ValueError, ET.ParseError) as exc:
                        resource.update(status="failed", message=str(exc))
                        add(graphic, "local_graphic", f"Local graphic is missing or cannot be decoded: {exc}", actual=target)
                elif pointer.uri.startswith(("http://", "https://")) and check_network:
                    http_targets += 1
                    try:
                        request = Request(pointer.uri, method="HEAD", headers={"User-Agent": "CAMAT-validation"})
                        with urlopen(request, timeout=timeout) as response:
                            content_type = response.headers.get("Content-Type", "").split(";")[0]
                            resource.update(status="passed", content_type=content_type)
                            if content_type and not content_type.startswith("image/"):
                                resource.update(status="failed")
                                add(graphic, "graphic_http_content_type", "Remote target did not identify itself as an image.",
                                    severity="warning", actual=content_type)
                    except Exception as exc:
                        resource.update(status="execution-error", message=str(exc))
                        add(graphic, "graphic_connectivity", f"Image connectivity could not be established: {exc}",
                            severity="warning", actual=target)
                else:
                    resource["reason"] = "Remote resource access was not requested or URI scheme is unsupported."
                    if network_only:
                        resource.update(status="not-applicable", reason="URI scheme is not HTTP(S).")
        file_network_counts.append({"file": str(path.resolve()), "http_targets": http_targets})
    result = {"rows": rows, "resources": resources}
    if network_only:
        http_targets = sum(item["http_targets"] for item in file_network_counts)
        result.update(applicable=http_targets > 0, graphics_found=graphics_found,
                      images_linked=len(resources), http_targets=http_targets,
                      requests_attempted=http_targets, files=file_network_counts)
        if not http_targets:
            if not resources:
                reason = "No images are linked; there are no graphic targets to test."
            elif all(item["kind"] == "local" for item in resources):
                reason = "Only local images are linked; the offline resources pass checks them. No HTTP(S) image URLs to test."
            else:
                reason = "No HTTP(S) image URLs are linked; the supplied URI schemes are outside this network check."
            result["reason"] = reason
    return result
