#!/usr/bin/env python3
"""
Run the full processing pipeline for a score directory.

Usage:
    camat-run-pipeline DdT_1/05_ahle_ausgewaehlte_gesangswerke_bsb00023114

    # Run only specific steps:
    camat-run-pipeline DdT_1/04_... --steps 4 5

    # Re-download images (e.g. if local images are outdated or mismatched):
    camat-run-pipeline DdT_1/04_... --overwrite-images

    # Use looser measure filters during annotation integration:
    camat-run-pipeline DdT_1/04_... --minimum-measures 2 --max-measure-mismatch 4

    # Skip preface pages:
    camat-run-pipeline DdT_1/04_... --skip-pages 1-29
"""

import argparse
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path.cwd()


def module_command(name):
    """Return an interpreter command for another installed CAMAT module."""
    return [sys.executable, "-m", f"camat.{name}"]


def add_page_filter_args(command, args):
    if args.pages:
        command.extend(["--pages", args.pages])
    if args.skip_pages:
        command.extend(["--skip-pages", args.skip_pages])
    return command


def step1_args(folder, args):
    # Note: 500 DPI is approximate — the pixel width is computed assuming a 210mm (A4) page width,
    # which may not match the actual physical dimensions of each DdT volume. The effective DPI
    # will differ for volumes with wider or narrower pages.
    command = module_command("facsimile_downloader") + [folder, "--target-dpi", "500"]
    if args.overwrite_images:
        command.append("--overwrite")
    return add_page_filter_args(command, args)


def annotation_integration_args(folder, args, *, graphic_target_mode):
    command = [
        *module_command("upload_and_integrate_measure_annotations"),
        folder,
        "--minimum-measures", str(args.minimum_measures),
        "--max-measure-mismatch", str(args.max_measure_mismatch),
        "--timeout", str(args.timeout),
        "--reuse-annotations",
        "--overwrite",
    ]
    if args.force:
        command.append("--force")
    if graphic_target_mode == "iiif":
        command.extend(["--graphic-target-mode", "iiif"])
    return add_page_filter_args(command, args)


def step2_args(folder, args):
    return annotation_integration_args(folder, args, graphic_target_mode="local")


def step3_args(folder, _args):
    return add_page_filter_args(module_command("validate_iiif_vs_local") + [folder], _args)


def step4_args(folder, args):
    return annotation_integration_args(folder, args, graphic_target_mode="iiif")


def step5_args(folder, _args):
    return add_page_filter_args(
        module_command("validate_iiif_vs_local") + [folder, "--check-output-mei"],
        _args,
    )


STEPS = [
    {
        "label": "Step 1: Download facsimile images at 500 DPI",
        "continue_on_failure": False,
        "args": step1_args,
    },
    {
        "label": "Step 2: Upload and integrate measure annotations (local paths)",
        "continue_on_failure": True,  # partial failures (HTTP 500, measure mismatches) are expected
        "args": step2_args,
    },
    {
        "label": "Step 3: Validate IIIF vs local",
        "continue_on_failure": False,
        "args": step3_args,
    },
    {
        "label": "Step 4: Re-run integration with IIIF URLs",
        "continue_on_failure": True,  # same partial failures expected as Step 2
        "args": step4_args,
    },
    {
        "label": "Step 5: Validate final MEI files",
        "continue_on_failure": True,  # partial failures expected for pages that failed Steps 2/4
        "args": step5_args,
    },
]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", help="Score directory to process (e.g. DdT_1/05_...)")
    parser.add_argument("--overwrite-images", action="store_true",
                        help="Re-download all facsimile images even if they already exist locally")
    parser.add_argument("--steps", nargs="+", type=int, metavar="N",
                        help="Run only these step numbers, e.g. --steps 4 5 (default: all)")
    parser.add_argument("--minimum-measures", type=int, default=5,
                        help="Skip pages whose source MEI has fewer measures than this threshold (default: 5)")
    parser.add_argument("--max-measure-mismatch", type=int, default=1,
                        help="Maximum number of unmatched measure numbers allowed during integration (default: 1)")
    parser.add_argument("--timeout", type=int, default=180,
                        help="HTTP timeout in seconds for measure detector uploads (default: 180)")
    parser.add_argument("--force", action="store_true",
                        help="Allow any amount of source-vs-annotation measure mismatch during integration")
    parser.add_argument("--pages",
                        help='Only process these page numbers/ranges, e.g. "30-" or "30-120,130"')
    parser.add_argument("--skip-pages",
                        help='Skip these page numbers/ranges, e.g. "1-29" for preface pages')
    args = parser.parse_args(argv)

    steps_to_run = args.steps or list(range(1, len(STEPS) + 1))
    invalid = [n for n in steps_to_run if n < 1 or n > len(STEPS)]
    if invalid:
        parser.error(f"Invalid step numbers: {invalid}. Valid range is 1–{len(STEPS)}.")
    if args.minimum_measures < 0:
        parser.error("--minimum-measures must be >= 0")
    if args.max_measure_mismatch < 0:
        parser.error("--max-measure-mismatch must be >= 0")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    for i, step in enumerate(STEPS, start=1):
        if i not in steps_to_run:
            continue
        print(f"\n=== {step['label']} ===")
        result = subprocess.run(step["args"](args.folder, args), cwd=REPO_ROOT)
        if result.returncode != 0:
            if step.get("continue_on_failure"):
                print(f"\nWARNING: {step['label']} had failures (continuing)", file=sys.stderr)
            else:
                print(f"\nFAILED: {step['label']}", file=sys.stderr)
                return result.returncode

    print("\n=== All steps completed successfully ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
