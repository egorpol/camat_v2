"""
Cleanup script for CAMAT corpus folders.

Rules applied to each target folder:
  - Delete everything except files whose stem ends in _facs_zones
  - Also delete the img/ subfolder entirely

Usage:
  camat-corpus-cleanup                  # dry run on numbered folders in the current directory
  camat-corpus-cleanup --run            # actually delete after confirmation
  camat-corpus-cleanup path/to/folder   # dry run on a specific folder
  camat-corpus-cleanup path/to/folder --run
"""

import argparse
import shutil
from pathlib import Path


def collect_deletions(folder: Path) -> list[Path]:
    to_delete = []

    for f in folder.iterdir():
        if f.is_dir() and f.name.lower() == "img":
            to_delete.append(f)
            continue

        if not f.is_file():
            continue

        if not f.stem.endswith("_facs_zones"):
            to_delete.append(f)

    return to_delete


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Corpus folders to inspect")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Delete the listed items after an additional confirmation prompt",
    )
    args = parser.parse_args(argv)
    dry_run = not args.run
    paths = args.paths

    repo_root = Path.cwd()

    if paths:
        folders = [Path(p) for p in paths]
    else:
        folders = sorted(d for d in repo_root.iterdir() if d.is_dir() and d.name[0].isdigit())

    if not folders:
        print("No folders found.")
        return 0

    all_deletions: list[tuple[Path, Path]] = []  # (folder, item)
    for folder in folders:
        if not folder.exists():
            print(f"Folder not found: {folder}")
            continue
        items = collect_deletions(folder)
        for item in items:
            all_deletions.append((folder, item))

    if not all_deletions:
        print("Nothing to delete.")
        return 0

    print(f"{'DRY RUN — ' if dry_run else ''}Files/folders to delete:\n")
    current_folder = None
    for folder, item in all_deletions:
        if folder != current_folder:
            print(f"  [{folder.name}]")
            current_folder = folder
        label = "(dir) " if item.is_dir() else ""
        print(f"    {label}{item.name}")

    total = len(all_deletions)
    print(f"\nTotal: {total} item(s)")

    if dry_run:
        print("\nRun with --run to actually delete.")
        return 0

    confirm = input("\nProceed with deletion? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return 0

    deleted = 0
    for folder, item in all_deletions:
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            deleted += 1
        except Exception as e:
            print(f"Error deleting {item}: {e}")

    print(f"Deleted {deleted}/{total} item(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
