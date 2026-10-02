"""Copy tutorial notebooks without cloning the whole CAMAT repository.

The PyPI package does not include Jupyter notebooks or ``test_corpus/``
fixtures. Install CAMAT, then fetch only those tutorial paths. The public
GitHub repository is downloaded as a source archive, so that step uses the
Python standard library.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request

WORKSPACE_ENV = "CAMAT_WORKSPACE"
DEFAULT_REPO = "https://github.com/egorpol/camat_v2.git"
DEFAULT_DEST_NAME = "camat_tutorials"
TUTORIAL_PATHS = ("notebooks", "test_corpus")

__all__ = [
    "DEFAULT_DEST_NAME",
    "DEFAULT_REPO",
    "TUTORIAL_PATHS",
    "WORKSPACE_ENV",
    "activate_workspace",
    "fetch_tutorial_workspace",
    "find_camat_root",
    "is_source_checkout",
    "is_tutorial_workspace",
    "locate_workspace",
    "main",
    "prepare_notebook",
]


def is_source_checkout(path: Path) -> bool:
    """Return whether ``path`` is a CAMAT git checkout with package sources."""
    root = path.resolve()
    return (root / "pyproject.toml").is_file() and (root / "camat" / "__init__.py").is_file()


def is_tutorial_workspace(path: Path) -> bool:
    """Return whether ``path`` has the tutorial notebooks and example corpus."""
    root = path.resolve()
    return (root / "notebooks").is_dir() and (root / "test_corpus").is_dir()


def locate_workspace(start: Path | None = None) -> Path | None:
    """Return the nearest source checkout or tutorial workspace, if any."""
    env = os.environ.get(WORKSPACE_ENV, "").strip()
    if env:
        env_path = Path(env).expanduser().resolve()
        if env_path.is_dir() and (
            is_source_checkout(env_path) or is_tutorial_workspace(env_path)
        ):
            return env_path

    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if is_source_checkout(candidate) or is_tutorial_workspace(candidate):
            return candidate
    return None


def find_camat_root(start: Path | None = None) -> Path:
    """Return the CAMAT checkout or tutorial workspace, else ``start`` / cwd.

    Jupyter may start in ``notebooks/``. Cloud sessions that copied only
    ``notebooks/`` and ``test_corpus/`` are valid workspaces even without a
    local ``camat/`` source tree.
    """
    start = (start or Path.cwd()).resolve()
    return locate_workspace(start) or start


def activate_workspace(root: Path) -> Path:
    """Record ``root`` for later path resolution and local imports."""
    resolved = root.resolve()
    os.environ[WORKSPACE_ENV] = str(resolved)
    notebooks = resolved / "notebooks"
    if notebooks.is_dir() and str(notebooks) not in sys.path:
        sys.path.insert(0, str(notebooks))
    if (resolved / "camat" / "__init__.py").is_file() and str(resolved) not in sys.path:
        sys.path.insert(0, str(resolved))
    return resolved


def _enable_colab_widgets() -> None:
    try:
        from google.colab import output
    except ImportError:
        return
    try:
        output.enable_custom_widget_manager()
    except Exception:
        return


def _warn_python_version() -> None:
    if sys.version_info < (3, 11):
        print(
            f"CAMAT requires Python 3.11 or later; this session is "
            f"{sys.version.split()[0]}. Pick a newer runtime before installing.",
            file=sys.stderr,
        )


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        env=env,
        text=True,
        capture_output=True,
    )


def _ref_candidates(ref: str | None) -> list[str]:
    if ref:
        return [ref]
    version = None
    try:
        from importlib.metadata import version as distribution_version

        version = distribution_version("camat")
    except Exception:
        try:
            from camat import __version__ as version
        except Exception:
            version = None
    candidates: list[str] = []
    if version:
        candidates.append(f"v{version}")
        candidates.append(version)
    candidates.append("main")
    return candidates


_GITHUB_HTTPS = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"
)
_GITHUB_SSH = re.compile(
    r"^git@github\.com:(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?$"
)


class _ArchiveNotFound(Exception):
    """The GitHub source archive for this ref is missing."""


def _parse_github_repo(repo: str) -> tuple[str, str] | None:
    """Return ``(owner, name)`` for a GitHub remote, else ``None``."""
    text = repo.strip()
    match = _GITHUB_HTTPS.fullmatch(text) or _GITHUB_SSH.fullmatch(text)
    if match is None:
        return None
    return match.group("owner"), match.group("name")


def _github_archive_urls(owner: str, name: str, ref: str) -> list[str]:
    quoted = urllib.parse.quote(ref, safe="")
    base = f"https://codeload.github.com/{owner}/{name}/tar.gz"
    return [
        f"{base}/refs/tags/{quoted}",
        f"{base}/refs/heads/{quoted}",
    ]


def _download_url(url: str, dest: Path, *, timeout: float = 120) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "camat-fetch-tutorials"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with dest.open("wb") as handle:
            shutil.copyfileobj(response, handle)


def _download_github_ref(owner: str, name: str, ref: str, dest: Path) -> None:
    errors: list[str] = []
    for url in _github_archive_urls(owner, name, ref):
        try:
            _download_url(url, dest)
        except urllib.error.HTTPError as exc:
            if dest.exists():
                dest.unlink()
            errors.append(f"HTTP {exc.code} {url}")
            continue
        return
    detail = "; ".join(errors) or "no archive URL"
    raise _ArchiveNotFound(detail)


def _tutorial_member_rel(name: str, paths: Sequence[str]) -> Path | None:
    """Return the workspace-relative path for one archive member."""
    pure = PurePosixPath(name)
    parts = pure.parts
    if not parts or pure.is_absolute() or ".." in parts:
        return None
    wanted = set(paths)
    if parts[0] in wanted:
        rel_parts = parts
    elif len(parts) >= 2 and parts[1] in wanted:
        rel_parts = parts[1:]
    else:
        return None
    return Path(*rel_parts)


def _extract_tutorial_archive(
    archive: Path,
    dest: Path,
    paths: Sequence[str],
) -> None:
    """Extract ``paths`` from a GitHub source archive into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            rel = _tutorial_member_rel(member.name, paths)
            if rel is None:
                continue
            target = (dest / rel).resolve()
            if not target.is_relative_to(root):
                continue
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isreg():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)


