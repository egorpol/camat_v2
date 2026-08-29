#!/usr/bin/env python3
"""
Upload page images to the Edirom measure detector and integrate the resulting
measure annotations into matching MEI files.

The detector at https://measure-detector.edirom.de/upload is a neural-network
service (DOMD: Detecting Objects in Music Documents). It does not parse the
MEI. It looks at the facsimile picture, returns bounding boxes for detected
measures, and this module writes those boxes as MEI ``<zone type="measure">``
elements with matching measure ``@facs`` links.

Examples:
    camat-integrate-annotations \
        Demo \
        --reuse-annotations

    camat-integrate-annotations \
        DdT_1/01_scheidt_tabulatura_nova_bsb00023110

By default this script expects:
    - MEI files directly inside SCORE_DIR
    - matching images inside SCORE_DIR/img with the same stem as the MEI file
    - annotations written as SCORE_DIR/<stem>_measure_annotations.xml
    - integrated outputs written as SCORE_DIR/<stem>_facs_zones.mei
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import struct
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from tqdm.auto import tqdm

from .facsimile_downloader import resolve_iiif_image_url
from .integrate_measure_annotations import (
    get_body_measures,
    integrate_annotation_file,
    parse_mei,
)
from .page_filter import filter_mei_files

DETECTOR_URL = "https://measure-detector.edirom.de/upload"
IIIF_IMAGE_URL_TEMPLATE = (
    "https://api.digitale-sammlungen.de/iiif/image/v2/{stem}/full/{width},/0/default.jpg"
)
MEI_NS = "http://www.music-encoding.org/ns/mei"
MEI = f"{{{MEI_NS}}}"

ET.register_namespace("", MEI_NS)


class RunLogger:
    def __init__(self, log_path: Path | None = None) -> None:
        self.log_path = log_path
        self._handle = log_path.open("w", encoding="utf-8") if log_path else None

    def write(self, message: str) -> None:
        tqdm.write(message)
        if self._handle is not None:
            self._handle.write(message + "\n")
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


LOGGER = RunLogger()


def log(message: str) -> None:
    LOGGER.write(message)


class SkipFile(Exception):
    pass


def read_png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        signature = handle.read(24)
    if signature[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a valid PNG file.")
    width, height = struct.unpack(">II", signature[16:24])
    return width, height


def read_jpeg_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise ValueError(f"{path} is not a valid JPEG file.")
        while True:
            marker_prefix = handle.read(1)
            if not marker_prefix:
                break
            if marker_prefix != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                block_size = struct.unpack(">H", handle.read(2))[0]
                _precision = handle.read(1)
                height, width = struct.unpack(">HH", handle.read(4))
                if block_size < 7:
                    raise ValueError(f"{path} has an invalid JPEG SOF segment.")
                return width, height
            if marker in {b"\xd8", b"\xd9"}:
                continue
            block_size_raw = handle.read(2)
            if len(block_size_raw) != 2:
                break
            block_size = struct.unpack(">H", block_size_raw)[0]
            handle.seek(block_size - 2, 1)
    raise ValueError(f"Could not determine JPEG size for {path}.")


def read_image_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return read_png_size(path)
    if header.startswith(b"\xff\xd8"):
        return read_jpeg_size(path)
    raise ValueError(f"Unsupported image format for {path}")


def get_upload_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


def build_annotation_tree(
    detector_payload: dict,
    image_name: str,
    image_width: int,
    image_height: int,
) -> ET.ElementTree:
    measures = detector_payload.get("measures")
    if not isinstance(measures, list) or not measures:
        raise ValueError("Detector response did not include a non-empty 'measures' list.")

    root = ET.Element(MEI + "mei")

    mei_head = ET.SubElement(root, MEI + "meiHead")
    file_desc = ET.SubElement(mei_head, MEI + "fileDesc")
    title_stmt = ET.SubElement(file_desc, MEI + "titleStmt")
    ET.SubElement(title_stmt, MEI + "title")
    ET.SubElement(file_desc, MEI + "pubStmt")

    encoding_desc = ET.SubElement(mei_head, MEI + "encodingDesc")
    app_info = ET.SubElement(encoding_desc, MEI + "appInfo")
    application = ET.SubElement(
        app_info,
        MEI + "application",
        isodate=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        version="api-upload",
    )
    ET.SubElement(application, MEI + "name").text = "Deep Optical Measure Detector"
    ET.SubElement(application, MEI + "p").text = (
        "Measures detected with Deep Optical Measure Detector"
    )

    music = ET.SubElement(root, MEI + "music")
    facsimile = ET.SubElement(music, MEI + "facsimile")

    token = uuid.uuid4().hex[:12]
    surface = ET.SubElement(
        facsimile,
        MEI + "surface",
        {
            "{http://www.w3.org/XML/1998/namespace}id": f"surface_{token}",
            "n": "1",
            "ulx": "0",
            "uly": "0",
            "lrx": str(max(image_width - 1, 0)),
            "lry": str(max(image_height - 1, 0)),
        },
    )
    ET.SubElement(
        surface,
        MEI + "graphic",
        {
            "{http://www.w3.org/XML/1998/namespace}id": f"graphic_{token}",
            "target": image_name,
            "width": str(image_width),
            "height": str(image_height),
        },
    )

    body = ET.SubElement(music, MEI + "body")
    mdiv = ET.SubElement(
        body,
        MEI + "mdiv",
        {
            "{http://www.w3.org/XML/1998/namespace}id": f"mdiv_{token}",
            "n": "1",
            "label": "",
        },
    )
    score = ET.SubElement(mdiv, MEI + "score")
    ET.SubElement(score, MEI + "scoreDef")
    section = ET.SubElement(score, MEI + "section")
    ET.SubElement(section, MEI + "pb")

    for index, measure in enumerate(measures, start=1):
        zone_id = f"zone_{uuid.uuid4().hex[:18]}"
        ET.SubElement(
            surface,
            MEI + "zone",
            {
                "{http://www.w3.org/XML/1998/namespace}id": zone_id,
                "type": "measure",
                "ulx": str(round(measure["ulx"])),
                "uly": str(round(measure["uly"])),
                "lrx": str(round(measure["lrx"])),
                "lry": str(round(measure["lry"])),
            },
        )
        ET.SubElement(
            section,
            MEI + "measure",
            {
                "{http://www.w3.org/XML/1998/namespace}id": f"measure_{uuid.uuid4().hex[:18]}",
                "n": str(index),
                "label": str(index),
                "facs": f"#{zone_id}",
            },
        )

    ET.SubElement(section, MEI + "pb")
    return ET.ElementTree(root)


def describe_http_error(error: requests.HTTPError) -> str:
    response = error.response
    if response is None:
        return str(error)
    body = (response.text or "").strip().replace("\n", " ")
    if body:
        body = body[:300]
        return f"HTTP {response.status_code} from detector: {body}"
    return f"HTTP {response.status_code} from detector with empty response body"


def upload_image(
    path: Path,
    detector_url: str,
    timeout: int,
    *,
    retries: int,
    retry_delay: float,
) -> dict:
    mime_type = get_upload_mime_type(path)
    last_error: Exception | None = None

    for attempt in range(1, retries + 2):
        try:
            with path.open("rb") as handle:
                response = requests.post(
                    detector_url,
                    files={"image": (path.name, handle, mime_type)},
                    timeout=timeout,
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Detector response was not a JSON object.")
            return payload
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code is None or status_code < 500 or attempt > retries:
                raise RuntimeError(describe_http_error(exc)) from exc
            log(
                f"  detector returned HTTP {status_code}; retrying "
                f"({attempt}/{retries}) after {retry_delay:.1f}s"
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt > retries:
                raise RuntimeError(f"Detector request failed: {exc}") from exc
            log(
                f"  detector request failed; retrying "
                f"({attempt}/{retries}) after {retry_delay:.1f}s"
            )

        time.sleep(retry_delay)

    if last_error is not None:
        raise RuntimeError(f"Detector request failed: {last_error}") from last_error
    raise RuntimeError("Detector request failed for an unknown reason.")


def find_image_for_mei(mei_path: Path, image_dir: Path, extensions: list[str]) -> Path:
    candidates = []
    for extension in extensions:
        normalized = extension if extension.startswith(".") else f".{extension}"
        candidates.extend(image_dir.rglob(f"{mei_path.stem}{normalized}"))
        candidates.extend(image_dir.rglob(f"{mei_path.stem}{normalized.upper()}"))

    if not candidates:
        for extension in extensions:
            normalized = extension if extension.startswith(".") else f".{extension}"
            candidates.extend(image_dir.rglob(f"*{mei_path.stem}*{normalized}"))
            candidates.extend(image_dir.rglob(f"*{mei_path.stem}*{normalized.upper()}"))

    unique_candidates = sorted({candidate.resolve() for candidate in candidates})
    if not unique_candidates:
        raise FileNotFoundError(
            f"No image found for {mei_path.name} in {image_dir} with extensions {extensions}."
        )
    if len(unique_candidates) > 1:
        matches = ", ".join(str(path) for path in unique_candidates)
        raise RuntimeError(f"Found multiple candidate images for {mei_path.name}: {matches}")
    return unique_candidates[0]


def get_annotation_graphic_size(annotation_path: Path) -> tuple[int, int]:
    root = parse_mei(str(annotation_path)).getroot()
    graphic = root.find(".//m:facsimile//m:graphic", {"m": MEI_NS})
    if graphic is None:
        raise RuntimeError(f"No <graphic> found in annotations file {annotation_path}")
    width = graphic.get("width")
    height = graphic.get("height")
    if not width or not height:
        raise RuntimeError(f"Annotation graphic in {annotation_path} is missing @width/@height")
    return int(width), int(height)


def build_graphic_target(
    *,
    mei_path: Path,
    annotation_path: Path,
    image_path: Path | None,
    graphic_target_mode: str,
    iiif_url_template: str,
    graphic_target: str | None = None,
    iiif_stem: str | None = None,
) -> str | None:
    if graphic_target_mode == "local":
        return None
    if graphic_target_mode != "iiif":
        raise ValueError(f"Unsupported graphic target mode: {graphic_target_mode}")

    if image_path is not None:
        width, _height = read_image_size(image_path)
    else:
        width, _height = get_annotation_graphic_size(annotation_path)

    return resolve_iiif_image_url(
        stem=iiif_stem or mei_path.stem,
        width=width,
        image_url=graphic_target,
        template=iiif_url_template,
    )


def process_mei_file(
    mei_path: Path,
    *,
    image_dir: Path,
    detector_url: str,
    timeout: int,
    retries: int,
    retry_delay: float,
    minimum_measures: int,
    max_measure_mismatch: int | None,
    annotation_suffix: str,
    output_suffix: str,
    reuse_annotations: bool,
    overwrite: bool,
    graphic_target_mode: str,
    iiif_url_template: str,
    graphic_target: str | None = None,
    iiif_stem: str | None = None,
) -> tuple[Path, Path]:
    annotation_path = mei_path.with_name(f"{mei_path.stem}{annotation_suffix}")
    output_path = mei_path.with_name(f"{mei_path.stem}{output_suffix}.mei")
    measure_count = len(get_body_measures(parse_mei(str(mei_path)).getroot()))
    image_path: Path | None = None

    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}")

    if measure_count < minimum_measures:
        raise SkipFile(
            f"{mei_path.name} has only {measure_count} measure(s), below "
            f"--minimum-measures={minimum_measures}"
        )

    if annotation_path.exists() and reuse_annotations:
        log(f"  reusing annotations: {annotation_path.name}")
    else:
        if annotation_path.exists() and not overwrite:
            raise FileExistsError(
                f"Annotations already exist: {annotation_path}. "
                "Use --reuse-annotations or --overwrite."
            )
        image_path = find_image_for_mei(mei_path, image_dir, [".jpg", ".jpeg", ".png"])
        log(f"  uploading image: {image_path.name}")
        payload = upload_image(
            image_path,
            detector_url=detector_url,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
        )
        image_width, image_height = read_image_size(image_path)
        annotation_tree = build_annotation_tree(
            payload,
            image_name=image_path.name,
            image_width=image_width,
            image_height=image_height,
        )
        if hasattr(ET, "indent"):
            ET.indent(annotation_tree, space="    ")
        annotation_tree.write(str(annotation_path), encoding="UTF-8", xml_declaration=True)
        log(f"  wrote annotations: {annotation_path.name}")

    graphic_target_override = build_graphic_target(
        mei_path=mei_path,
        annotation_path=annotation_path,
        image_path=image_path,
        graphic_target_mode=graphic_target_mode,
        iiif_url_template=iiif_url_template,
        graphic_target=graphic_target,
        iiif_stem=iiif_stem,
    )

    integrate_annotation_file(
        str(mei_path),
        str(annotation_path),
        str(output_path),
        max_measure_mismatch=max_measure_mismatch,
        graphic_target_prefix="img/",
        graphic_target_override=graphic_target_override,
    )
    log(f"  wrote integrated MEI: {output_path.name}")
    return annotation_path, output_path


def iter_mei_files(score_dir: Path, output_suffix: str) -> list[Path]:
    mei_files = sorted(
        path
        for path in score_dir.glob("*.mei")
        if path.is_file() and not path.stem.endswith(output_suffix)
    )
    if not mei_files:
        raise FileNotFoundError(f"No .mei files found in {score_dir}")
    return mei_files


def write_json_report(report_path: Path, report: dict) -> None:
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score_dir", help="Directory containing .mei files and an img/ subdirectory")
    parser.add_argument(
        "--image-dir",
        help="Directory containing page images (default: SCORE_DIR/img)",
    )
    parser.add_argument(
        "--detector-url",
        default=DETECTOR_URL,
        help=f"DOMD upload endpoint (default: {DETECTOR_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds for the upload request",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of retries after the initial detector upload attempt for 5xx/network failures",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="Seconds to wait between detector upload retries",
    )
    parser.add_argument(
        "--minimum-measures",
        type=int,
        default=0,
        help="Skip pages whose source MEI has fewer measures than this threshold",
    )
    parser.add_argument(
        "--max-measure-mismatch",
        type=int,
        default=0,
        help="Maximum number of unmatched measure numbers allowed during integration",
    )
    parser.add_argument(
        "--annotation-suffix",
        default="_measure_annotations.xml",
        help='Suffix used for saved annotations (default: "_measure_annotations.xml")',
    )
    parser.add_argument(
        "--output-suffix",
        default="_facs_zones",
        help='Suffix used for integrated MEI outputs before ".mei" (default: "_facs_zones")',
    )
    parser.add_argument(
        "--reuse-annotations",
        action="store_true",
        help="Reuse existing annotation XML files instead of uploading again",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing integrated outputs",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow any amount of source-vs-annotation measure mismatch",
    )
    parser.add_argument(
        "--graphic-target-mode",
        choices=["local", "iiif"],
        default="local",
        help="How to write <graphic @target> into the integrated MEI",
    )
    parser.add_argument(
        "--iiif-url-template",
        default=IIIF_IMAGE_URL_TEMPLATE,
        help="Template used when --graphic-target-mode iiif is selected",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately when a file fails instead of continuing with the rest",
    )
    parser.add_argument(
        "--pages",
        help='Only process these page numbers/ranges, e.g. "30-" or "30-120,130"',
    )
    parser.add_argument(
        "--skip-pages",
        help='Skip these page numbers/ranges, e.g. "1-29" for preface pages',
    )
    return parser


def main(argv=None) -> int:
    global LOGGER
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    score_dir = Path(args.score_dir).resolve()
    image_dir = Path(args.image_dir).resolve() if args.image_dir else score_dir / "img"

    if not score_dir.is_dir():
        parser.error(f"Score directory does not exist: {score_dir}")
    if not image_dir.is_dir() and not args.reuse_annotations:
        parser.error(f"Image directory does not exist: {image_dir}")
    if args.minimum_measures < 0:
        parser.error("--minimum-measures must be >= 0")
    if args.max_measure_mismatch < 0:
        parser.error("--max-measure-mismatch must be >= 0")

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = score_dir / f"measure_annotation_run_{timestamp}.log"
    report_path = score_dir / f"measure_annotation_run_{timestamp}.json"
    LOGGER = RunLogger(log_path)

    failures: list[tuple[Path, str]] = []
    skipped: list[tuple[Path, str]] = []
    succeeded: list[dict[str, str]] = []
    processed = 0
    aborted = False
    interrupted_file: Path | None = None

    try:
        mei_files = filter_mei_files(
            iter_mei_files(score_dir, args.output_suffix),
            pages=args.pages,
            skip_pages=args.skip_pages,
        )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        log(f"Run log: {log_path}")
        log(f"Run report: {report_path}")

        try:
            for mei_path in tqdm(mei_files, desc="Processing MEI files", unit="file"):
                interrupted_file = mei_path
                log(f"Processing {mei_path.name}")
                try:
                    annotation_path, output_path = process_mei_file(
                        mei_path,
                        image_dir=image_dir,
                        detector_url=args.detector_url,
                        timeout=args.timeout,
                        retries=args.retries,
                        retry_delay=args.retry_delay,
                        minimum_measures=args.minimum_measures,
                        max_measure_mismatch=None if args.force else args.max_measure_mismatch,
                        annotation_suffix=args.annotation_suffix,
                        output_suffix=args.output_suffix,
                        reuse_annotations=args.reuse_annotations,
                        overwrite=args.overwrite,
                        graphic_target_mode=args.graphic_target_mode,
                        iiif_url_template=args.iiif_url_template,
                    )
                    processed += 1
                    succeeded.append(
                        {
                            "file": mei_path.name,
                            "annotation_file": annotation_path.name,
                            "output_file": output_path.name,
                        }
                    )
                except SkipFile as exc:
                    skipped.append((mei_path, str(exc)))
                    log(f"  skipped: {exc}")
                except Exception as exc:
                    failures.append((mei_path, str(exc)))
                    log(f"  ERROR: {exc}")
                    if args.stop_on_error:
                        break
        except KeyboardInterrupt:
            aborted = True
            if interrupted_file is not None:
                log(f"Interrupted while processing {interrupted_file.name}")
            else:
                log("Interrupted before processing began")

        log(
            f"Finished: processed={processed}, skipped={len(skipped)}, failed={len(failures)}, "
            f"aborted={aborted}, score_dir={score_dir}"
        )
        for mei_path, message in skipped:
            log(f"  skipped {mei_path.name}: {message}")
        for mei_path, message in failures:
            log(f"  failed {mei_path.name}: {message}")

        report = {
            "timestamp": timestamp,
            "score_dir": str(score_dir),
            "image_dir": str(image_dir),
            "settings": {
                "detector_url": args.detector_url,
                "timeout": args.timeout,
                "retries": args.retries,
                "retry_delay": args.retry_delay,
                "minimum_measures": args.minimum_measures,
                "max_measure_mismatch": args.max_measure_mismatch,
                "annotation_suffix": args.annotation_suffix,
                "output_suffix": args.output_suffix,
                "reuse_annotations": args.reuse_annotations,
                "overwrite": args.overwrite,
                "force": args.force,
                "graphic_target_mode": args.graphic_target_mode,
                "iiif_url_template": args.iiif_url_template,
                "stop_on_error": args.stop_on_error,
                "pages": args.pages,
                "skip_pages": args.skip_pages,
            },
            "counts": {
                "total_mei_files": len(mei_files),
                "processed": processed,
                "skipped": len(skipped),
                "failed": len(failures),
            },
            "aborted": aborted,
            "interrupted_file": interrupted_file.name if aborted and interrupted_file else None,
            "processed_files": succeeded,
            "skipped_files": [
                {"file": mei_path.name, "reason": message}
                for mei_path, message in skipped
            ],
            "failed_files": [
                {"file": mei_path.name, "reason": message}
                for mei_path, message in failures
            ],
        }
        write_json_report(report_path, report)
        return 130 if aborted else 1 if failures else 0
    finally:
        LOGGER.close()


if __name__ == "__main__":
    raise SystemExit(main())
