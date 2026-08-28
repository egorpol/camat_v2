#!/usr/bin/env python3
"""
Download BSB IIIF facsimile JPEGs for a score directory of page-level MEI files.

Examples:
    camat-facsimile-download \
        DdT_1/02_hassler_werke_erster_band_cantiones_sacrae_bsb00023111

    camat-facsimile-download \
        DdT_1/02_hassler_werke_erster_band_cantiones_sacrae_bsb00023111 \
        --target-dpi 500

    camat-facsimile-download \
        DdT_1/02_hassler_werke_erster_band_cantiones_sacrae_bsb00023111 \
        --quality-rank 2
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import requests
from tqdm.auto import tqdm

from .page_filter import filter_mei_files

IIIF_IMAGE_TEMPLATE = (
    "https://api.digitale-sammlungen.de/iiif/image/v2/{stem}/full/{width},/0/default.jpg"
)
IIIF_INFO_TEMPLATE = "https://api.digitale-sammlungen.de/iiif/image/v2/{stem}/info.json"


def collect_mei_files(score_dir: Path) -> list[Path]:
    mei_files = sorted(
        path
        for path in score_dir.glob("*.mei")
        if path.is_file() and not path.stem.endswith("_facs_zones")
    )
    if not mei_files:
        raise FileNotFoundError(f"No source .mei files found in {score_dir}")
    return mei_files


def infer_bsb_id(mei_files: list[Path]) -> str:
    first_stem = mei_files[0].stem
    bsb_id = first_stem.rsplit("_", 1)[0]
    if not bsb_id.startswith("bsb"):
        raise ValueError(f"Could not infer a BSB id from {first_stem}")
    return bsb_id


def lookup_bsb_metadata(csv_path: Path, bsb_id: str) -> dict[str, str] | None:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    header_index = None
    for index, row in enumerate(rows):
        normalized = [cell.strip() for cell in row]
        if "ZEND ID" in normalized:
            header_index = index
            headers = normalized
            break

    if header_index is None:
        raise ValueError(f"Could not find a CSV header row containing 'ZEND ID' in {csv_path}")

    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * max(0, len(headers) - len(row))
        record = {key: value.strip() for key, value in zip(headers, padded)}
        if record.get("ZEND ID") == bsb_id:
            return record
    return None


def fetch_sizes(session: requests.Session, stem: str, timeout: int) -> list[dict]:
    response = session.get(IIIF_INFO_TEMPLATE.format(stem=stem), timeout=timeout)
    response.raise_for_status()
    sizes = response.json().get("sizes", [])
    return sorted(sizes, key=lambda size: size["width"], reverse=True)


def pick_width_by_rank(sizes: list[dict], quality_rank: int) -> int:
    if not sizes:
        raise ValueError("IIIF info.json did not return any sizes")
    if quality_rank < 1 or quality_rank > len(sizes):
        raise ValueError(
            f"--quality-rank {quality_rank} is out of range for this volume; "
            f"available ranks: 1-{len(sizes)}"
        )
    return int(sizes[quality_rank - 1]["width"])


def resolve_width_for_stem(
    *,
    session: requests.Session,
    stem: str,
    width: int | None,
    quality_rank: int | None,
    target_dpi: int | None,
    page_width_mm: float,
    timeout: int,
) -> int:
    if width is not None:
        return width
    if quality_rank is not None:
        sizes = fetch_sizes(session, stem, timeout)
        return pick_width_by_rank(sizes, quality_rank)
    if target_dpi is not None:
        return max(1, int(round(target_dpi * page_width_mm / 25.4)))
    raise ValueError("One resolution mode must be selected")


def download_images(
    *,
    mei_files: list[Path],
    output_dir: Path,
    width: int | None,
    quality_rank: int | None,
    target_dpi: int | None,
    page_width_mm: float,
    timeout: int,
    delay: float,
    overwrite: bool,
) -> tuple[int, int, int]:
    downloaded = 0
    skipped = 0
    failed = 0

    output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for mei_path in tqdm(mei_files, desc="Downloading facsimiles", unit="file"):
        stem = mei_path.stem
        out_path = output_dir / f"{stem}.jpg"
        if out_path.exists() and not overwrite:
            skipped += 1
            continue

        try:
            resolved_width = resolve_width_for_stem(
                session=session,
                stem=stem,
                width=width,
                quality_rank=quality_rank,
                target_dpi=target_dpi,
                page_width_mm=page_width_mm,
                timeout=timeout,
            )
            url = IIIF_IMAGE_TEMPLATE.format(stem=stem, width=resolved_width)
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            out_path.write_bytes(response.content)
            downloaded += 1
        except requests.RequestException as exc:
            failed += 1
            tqdm.write(f"ERROR {stem}: {exc}")

        if delay > 0:
            time.sleep(delay)

    return downloaded, skipped, failed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score_dir", help="Directory containing source page-level .mei files")
    parser.add_argument(
        "--output-dir",
        help="Directory to store downloaded images (default: SCORE_DIR/img)",
    )
    resolution = parser.add_mutually_exclusive_group()
    resolution.add_argument(
        "--width",
        type=int,
        help="Explicit IIIF pixel width to request",
    )
    resolution.add_argument(
        "--quality-rank",
        type=int,
        help="Pick width by IIIF size rank from info.json (1=best, 2=second best, ...)",
    )
    resolution.add_argument(
        "--target-dpi",
        type=int,
        default=500,
        help="Compute width from target DPI and --page-width-mm (default: 500). Note: the"
             " resulting DPI is approximate — it assumes all pages have the width given by"
             " --page-width-mm, which may not match the actual physical dimensions of the volume.",
    )
    parser.add_argument(
        "--page-width-mm",
        type=float,
        default=210.0,
        help="Physical page width used with --target-dpi (default: 210.0mm / A4). Adjust this"
             " if the volume's pages are a different size, otherwise the effective DPI will differ"
             " from the target.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between download requests (default: 0.5)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing local image files",
    )
    parser.add_argument(
        "--pages",
        help='Only process these page numbers/ranges, e.g. "30-" or "30-120,130"',
    )
    parser.add_argument(
        "--skip-pages",
        help='Skip these page numbers/ranges, e.g. "1-29" for preface pages',
    )
    parser.add_argument(
        "--id-csv",
        default="metadata/DdT_BSB_IDs.csv",
        help="Optional CSV used to validate the inferred BSB id (default: metadata/DdT_BSB_IDs.csv)",
    )
    return parser


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    score_dir = Path(args.score_dir).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else score_dir / "img"

    if not score_dir.is_dir():
        parser.error(f"Score directory does not exist: {score_dir}")
    if args.width is not None and args.width <= 0:
        parser.error("--width must be > 0")
    if args.quality_rank is not None and args.quality_rank <= 0:
        parser.error("--quality-rank must be > 0")
    if args.target_dpi is not None and args.target_dpi <= 0:
        parser.error("--target-dpi must be > 0")
    if args.page_width_mm <= 0:
        parser.error("--page-width-mm must be > 0")
    if args.delay < 0:
        parser.error("--delay must be >= 0")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    all_mei_files = collect_mei_files(score_dir)
    bsb_id = infer_bsb_id(all_mei_files)
    try:
        mei_files = filter_mei_files(all_mei_files, pages=args.pages, skip_pages=args.skip_pages)
    except ValueError as exc:
        parser.error(str(exc))
    csv_path = Path(args.id_csv).resolve()

    if csv_path.is_file():
        metadata = lookup_bsb_metadata(csv_path, bsb_id)
        if metadata is None:
            parser.error(
                f"Could not find inferred BSB id {bsb_id} in {csv_path}. "
                "Check the score directory and filename stems."
            )
        print(
            f"Volume check: {bsb_id} "
            f"(DdT Folge={metadata.get('DdT Folge', '')}, "
            f"BV-Nummer={metadata.get('BV-Nummer', '')})"
        )
    else:
        print(f"Volume check skipped: CSV not found at {csv_path}")

    mode = (
        f"width={args.width}"
        if args.width is not None
        else f"quality-rank={args.quality_rank}"
        if args.quality_rank is not None
        else f"target-dpi={args.target_dpi}"
    )
    print(
        f"Found {len(all_mei_files)} source .mei files in {score_dir}; "
        f"selected {len(mei_files)} after page filters"
    )
    print(f"Downloading facsimiles to {output_dir} using {mode}")

    downloaded, skipped, failed = download_images(
        mei_files=mei_files,
        output_dir=output_dir,
        width=args.width,
        quality_rank=args.quality_rank,
        target_dpi=args.target_dpi,
        page_width_mm=args.page_width_mm,
        timeout=args.timeout,
        delay=args.delay,
        overwrite=args.overwrite,
    )

    print(
        f"Finished: downloaded={downloaded}, skipped={skipped}, failed={failed}, "
        f"output_dir={output_dir}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
