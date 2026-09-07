import subprocess
from types import SimpleNamespace

import pytest

from scripts import docs_hooks


@pytest.fixture
def docs_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(docs_hooks, "REPO_ROOT", tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.1b1"\n')
    (tmp_path / "docs" / "guides").mkdir(parents=True)
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "notebooks" / "demo.ipynb").write_text("{}")
    config = {
        "docs_dir": str(tmp_path / "docs"),
        "repo_url": "https://github.com/egorpol/camat_v2",
        "extra": {"camat_repo_ref": "a" * 40},
    }
    page = SimpleNamespace(file=SimpleNamespace(abs_src_path=str(tmp_path / "docs/guides/demo.md")))
    return config, page


def test_notebook_links_use_build_revision_and_preserve_fragments(docs_checkout):
    config, page = docs_checkout
    result = docs_hooks.on_page_markdown(
        "[Demo](../../notebooks/demo.ipynb#example) and [Guide](../overview.md)",
        page=page, config=config, files=None,
    )
    assert result == (
        f"[Demo](https://github.com/egorpol/camat_v2/blob/{'a' * 40}/notebooks/demo.ipynb#example) "
        "and [Guide](../overview.md)"
    )


def test_repository_directory_links_use_tree(docs_checkout):
    config, page = docs_checkout
    config["extra"]["camat_repo_ref"] = "beta/0.2.1"
    result = docs_hooks.on_page_markdown(
        "[Notebooks](../../notebooks)", page=page, config=config, files=None,
    )
    assert result == "[Notebooks](https://github.com/egorpol/camat_v2/tree/beta/0.2.1/notebooks)"


@pytest.mark.parametrize("target", ["../../missing.ipynb", "../../../outside.ipynb"])
def test_missing_or_outside_repository_targets_fail_build(docs_checkout, target):
    config, page = docs_checkout
    with pytest.raises(ValueError, match="missing repository link target"):
        docs_hooks.on_page_markdown(f"[Missing]({target})", page=page, config=config, files=None)


def test_build_uses_checkout_version_and_explicit_ref(docs_checkout, monkeypatch):
    config, _ = docs_checkout
    monkeypatch.setenv("CAMAT_DOCS_REF", "v0.2.1b1")
    result = docs_hooks.on_config(config)
    assert result["site_name"] == "CAMAT 0.2.1b1"
    assert result["extra"]["camat_repo_ref"] == "v0.2.1b1"
    assert result["edit_uri"] == "blob/v0.2.1b1/docs/"


def test_build_uses_commit_for_detached_checkouts(docs_checkout, monkeypatch):
    config, _ = docs_checkout
    monkeypatch.delenv("CAMAT_DOCS_REF", raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "b" * 40 + "\n")
    assert docs_hooks.on_config(config)["extra"]["camat_repo_ref"] == "b" * 40


def test_source_snapshot_requires_an_explicit_ref(docs_checkout, monkeypatch):
    config, _ = docs_checkout
    monkeypatch.delenv("CAMAT_DOCS_REF", raising=False)

    def no_git(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "check_output", no_git)
    with pytest.raises(ValueError, match="CAMAT_DOCS_REF"):
        docs_hooks.on_config(config)
