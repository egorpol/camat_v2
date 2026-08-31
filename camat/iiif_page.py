"""Plan and run IIIF facsimile + measure-zone integration for one or more MEI pages.

The single-file notebook shows each step. This module is the batch form of the
same job: identify the facsimile page, copy the MEI to a working name,
download the image, send it to the measure-detector network, and write
``{stem}_facs_zones.mei`` with an IIIF ``<graphic @target>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

from .facsimile_downloader import (
    collect_mei_files,
    download_facsimile_image,
    parse_bsb_filename_stem,
    parse_bsb_viewer_url,
    stage_mei_copy,
)
from .facsimile_viewer import (
    display_path,
    format_facsimile_summary,
    read_facsimile_model,
    resolve_repo_path,
)
from .page_filter import filter_mei_files, page_in_ranges, parse_page_ranges
from .upload_and_integrate_measure_annotations import DETECTOR_URL, process_mei_file
from .validate_iiif_vs_local import (
    IIIF_IMAGE_URL_TEMPLATE,
    parse_graphic_from_output_mei,
    read_image_size,
    sha256_bytes,
    sha256_file,
)

JobDict = dict[str, str | Path]


@dataclass(frozen=True)
class IiifPagePlan:
    """Resolved paths and identifiers for one IIIF page job. No files are written."""

    source_mei: Path
    archive_url: str | None
    iiif_image_url: str | None
    bsb_id: str | None
    page_number: int | None
    target_stem: str
    staged_mei: Path
    image_dir: Path
    image_path: Path
    annotation_path: Path
    final_mei: Path


def collect_iiif_jobs_from_directory(
    score_dir: str | Path,
    *,
    pages: str | None = None,
    skip_pages: str | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, str]]:
    """Turn a folder of page MEI files into job dicts.

    Files already named ``bsb…_NNNNN.mei`` do not need ``archive_url`` or
    ``iiif_image_url``; the IIIF link is built from the filename stem.
    """
    score_dir = resolve_repo_path(score_dir, repo_root=repo_root)
    mei_files = filter_mei_files(
        collect_mei_files(score_dir),
        pages=pages,
        skip_pages=skip_pages,
    )
    return [
        {"source_mei": str(path), "archive_url": "", "iiif_image_url": ""}
        for path in mei_files
    ]


def plan_iiif_page(
    source_mei: str | Path,
    *,
    target_dir: str | Path,
    archive_url: str | None = None,
    iiif_image_url: str | None = None,
    repo_root: Path | None = None,
    require_clean: bool = True,
) -> IiifPagePlan:
    """Resolve working paths for one page. Reads the source; does not write."""
    source_path = resolve_repo_path(source_mei, repo_root=repo_root)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    archive = (archive_url or "").strip() or None
    image_url = (iiif_image_url or "").strip() or None
    filename_ids = parse_bsb_filename_stem(source_path.stem)

    if archive:
        bsb_id, page_number, target_stem = parse_bsb_viewer_url(archive)
    elif filename_ids is not None:
        bsb_id, page_number, target_stem = filename_ids
    elif image_url:
        bsb_id = page_number = None
        target_stem = source_path.stem
    else:
        raise ValueError(
            f"Set archive_url and/or iiif_image_url for {source_path.name}, "
            "or name the file like bsb00023199_00185.mei."
        )

    target_dir_path = resolve_repo_path(target_dir, repo_root=repo_root)
    staged_mei = target_dir_path / f"{target_stem}.mei"
    image_dir = target_dir_path / "img"
    plan = IiifPagePlan(
        source_mei=source_path,
        archive_url=archive,
        iiif_image_url=image_url,
        bsb_id=bsb_id,
        page_number=page_number,
        target_stem=target_stem,
        staged_mei=staged_mei,
        image_dir=image_dir,
        image_path=image_dir / f"{target_stem}.jpg",
        annotation_path=target_dir_path / f"{target_stem}_measure_annotations.xml",
        final_mei=target_dir_path / f"{target_stem}_facs_zones.mei",
    )

    if require_clean:
        model = read_facsimile_model(source_path, repo_root=repo_root, allow_missing_facsimile=True)
        if model["has_facsimile"]:
            raise ValueError(
                f"{display_path(source_path, repo_root=repo_root)} already contains "
                "facsimile integration.\n" + format_facsimile_summary(model, repo_root=repo_root)
            )
    return plan


def plan_iiif_pages(
    jobs: list[JobDict],
    *,
    target_dir: str | Path,
    pages: str | None = None,
    skip_pages: str | None = None,
    repo_root: Path | None = None,
    require_clean: bool = True,
) -> list[IiifPagePlan]:
    """Plan every job dict, then apply optional page filters."""
    if not jobs:
        raise ValueError("JOBS is empty. Add at least one source_mei row.")

    plans = [
        plan_iiif_page(
            job["source_mei"],
            target_dir=target_dir,
            archive_url=str(job.get("archive_url") or ""),
            iiif_image_url=str(job.get("iiif_image_url") or ""),
            repo_root=repo_root,
            require_clean=require_clean,
        )
        for job in jobs
    ]
    return filter_iiif_plans(plans, pages=pages, skip_pages=skip_pages)


def filter_iiif_plans(
    plans: list[IiifPagePlan],
    *,
    pages: str | None = None,
    skip_pages: str | None = None,
) -> list[IiifPagePlan]:
    """Keep plans whose page number matches ``pages`` / ``skip_pages``."""
    include_ranges = parse_page_ranges(pages)
    skip_ranges = parse_page_ranges(skip_pages)
    if not include_ranges and not skip_ranges:
        return plans

    filtered: list[IiifPagePlan] = []
    for plan in plans:
        if plan.page_number is None:
            raise ValueError(
                f"No page number for {plan.source_mei.name}; "
                "PAGES/SKIP_PAGES need an ARCHIVE_URL or a bsb…_NNNNN filename."
            )
        if include_ranges and not page_in_ranges(plan.page_number, include_ranges):
            continue
        if skip_ranges and page_in_ranges(plan.page_number, skip_ranges):
            continue
        filtered.append(plan)
    if not filtered:
        raise ValueError("Page filter selected no IIIF jobs")
    return filtered


def format_iiif_page_plans(plans: list[IiifPagePlan], *, repo_root: Path | None = None) -> str:
    """Return a compact inventory for the notebook plan cell."""
    if not plans:
        return "No jobs selected."
    lines = [
        f"{'page':>5}  {'stem':<22}  {'source':<56}  clean",
        f"{'-'*5}  {'-'*22}  {'-'*56}  -----",
    ]
    for plan in plans:
        model = read_facsimile_model(
            plan.source_mei,
            repo_root=repo_root,
            allow_missing_facsimile=True,
        )
        clean = "yes" if not model["has_facsimile"] else "NO"
        page = str(plan.page_number) if plan.page_number is not None else "-"
        source = display_path(plan.source_mei, repo_root=repo_root)
        lines.append(f"{page:>5}  {plan.target_stem:<22}  {source:<56}  {clean}")
    lines.append(f"{len(plans)} job(s)")
    return "\n".join(lines)


def _verify_local_matches_iiif(image_path: Path, image_url: str, *, timeout: int) -> None:
    local_hash = sha256_file(image_path)
    response = requests.get(image_url, timeout=timeout)
    response.raise_for_status()
    if local_hash != sha256_bytes(response.content):
        raise RuntimeError(f"Local facsimile does not match the IIIF source: {image_url}")


def integrate_iiif_page(
    plan: IiifPagePlan,
    *,
    target_dpi: int = 500,
    page_width_mm: float = 210.0,
    timeout: int = 180,
    minimum_measures: int = 5,
    max_measure_mismatch: int | None = 1,
    overwrite_staged: bool = False,
    overwrite_output: bool = False,
    overwrite_images: bool = False,
    reuse_annotations: bool = False,
    verify_iiif: bool = True,
    detector_url: str = DETECTOR_URL,
    iiif_url_template: str = IIIF_IMAGE_URL_TEMPLATE,
    retries: int = 2,
    retry_delay: float = 2.0,
) -> dict[str, object]:
    """Run the single-page IIIF job described by ``plan``. Returns result paths."""
    staged_mei = stage_mei_copy(
        plan.source_mei,
        plan.staged_mei.parent,
        plan.target_stem,
        overwrite=overwrite_staged,
    )
    image_path, expected_iiif_url = download_facsimile_image(
        plan.image_path,
        stem=plan.target_stem,
        image_url=plan.iiif_image_url,
        target_dpi=target_dpi,
        page_width_mm=page_width_mm,
        timeout=timeout,
        overwrite=overwrite_images,
    )
    width, height = read_image_size(image_path)

    detect_kwargs = {
        "image_dir": plan.image_dir,
        "detector_url": detector_url,
        "timeout": timeout,
        "retries": retries,
        "retry_delay": retry_delay,
        "minimum_measures": minimum_measures,
        "max_measure_mismatch": max_measure_mismatch,
        "annotation_suffix": "_measure_annotations.xml",
        "output_suffix": "_facs_zones",
        "iiif_url_template": iiif_url_template,
        "graphic_target": expected_iiif_url,
    }
    annotation_path, _local_output = process_mei_file(
        staged_mei,
        reuse_annotations=reuse_annotations,
        overwrite=overwrite_output,
        graphic_target_mode="local",
        **detect_kwargs,
    )
    if verify_iiif:
        _verify_local_matches_iiif(image_path, expected_iiif_url, timeout=timeout)

    annotation_path, final_mei = process_mei_file(
        staged_mei,
        reuse_annotations=True,
        overwrite=True,
        graphic_target_mode="iiif",
        **detect_kwargs,
    )
    target, mei_width, mei_height = parse_graphic_from_output_mei(final_mei)
    if target != expected_iiif_url:
        raise RuntimeError(f"Graphic target mismatch: {target} != {expected_iiif_url}")
    if (mei_width, mei_height) != (width, height):
        raise RuntimeError(
            f"Graphic size mismatch: {(mei_width, mei_height)} != {(width, height)}"
        )
    final_model = read_facsimile_model(final_mei)
    if not final_model["has_facsimile"] or not final_model["zones"] or not final_model["linked"]:
        raise RuntimeError(f"Integrated MEI is missing facsimile links: {final_mei}")

    return {
        "ok": True,
        "target_stem": plan.target_stem,
        "source_mei": plan.source_mei,
        "staged_mei": staged_mei,
        "image_path": image_path,
        "expected_iiif_url": expected_iiif_url,
        "annotation_path": annotation_path,
        "final_mei": final_mei,
        "width": width,
        "height": height,
        "error": None,
    }


def integrate_iiif_pages(
    plans: list[IiifPagePlan],
    *,
    continue_on_error: bool = True,
    **kwargs,
) -> list[dict[str, object]]:
    """Run every planned job. Failed pages are recorded when ``continue_on_error``."""
    results: list[dict[str, object]] = []
    for plan in plans:
        try:
            results.append(integrate_iiif_page(plan, **kwargs))
        except Exception as exc:
            if not continue_on_error:
                raise
            results.append(
                {
                    "ok": False,
                    "target_stem": plan.target_stem,
                    "source_mei": plan.source_mei,
                    "staged_mei": plan.staged_mei,
                    "image_path": plan.image_path,
                    "expected_iiif_url": None,
                    "annotation_path": plan.annotation_path,
                    "final_mei": plan.final_mei,
                    "width": None,
                    "height": None,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return results


def format_iiif_page_results(results: list[dict[str, object]], *, repo_root: Path | None = None) -> str:
    """Return a compact run summary."""
    if not results:
        return "No jobs ran."
    succeeded = sum(1 for row in results if row.get("ok"))
    lines = [f"{succeeded}/{len(results)} job(s) succeeded"]
    for row in results:
        stem = row.get("target_stem")
        if row.get("ok"):
            final_mei = display_path(Path(str(row["final_mei"])), repo_root=repo_root)
            lines.append(f"  OK   {stem}: {final_mei}")
        else:
            lines.append(f"  FAIL {stem}: {row.get('error')}")
    return "\n".join(lines)
