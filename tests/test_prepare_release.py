from pathlib import Path

import pytest

from scripts.prepare_release import prepare_release


def release_checkout(root: Path, version: str = "0.2.1", notes: str = "- Fixed parsing.") -> Path:
    (root / "camat").mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (root / "camat/__init__.py").write_text(f'__version__ = "{version}"\n')
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [Unreleased]\n\n## [{version}] - 2026-09-07\n\n{notes}\n\n"
        "## [0.1.0] - 2026-01-01\n\n- Older release.\n"
    )
    return root


@pytest.mark.parametrize("version,prerelease", [
    ("0.2.1", False), ("0.2.2b1", True), ("0.2.2rc1", True), ("0.2.2.dev1", True),
])
def test_release_notes_and_github_status(tmp_path, version, prerelease):
    root = release_checkout(tmp_path, version)
    assert prepare_release(root, f"v{version}") == (version, prerelease, "- Fixed parsing.\n")


@pytest.mark.parametrize("mismatch", ["tag", "module"])
def test_inconsistent_versions_block_publication(tmp_path, mismatch):
    root = release_checkout(tmp_path)
    tag = "v0.2.2" if mismatch == "tag" else "v0.2.1"
    if mismatch == "module":
        (root / "camat/__init__.py").write_text('__version__ = "0.2.0"\n')
    with pytest.raises(ValueError, match="does not match"):
        prepare_release(root, tag)


@pytest.mark.parametrize("notes", ["", "### Added\n\n### Fixed"])
def test_empty_notes_block_publication(tmp_path, notes):
    root = release_checkout(tmp_path, notes=notes)
    with pytest.raises(ValueError, match="empty"):
        prepare_release(root, "v0.2.1")


@pytest.mark.parametrize("heading", [
    "## [0.2.0] - 2026-09-07", "## [0.2.1]", "## [0.2.1] - 2026-02-30",
])
def test_missing_or_invalid_dated_section_blocks_publication(tmp_path, heading):
    root = release_checkout(tmp_path)
    (root / "CHANGELOG.md").write_text(f"{heading}\n\n- Fixed parsing.\n")
    with pytest.raises(ValueError):
        prepare_release(root, "v0.2.1")
