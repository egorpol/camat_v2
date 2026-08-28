from __future__ import annotations

import re
from pathlib import Path

PageRange = tuple[int | None, int | None]


def page_number_for_path(path: Path) -> int | None:
    match = re.search(r"_(\d+)$", path.stem)
    return int(match.group(1)) if match else None


def parse_page_ranges(spec: str | None) -> list[PageRange]:
    if not spec:
        return []

    ranges: list[PageRange] = []
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text) if start_text else None
            end = int(end_text) if end_text else None
        else:
            start = end = int(part)
        if start is not None and start <= 0:
            raise ValueError(f"Page numbers must be positive: {part}")
        if end is not None and end <= 0:
            raise ValueError(f"Page numbers must be positive: {part}")
        if start is not None and end is not None and start > end:
            raise ValueError(f"Invalid page range with start > end: {part}")
        ranges.append((start, end))
    return ranges


def page_in_ranges(page: int, ranges: list[PageRange]) -> bool:
    return any(
        (start is None or page >= start) and (end is None or page <= end)
        for start, end in ranges
    )


def filter_mei_files(
    mei_files: list[Path],
    *,
    pages: str | None = None,
    skip_pages: str | None = None,
) -> list[Path]:
    include_ranges = parse_page_ranges(pages)
    skip_ranges = parse_page_ranges(skip_pages)
    if not include_ranges and not skip_ranges:
        return mei_files

    filtered: list[Path] = []
    for path in mei_files:
        page = page_number_for_path(path)
        if page is None:
            raise ValueError(f"Could not infer page number from {path.name}")
        if include_ranges and not page_in_ranges(page, include_ranges):
            continue
        if skip_ranges and page_in_ranges(page, skip_ranges):
            continue
        filtered.append(path)

    if not filtered:
        raise ValueError("Page filter selected no MEI files")
    return filtered