def _fetch_github_archive(
    dest: Path,
    owner: str,
    name: str,
    ref: str | None,
    paths: Sequence[str],
) -> Path:
    errors: list[str] = []
    candidates = _ref_candidates(ref)
    for candidate in candidates:
        if dest.exists():
            shutil.rmtree(dest)
        print(f"Downloading CAMAT tutorials ({candidate})...", flush=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "source.tar.gz"
                _download_github_ref(owner, name, candidate, archive)
                try:
                    _extract_tutorial_archive(archive, dest, paths)
                except tarfile.TarError as exc:
                    errors.append(f"{candidate}: {exc}")
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    continue
        except _ArchiveNotFound as exc:
            errors.append(f"{candidate}: {exc}")
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            continue
        except urllib.error.URLError as exc:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(
                "Could not download CAMAT tutorial notebooks from "
                f"https://github.com/{owner}/{name}. {reason}"
            ) from exc
        if not is_tutorial_workspace(dest):
            shutil.rmtree(dest, ignore_errors=True)
            errors.append(f"{candidate}: archive has no notebooks/ or test_corpus/")
            continue
        return activate_workspace(dest)

    joined = "\n".join(errors) or "no refs tried"
    raise RuntimeError(
        "Could not download CAMAT tutorial notebooks from "
        f"https://github.com/{owner}/{name}. "
        f"Tried: {', '.join(candidates)}.\n{joined}"
    )


def _sparse_clone(repo: str, dest: Path, ref: str, paths: Sequence[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    filtered = [
        "clone",
        "--depth",
        "1",
        "--filter=blob:none",
        "--sparse",
        "--branch",
        ref,
        repo,
        str(dest),
    ]
    plain = [
        "clone",
        "--depth",
        "1",
        "--sparse",
        "--branch",
        ref,
        repo,
        str(dest),
    ]
    try:
        _git(*filtered)
    except subprocess.CalledProcessError:
        if dest.exists():
            shutil.rmtree(dest)
        _git(*plain)
    _git("sparse-checkout", "set", *paths, cwd=dest)


def fetch_tutorial_workspace(
    dest: str | Path | None = None,
    *,
    repo: str = DEFAULT_REPO,
    ref: str | None = None,
    paths: Sequence[str] = TUTORIAL_PATHS,
) -> Path:
    """Copy the tutorial notebooks and example corpus into ``dest``.

    ``dest`` defaults to ``./camat_tutorials``. An existing tutorial workspace
    or source checkout at that path is reused. A GitHub remote is downloaded
    as a source archive for the installed CAMAT version, then ``main``.
    Other remotes use a sparse git clone.
    """
    dest_path = Path(dest or Path.cwd() / DEFAULT_DEST_NAME).expanduser().resolve()
    if is_source_checkout(dest_path) or is_tutorial_workspace(dest_path):
        return activate_workspace(dest_path)
    if dest_path.exists():
        raise FileExistsError(
            f"{dest_path} already exists and is not a CAMAT tutorial workspace. "
            "Choose another directory or remove it first."
        )

    github = _parse_github_repo(repo)
    if github is not None:
        owner, name = github
        return _fetch_github_archive(dest_path, owner, name, ref, paths)

    errors: list[str] = []
    for candidate in _ref_candidates(ref):
        if dest_path.exists():
            shutil.rmtree(dest_path)
        try:
            _sparse_clone(repo, dest_path, candidate, paths)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "git is required to copy the tutorial notebooks. "
                "Install git, or clone https://github.com/egorpol/camat_v2.git."
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            errors.append(f"{candidate}: {detail}")
            if dest_path.exists():
                shutil.rmtree(dest_path)
            continue
        if not is_tutorial_workspace(dest_path):
            shutil.rmtree(dest_path, ignore_errors=True)
            errors.append(
                f"{candidate}: clone succeeded but notebooks/ or test_corpus/ is missing"
            )
            continue
        return activate_workspace(dest_path)

    joined = "\n".join(errors) or "no refs tried"
    raise RuntimeError(
        "Could not copy CAMAT tutorial notebooks from "
        f"{repo}. Tried: {', '.join(_ref_candidates(ref))}.\n{joined}"
    )


def prepare_notebook(
    *,
    fetch: bool = True,
    dest: str | Path | None = None,
    repo: str = DEFAULT_REPO,
    ref: str | None = None,
) -> Path:
    """Make this kernel ready to run a CAMAT tutorial notebook.

    Reuses a source checkout or an already copied tutorial workspace. When
    neither is visible and ``fetch`` is true, copies ``notebooks/`` and
    ``test_corpus/`` next to the current directory.
    """
    _warn_python_version()
    _enable_colab_widgets()
    root = locate_workspace()
    if root is not None:
        return activate_workspace(root)
    if not fetch:
        raise FileNotFoundError(
            "CAMAT tutorial files were not found. Install the package with "
            "`python -m pip install camat` and copy the notebooks with "
            "`camat-fetch-tutorials`, or run this notebook from a git checkout."
        )
    return fetch_tutorial_workspace(dest, repo=repo, ref=ref)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Copy CAMAT tutorial notebooks and example files without cloning "
            "the full repository."
        )
    )
    parser.add_argument(
        "dest",
        nargs="?",
        default=DEFAULT_DEST_NAME,
        help=f"Directory to create (default: {DEFAULT_DEST_NAME})",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Branch or tag (default: installed camat version, then main)",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help="GitHub repository or git remote to copy from",
    )
    args = parser.parse_args(argv)
    _warn_python_version()
    root = fetch_tutorial_workspace(args.dest, repo=args.repo, ref=args.ref)
    print(f"Tutorial workspace: {root}")
    print(f"Open notebooks in:  {root / 'notebooks'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
