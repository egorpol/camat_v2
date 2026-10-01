from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tarfile
import urllib.error

import pytest

from camat.facsimile_viewer import find_camat_root as viewer_find_camat_root
from camat.facsimile_viewer import resolve_mei_source_info
from camat.notebook_workspace import (
    WORKSPACE_ENV,
    _extract_tutorial_archive,
    _parse_github_repo,
    activate_workspace,
    fetch_tutorial_workspace,
    find_camat_root,
    is_source_checkout,
    is_tutorial_workspace,
    locate_workspace,
    main,
    prepare_notebook,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = REPO_ROOT / "notebooks"


@pytest.fixture(autouse=True)
def _clear_workspace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)


def _init_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    work = tmp_path / "remote-work"
    (work / "notebooks").mkdir(parents=True)
    (work / "test_corpus").mkdir()
    (work / "CAMAT_old").mkdir()
    (work / "notebooks" / "setup_camat.py").write_text("CAMAT_ROOT = None\n", encoding="utf-8")
    (work / "notebooks" / "demo.ipynb").write_text("{}\n", encoding="utf-8")
    (work / "test_corpus" / "sample.mei").write_text("<mei/>\n", encoding="utf-8")
    (work / "CAMAT_old" / "archive.ipynb").write_text("{}\n", encoding="utf-8")
    (work / "README.md").write_text("remote\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "camat@example.test"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "CAMAT tests"], cwd=work, check=True)
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "tutorials"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "clone", "--bare", str(work), str(remote)], check=True, capture_output=True)
    return remote


def test_source_checkout_and_tutorial_workspace_detection(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "camat").mkdir(parents=True)
    (checkout / "camat" / "__init__.py").write_text("", encoding="utf-8")
    (checkout / "pyproject.toml").write_text("[project]\nname = \"camat\"\n", encoding="utf-8")
    tutorials = tmp_path / "tutorials"
    (tutorials / "notebooks").mkdir(parents=True)
    (tutorials / "test_corpus").mkdir()

    assert is_source_checkout(checkout)
    assert not is_tutorial_workspace(checkout)
    assert is_tutorial_workspace(tutorials)
    assert not is_source_checkout(tutorials)
    assert locate_workspace(checkout / "camat") == checkout.resolve()
    assert locate_workspace(tutorials / "notebooks") == tutorials.resolve()
    assert locate_workspace(tmp_path / "empty") is None


def test_find_camat_root_prefers_env_and_matches_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "tutorials"
    (workspace / "notebooks").mkdir(parents=True)
    (workspace / "test_corpus").mkdir()
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert find_camat_root(elsewhere) == workspace.resolve()
    assert viewer_find_camat_root(elsewhere) == workspace.resolve()
    monkeypatch.delenv(WORKSPACE_ENV)
    assert find_camat_root(elsewhere) == elsewhere.resolve()


def test_prepare_notebook_reuses_existing_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "tutorials"
    (workspace / "notebooks").mkdir(parents=True)
    (workspace / "test_corpus").mkdir()
    monkeypatch.chdir(workspace / "notebooks")
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)

    root = prepare_notebook(fetch=False)
    assert root == workspace.resolve()
    assert Path.cwd() == workspace / "notebooks"


def test_prepare_notebook_fetch_false_without_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    with pytest.raises(FileNotFoundError, match="tutorial files"):
        prepare_notebook(fetch=False)


def test_fetch_tutorial_workspace_sparse_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = _init_remote(tmp_path)
    dest = tmp_path / "copied"
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)

    root = fetch_tutorial_workspace(dest, repo=str(remote), ref="main")

    assert root == dest.resolve()
    assert (dest / "notebooks" / "demo.ipynb").is_file()
    assert (dest / "test_corpus" / "sample.mei").is_file()
    assert not (dest / "CAMAT_old" / "archive.ipynb").exists()
    again = fetch_tutorial_workspace(dest, repo=str(remote), ref="main")
    assert again == dest.resolve()


def _github_archive_bytes(root: str = "camat_v2-main") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:

        def add(name: str, payload: bytes) -> None:
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        add(f"{root}/notebooks/demo.ipynb", b"{}\n")
        add(f"{root}/test_corpus/sample.mei", b"<mei/>\n")
        add(f"{root}/CAMAT_old/archive.ipynb", b"{}\n")
        add(f"{root}/notebooks/../../escaped.txt", b"nope\n")
    return buffer.getvalue()


def test_parse_github_repo() -> None:
    assert _parse_github_repo("https://github.com/egorpol/camat_v2.git") == (
        "egorpol",
        "camat_v2",
    )
    assert _parse_github_repo("https://github.com/egorpol/camat_v2") == (
        "egorpol",
        "camat_v2",
    )
    assert _parse_github_repo("git@github.com:egorpol/camat_v2.git") == (
        "egorpol",
        "camat_v2",
    )
    assert _parse_github_repo("/tmp/camat_v2.git") is None


