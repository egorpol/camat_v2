#!/usr/bin/env python3
"""Validate release metadata and prepare notes before publishing a distribution."""
from __future__ import annotations

import argparse
import ast
from datetime import date
import os
from pathlib import Path
import re
import tomllib

from packaging.version import Version


def prepare_release(root: Path, tag: str) -> tuple[str, bool, str]:
    """Return the package version, prerelease flag, and validated release notes."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    parsed_version = Version(version)
    if tag != f"v{version}":
        raise ValueError(f"Tag {tag!r} does not match package version {version!r}.")

    module = ast.parse((root / "camat/__init__.py").read_text(encoding="utf-8"))
    module_versions = [
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    ]
    if module_versions != [version]:
        raise ValueError("camat.__version__ does not match the package version.")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = list(re.finditer(
        rf"^## \[{re.escape(version)}\] - (?P<date>[^\n]+)\n"
        r"(?P<body>.*?)(?=^## \[|\Z)",
        changelog, re.MULTILINE | re.DOTALL,
    ))
    if len(sections) != 1:
        raise ValueError(f"Expected one dated changelog section for {version!r}.")
    section = sections[0]
    release_date = section["date"].strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
        raise ValueError("Release date must use YYYY-MM-DD.")
    date.fromisoformat(release_date)
    notes = section["body"].strip()
    meaningful_lines = [line for line in notes.splitlines() if line.strip() and not line.startswith("#")]
    if not meaningful_lines:
        raise ValueError(f"Release notes for {version!r} are empty.")
    return version, parsed_version.is_prerelease, notes + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME"))
    parser.add_argument("--notes", type=Path, default=Path(".release-runs/release-notes.md"))
    args = parser.parse_args()
    if not args.tag:
        parser.error("Provide --tag or set GITHUB_REF_NAME.")
    try:
        version, prerelease, notes = prepare_release(Path(__file__).resolve().parents[1], args.tag)
    except ValueError as exc:
        parser.exit(1, f"Release validation failed: {exc}\n")
    args.notes.parent.mkdir(parents=True, exist_ok=True)
    args.notes.write_text(notes, encoding="utf-8")
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"package_version={version}\ntag_name={args.tag}\nprerelease={str(prerelease).lower()}\n")
    print(f"Validated {args.tag}; prerelease={prerelease}; notes={args.notes}")


if __name__ == "__main__":
    main()
