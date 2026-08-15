from __future__ import annotations

from pathlib import Path

from camat.parser_utils import expand_file_sources


def test_expand_file_sources_normalizes_direct_local_paths(tmp_path: Path) -> None:
    source = tmp_path / "scores" / "local.mei"

    expanded = expand_file_sources(
        ["scores/local.mei"],
        base_dir=tmp_path,
        verbose=False,
    )

    assert expanded == [str(source.resolve())]


def test_expand_file_sources_expands_mixed_manifest_from_base_dir(tmp_path: Path) -> None:
    manifest = tmp_path / "lists" / "sources.txt"
    manifest.parent.mkdir()
    manifest.write_text(
        "\n".join(
            [
                "# A local repository-relative path",
                "scores/local.musicxml",
                "",
                "https://example.org/remote.krn",
            ]
        ),
        encoding="utf-8",
    )

    expanded = expand_file_sources(
        ["lists/sources.txt"],
        base_dir=tmp_path,
        verbose=False,
    )

    assert expanded == [
        str((tmp_path / "scores" / "local.musicxml").resolve()),
        "https://example.org/remote.krn",
    ]


def test_expand_file_sources_preserves_absolute_paths_and_urls(tmp_path: Path) -> None:
    absolute = (tmp_path / "score.mei").resolve()
    url = "https://example.org/score.mei?download=1"

    expanded = expand_file_sources(
        [str(absolute), url],
        base_dir=tmp_path / "unused",
        verbose=False,
    )

    assert expanded == [str(absolute), url]