def test_extract_tutorial_archive_keeps_tutorial_paths(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(_github_archive_bytes())
    dest = tmp_path / "copied"

    _extract_tutorial_archive(archive, dest, ("notebooks", "test_corpus"))

    assert (dest / "notebooks" / "demo.ipynb").read_text(encoding="utf-8") == "{}\n"
    assert (dest / "test_corpus" / "sample.mei").is_file()
    assert not (dest / "CAMAT_old").exists()
    assert not (tmp_path / "escaped.txt").exists()
    assert not (dest / "escaped.txt").exists()


def test_fetch_tutorial_workspace_uses_github_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _github_archive_bytes()
    calls: list[str] = []

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        calls.append(url)
        if url.endswith("/refs/heads/main"):
            return io.BytesIO(payload)
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("camat.notebook_workspace.urllib.request.urlopen", fake_urlopen)

    def fail_git(*args, **kwargs):
        raise AssertionError("git should not be used for a GitHub repository")

    monkeypatch.setattr("camat.notebook_workspace.subprocess.run", fail_git)
    dest = tmp_path / "copied"

    root = fetch_tutorial_workspace(
        dest,
        repo="https://github.com/egorpol/camat_v2.git",
        ref="main",
    )

    assert root == dest.resolve()
    assert (dest / "notebooks" / "demo.ipynb").is_file()
    assert not (dest / "CAMAT_old").exists()
    assert calls == [
        "https://codeload.github.com/egorpol/camat_v2/tar.gz/refs/tags/main",
        "https://codeload.github.com/egorpol/camat_v2/tar.gz/refs/heads/main",
    ]
    again = fetch_tutorial_workspace(
        dest,
        repo="https://github.com/egorpol/camat_v2.git",
        ref="main",
    )
    assert again == dest.resolve()
    assert len(calls) == 2


def test_github_archive_falls_back_to_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _github_archive_bytes()
    calls: list[str] = []

    def fake_urlopen(request, timeout=0):
        url = request.full_url
        calls.append(url)
        if url.endswith("/refs/heads/main"):
            return io.BytesIO(payload)
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("camat.notebook_workspace.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "camat.notebook_workspace._ref_candidates",
        lambda ref: ["v9.9.9", "main"],
    )

    fetch_tutorial_workspace(
        tmp_path / "copied",
        repo="https://github.com/egorpol/camat_v2.git",
    )

    assert calls[0].endswith("/refs/tags/v9.9.9")
    assert calls[-1].endswith("/refs/heads/main")


def test_github_download_error_does_not_require_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_urlopen(request, timeout=0):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("camat.notebook_workspace.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="Could not download") as exc_info:
        fetch_tutorial_workspace(
            tmp_path / "copied",
            repo="https://github.com/egorpol/camat_v2.git",
            ref="main",
        )

    message = str(exc_info.value)
    assert "git is required" not in message
    assert "Install git" not in message


def test_cli_writes_tutorial_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    remote = _init_remote(tmp_path)
    dest = tmp_path / "from-cli"
    assert main([str(dest), "--repo", str(remote), "--ref", "main"]) == 0
    captured = capsys.readouterr()
    assert str(dest) in captured.out
    assert (dest / "notebooks").is_dir()


def test_activate_workspace_puts_local_package_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "camat").mkdir(parents=True)
    (checkout / "camat" / "__init__.py").write_text("", encoding="utf-8")
    (checkout / "notebooks").mkdir()
    (checkout / "pyproject.toml").write_text("[project]\nname = \"camat\"\n", encoding="utf-8")
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    import os
    import sys

    original_path = list(sys.path)
    try:
        root = activate_workspace(checkout)
        assert root == checkout.resolve()
        assert os.environ[WORKSPACE_ENV] == str(checkout.resolve())
        assert sys.path[0] == str(checkout.resolve())
        assert str(checkout / "notebooks") in sys.path
    finally:
        sys.path[:] = original_path
        monkeypatch.delenv(WORKSPACE_ENV, raising=False)


def test_packaged_example_resolves_without_source_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(WORKSPACE_ENV, raising=False)
    info = resolve_mei_source_info(
        "camat/examples/facsimile_viewer_demo.mei", repo_root=tmp_path
    )
    assert info is not None
    assert info.kind == "packaged"
    assert info.local_path.is_file()
    assert "facsimile_viewer_demo.mei" in info.local_path.name
    assert (info.local_path.parent / "facsimile_viewer_demo.svg").is_file()


def _notebook_code(name: str) -> str:
    notebook = json.loads((NOTEBOOKS / name).read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )


@pytest.mark.parametrize(
    "name",
    [
        "camat_formats.ipynb",
        "camat_batch_conversion.ipynb",
        "mei_render.ipynb",
        "mei_facsimile_viewer.ipynb",
        "cloud_setup.ipynb",
    ],
)
def test_cloud_notebooks_use_prepare_notebook(name: str) -> None:
    code = _notebook_code(name)
    assert "prepare_notebook" in code
    assert "Run this notebook from a CAMAT source checkout" not in code


def test_conversion_notebooks_do_not_require_local_package_tree() -> None:
    for name in ("camat_formats.ipynb", "camat_batch_conversion.ipynb"):
        code = _notebook_code(name)
        assert "camat / '__init__.py'" not in code
        assert "CAMAT source checkout" not in code
