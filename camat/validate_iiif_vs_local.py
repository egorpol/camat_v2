#!/usr/bin/env python3
"""
Validate that local facsimile images are byte-identical to the BSB IIIF URLs implied by
their page stems and widths.

Examples:
    camat-validate-iiif \
        DdT_1/02_hassler_werke_erster_band_cantiones_sacrae_bsb00023111

    camat-validate-iiif \
        DdT_1/02_hassler_werke_erster_band_cantiones_sacrae_bsb00023111 \
        --check-output-mei
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from tqdm.auto import tqdm

from .page_filter import filter_mei_files

IIIF_IMAGE_URL_TEMPLATE = (
    "https://api.digitale-sammlungen.de/iiif/image/v2/{stem}/full/{width},/0/default.jpg"
)
MEI_NS = "http://www.music-encoding.org/ns/mei"


class RunLogger:
    def __init__(self, log_path: Path) -> None:
        self._handle = log_path.open("w", encoding="utf-8")

    def write(self, message: str) -> None:
        tqdm.write(message)
        self._handle.write(message + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


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
            if marker in {
                b"\xc0",
                b"\xc1",
                b"\xc2",
                b"\xc3",
                b"\xc5",
                b"\xc6",
                b"\xc7",
                b"\xc9",
                b"\xca",
                b"\xcb",
                b"\xcd",
                b"\xce",
                b"\xcf",
            }:
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_mei_files(score_dir: Path, output_suffix: str) -> list[Path]:
    mei_files = sorted(
        path
        for path in score_dir.glob("*.mei")
        if path.is_file() and not path.stem.endswith(output_suffix)
    )
    if not mei_files:
        raise FileNotFoundError(f"No source .mei files found in {score_dir}")
    return mei_files


def find_image_for_stem(image_dir: Path, stem: str) -> Path:
    candidates = []
    for pattern in (f"{stem}.jpg", f"{stem}.jpeg", f"{stem}.png"):
        candidates.extend(candidate for candidate in image_dir.rglob(pattern) if candidate.is_file())
    if not candidates:
        for pattern in (f"*{stem}*.jpg", f"*{stem}*.jpeg", f"*{stem}*.png"):
            candidates.extend(
                candidate for candidate in image_dir.rglob(pattern) if candidate.is_file()
            )
    candidates = sorted({candidate.resolve() for candidate in candidates})
    if not candidates:
        raise FileNotFoundError(f"No local image found for {stem} in {image_dir}")
    if len(candidates) > 1:
        matches = ", ".join(str(candidate) for candidate in candidates)
        raise RuntimeError(f"Multiple local images found for {stem}: {matches}")
    return candidates[0]


def parse_graphic_from_output_mei(output_mei: Path) -> tuple[str | None, int | None, int | None]:
    root = ET.parse(output_mei).getroot()
    graphic = root.find(f".//{{{MEI_NS}}}facsimile//{{{MEI_NS}}}graphic")
    if graphic is None:
        raise RuntimeError(f"No <graphic> found in {output_mei}")
    target = graphic.get("target")
    width = graphic.get("width")
    height = graphic.get("height")
    return target, int(width) if width else None, int(height) if height else None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score_dir", help="Directory containing source .mei files")
    parser.add_argument(
        "--image-dir",
        help="Directory containing local facsimile images (default: SCORE_DIR/img)",
    )
    parser.add_argument(
        "--output-suffix",
        default="_facs_zones",
        help='Integrated MEI suffix used when --check-output-mei is enabled (default: "_facs_zones")',
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="HTTP timeout in seconds for remote IIIF fetches (default: 60)",
    )
    parser.add_argument(
        "--check-output-mei",
        action="store_true",
        help="Also verify that integrated *_facs_zones.mei files point to the expected IIIF URL",
    )
    parser.add_argument(
        "--iiif-url-template",
        default=IIIF_IMAGE_URL_TEMPLATE,
        help="Template used to build the expected IIIF URL",
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
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    score_dir = Path(args.score_dir).resolve()
    image_dir = Path(args.image_dir).resolve() if args.image_dir else score_dir / "img"

    if not score_dir.is_dir():
        parser.error(f"Score directory does not exist: {score_dir}")
    if not image_dir.is_dir():
        parser.error(f"Image directory does not exist: {image_dir}")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    try:
        mei_files = filter_mei_files(
            iter_mei_files(score_dir, args.output_suffix),
            pages=args.pages,
            skip_pages=args.skip_pages,
        )
    except ValueError as exc:
        parser.error(str(exc))
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = score_dir / f"iiif_validation_{timestamp}.log"
    report_path = score_dir / f"iiif_validation_{timestamp}.json"
    logger = RunLogger(log_path)

    matched: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    session = requests.Session()

    try:
        logger.write(f"Validation log: {log_path}")
        logger.write(f"Validation report: {report_path}")

        for mei_path in tqdm(mei_files, desc="Validating IIIF vs local", unit="file"):
            stem = mei_path.stem
            try:
                image_path = find_image_for_stem(image_dir, stem)
                width, height = read_image_size(image_path)
                expected_url = args.iiif_url_template.format(stem=stem, width=width)

                local_hash = sha256_file(image_path)
                response = session.get(expected_url, timeout=args.timeout)
                response.raise_for_status()
                remote_hash = sha256_bytes(response.content)
                if local_hash != remote_hash:
                    raise RuntimeError(
                        f"SHA-256 mismatch for {stem}: local={local_hash}, remote={remote_hash}"
                    )

                if args.check_output_mei:
                    output_mei = mei_path.with_name(f"{stem}{args.output_suffix}.mei")
                    if not output_mei.is_file():
                        raise FileNotFoundError(f"Missing integrated output: {output_mei.name}")
                    target, mei_width, mei_height = parse_graphic_from_output_mei(output_mei)
                    if target != expected_url:
                        raise RuntimeError(
                            f"Integrated MEI target mismatch for {output_mei.name}: "
                            f"expected {expected_url}, found {target}"
                        )
                    if mei_width != width or mei_height != height:
                        raise RuntimeError(
                            f"Integrated MEI graphic size mismatch for {output_mei.name}: "
                            f"expected {width}x{height}, found {mei_width}x{mei_height}"
                        )

                matched.append(
                    {
                        "file": mei_path.name,
                        "image_file": image_path.name,
                        "width": str(width),
                        "height": str(height),
                        "iiif_url": expected_url,
                        "sha256": local_hash,
                    }
                )
            except Exception as exc:
                logger.write(f"ERROR {stem}: {exc}")
                failed.append({"file": mei_path.name, "error": str(exc)})

        logger.write(
            f"Finished: matched={len(matched)}, failed={len(failed)}, "
            f"score_dir={score_dir}, image_dir={image_dir}"
        )

        report = {
            "timestamp": timestamp,
            "score_dir": str(score_dir),
            "image_dir": str(image_dir),
            "settings": {
                "timeout": args.timeout,
                "check_output_mei": args.check_output_mei,
                "output_suffix": args.output_suffix,
                "iiif_url_template": args.iiif_url_template,
                "pages": args.pages,
                "skip_pages": args.skip_pages,
            },
            "summary": {
                "total_mei_files": len(mei_files),
                "matched": len(matched),
                "failed": len(failed),
            },
            "matched": matched,
            "failed": failed,
        }
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    finally:
        logger.close()

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
