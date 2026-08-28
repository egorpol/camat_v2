#!/usr/bin/env python3
"""
Compare a local score directory against the BSB IIIF manifest page list.

Example:
    camat-check-bsb-page-coverage \
        DdT_1/29_30_instrumentalkonzerte_deutscher_meister_bsb00023250
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path

import requests

MANIFEST_URL = "https://api.digitale-sammlungen.de/iiif/presentation/v2/{bsb_id}/manifest"


def infer_bsb_id(score_dir: Path) -> str:
    for path in sorted(score_dir.glob("*.mei")):
        if path.stem.endswith("_facs_zones"):
            continue
        bsb_id = path.stem.rsplit("_", 1)[0]
        if bsb_id.startswith("bsb"):
            return bsb_id
    raise FileNotFoundError(f"Could not infer BSB id from MEI files in {score_dir}")


def stem_page_number(stem: str) -> int | None:
    match = re.search(r"_(\d+)$", stem)
    return int(match.group(1)) if match else None


def local_stems(score_dir: Path, kind: str) -> set[str]:
    if kind == "source_mei":
        return {
            path.stem
            for path in score_dir.glob("*.mei")
            if path.is_file() and not path.stem.endswith("_facs_zones")
        }
    if kind == "images":
        image_dir = score_dir / "img"
        return {path.stem for path in image_dir.glob("*.jpg") if path.is_file()}
    if kind == "annotations":
        return {
            path.name.replace("_measure_annotations.xml", "")
            for path in score_dir.glob("*_measure_annotations.xml")
            if path.is_file()
        }
    if kind == "facs_zones":
        return {
            path.name.replace("_facs_zones.mei", "")
            for path in score_dir.glob("*_facs_zones.mei")
            if path.is_file()
        }
    raise ValueError(f"Unsupported local stem kind: {kind}")


def fetch_manifest_stems(bsb_id: str, timeout: int) -> tuple[dict, list[str]]:
    url = MANIFEST_URL.format(bsb_id=bsb_id)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    manifest = response.json()
    canvases = manifest.get("sequences", [{}])[0].get("canvases", [])
    stems: list[str] = []
    for canvas in canvases:
        match = re.search(rf"{re.escape(bsb_id)}_\d+", json.dumps(canvas))
        if match:
            stems.append(match.group(0))
    if not stems:
        raise RuntimeError(f"Could not extract page stems from manifest {url}")
    return manifest, stems


def compare_to_manifest(manifest_stems: list[str], local: set[str]) -> dict[str, object]:
    manifest_set = set(manifest_stems)
    local_numbers = sorted(n for stem in local if (n := stem_page_number(stem)) is not None)
    manifest_numbers = sorted(
        n for stem in manifest_set if (n := stem_page_number(stem)) is not None
    )
    return {
        "local_count": len(local),
        "manifest_count": len(manifest_set),
        "local_min_page": min(local_numbers) if local_numbers else None,
        "local_max_page": max(local_numbers) if local_numbers else None,
        "manifest_min_page": min(manifest_numbers) if manifest_numbers else None,
        "manifest_max_page": max(manifest_numbers) if manifest_numbers else None,
        "missing_vs_manifest": sorted(manifest_set - local),
        "extra_vs_manifest": sorted(local - manifest_set),
    }


def write_csv(path: Path, comparisons: dict[str, dict[str, object]]) -> None:
    rows = []
    for kind, data in comparisons.items():
        for stem in data["missing_vs_manifest"]:
            rows.append({"kind": kind, "status": "missing_vs_manifest", "stem": stem})
        for stem in data["extra_vs_manifest"]:
            rows.append({"kind": kind, "status": "extra_vs_manifest", "stem": stem})

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["kind", "status", "stem"])
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score_dir", help="Directory containing source page-level MEI files")
    parser.add_argument("--bsb-id", help="Override inferred BSB id")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds")
    parser.add_argument("--no-write", action="store_true", help="Do not write JSON/CSV reports")
    return parser


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    score_dir = Path(args.score_dir).resolve()
    if not score_dir.is_dir():
        parser.error(f"Score directory does not exist: {score_dir}")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    bsb_id = args.bsb_id or infer_bsb_id(score_dir)
    manifest, manifest_stems = fetch_manifest_stems(bsb_id, args.timeout)
    comparisons = {
        kind: compare_to_manifest(manifest_stems, local_stems(score_dir, kind))
        for kind in ("source_mei", "images", "annotations", "facs_zones")
    }

    report = {
        "timestamp": dt.datetime.now().strftime("%Y%m%d_%H%M%S"),
        "score_dir": str(score_dir),
        "bsb_id": bsb_id,
        "manifest_url": MANIFEST_URL.format(bsb_id=bsb_id),
        "manifest_label": manifest.get("label"),
        "manifest_count": len(set(manifest_stems)),
        "manifest_first": manifest_stems[:5],
        "manifest_last": manifest_stems[-5:],
        "comparisons": comparisons,
    }

    print(f"BSB manifest pages: {report['manifest_count']}")
    for kind, data in comparisons.items():
        print(
            f"{kind}: local={data['local_count']}, "
            f"missing={len(data['missing_vs_manifest'])}, "
            f"extra={len(data['extra_vs_manifest'])}"
        )
        if data["missing_vs_manifest"]:
            print("  missing:", ", ".join(data["missing_vs_manifest"][:40]))
        if data["extra_vs_manifest"]:
            print("  extra:", ", ".join(data["extra_vs_manifest"][:40]))

    if not args.no_write:
        stem = f"bsb_page_coverage_{report['timestamp']}"
        json_path = score_dir / f"{stem}.json"
        csv_path = score_dir / f"{stem}.csv"
        json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        write_csv(csv_path, comparisons)
        print(f"JSON report: {json_path}")
        print(f"CSV report: {csv_path}")

    has_missing_or_extra = any(
        data["missing_vs_manifest"] or data["extra_vs_manifest"]
        for data in comparisons.values()
    )
    return 1 if has_missing_or_extra else 0


if __name__ == "__main__":
    raise SystemExit(main())
