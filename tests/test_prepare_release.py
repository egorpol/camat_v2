from pathlib import Path

import pytest

from scripts.prepare_release import prepare_release


def release_checkout(
    root: Path, version: str = "0.2.1", notes: str = "- Fixed parsing.", *, linked_heading: bool = False,
) -> Path:
    (root / "camat").mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n')
    (root / "camat/__init__.py").write_text(f'__version__ = "{version}"\n')
    heading = f"[{version}][{version}]" if linked_heading else f"[{version}]"
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [Unreleased]\n\n## {heading} - 2026-09-07\n\n{notes}\n\n"
        "## [0.1.0] - 2026-01-01\n\n- Older release.\n"
    )
    return root


@pytest.mark.parametrize("version,prerelease", [
    ("0.2.1", False), ("0.2.2b1", True), ("0.2.2rc1", True), ("0.2.2.dev1", True),
])
@pytest.mark.parametrize("linked_heading", [False, True])
def test_release_notes_and_github_status(tmp_path, version, prerelease, linked_heading):
    root = release_checkout(tmp_path, version, linked_heading=linked_heading)
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
@pytest.mark.parametrize("linked_heading", [False, True])
def test_empty_notes_block_publication(tmp_path, notes, linked_heading):
    root = release_checkout(tmp_path, notes=notes, linked_heading=linked_heading)
    with pytest.raises(ValueError, match="empty"):
        prepare_release(root, "v0.2.1")


@pytest.mark.parametrize("heading", [
    "## [0.2.0] - 2026-09-07", "## [0.2.1]", "## [0.2.1] - 2026-02-30",
    "## [0.2.0][0.2.0] - 2026-09-07", "## [0.2.1][0.2.1]",
    "## [0.2.1][0.2.1] - 2026-02-30",
])
def test_missing_or_invalid_dated_section_blocks_publication(tmp_path, heading):
    root = release_checkout(tmp_path)
    (root / "CHANGELOG.md").write_text(f"{heading}\n\n- Fixed parsing.\n")
    with pytest.raises(ValueError):
        prepare_release(root, "v0.2.1")


@pytest.mark.parametrize("linked_heading", [False, True])
@pytest.mark.parametrize("duplicate_heading", ["[0.2.1]", "[0.2.1][0.2.1]"])
def test_duplicate_version_sections_block_publication(tmp_path, linked_heading, duplicate_heading):
    root = release_checkout(tmp_path, linked_heading=linked_heading)
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text() + f"\n## {duplicate_heading} - 2026-09-08\n\n- Duplicate release.\n"
    )
    with pytest.raises(ValueError, match="Expected one dated changelog section"):
        prepare_release(root, "v0.2.1")


@pytest.mark.parametrize("linked_heading", [False, True])
def test_unreleased_notes_are_ignored(tmp_path, linked_heading):
    root = release_checkout(tmp_path, linked_heading=linked_heading)
    changelog = root / "CHANGELOG.md"
    changelog.write_text(changelog.read_text().replace(
        "## [Unreleased]\n\n", "## [Unreleased][Unreleased]\n\n- Future work for @someone.\n\n",
    ))
    assert prepare_release(root, "v0.2.1") == ("0.2.1", False, "- Fixed parsing.\n")


def test_reference_link_label_can_differ_from_version(tmp_path):
    root = release_checkout(tmp_path, linked_heading=True)
    changelog = root / "CHANGELOG.md"
    changelog.write_text(changelog.read_text().replace("[0.2.1][0.2.1]", "[0.2.1][release-link]"))
    assert prepare_release(root, "v0.2.1") == ("0.2.1", False, "- Fixed parsing.\n")


@pytest.mark.parametrize("notes", [
    "- Fixed unresolved measure @facs links.",
    "- Fixed unresolved measure `@facs` links.",
    "- Linked `<graphic @target>` images.",
    "- Matched zones on `@type`.",
])
@pytest.mark.parametrize("linked_heading", [False, True])
def test_github_mention_tokens_block_publication(tmp_path, notes, linked_heading):
    root = release_checkout(tmp_path, notes=notes, linked_heading=linked_heading)
    with pytest.raises(ValueError, match="false Contributors"):
        prepare_release(root, "v0.2.1")


@pytest.mark.parametrize("notes", [
    "- Fixed unresolved measure `facs` links.",
    "- Linked `<graphic &#64;target>` images.",
    "- Contact support@example.com for corpus access.",
])
@pytest.mark.parametrize("linked_heading", [False, True])
def test_safe_attribute_spellings_and_emails_are_allowed(tmp_path, notes, linked_heading):
    root = release_checkout(tmp_path, notes=notes, linked_heading=linked_heading)
    assert prepare_release(root, "v0.2.1") == ("0.2.1", False, f"{notes}\n")
