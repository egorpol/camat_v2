"""Copy tutorial notebooks without cloning the whole CAMAT repository.

The PyPI package does not include Jupyter notebooks or ``test_corpus/``
fixtures. Cloud Jupyter sessions (Colab, Jupyter4NFDI, Binder, and similar)
should install CAMAT, then fetch only those tutorial paths.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import shutil
import subprocess
import sys

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
    """Clone only the tutorial notebooks and example corpus into ``dest``.

    ``dest`` defaults to ``./camat_tutorials``. An existing tutorial workspace
    or source checkout at that path is reused. The clone prefers the git tag
    matching the installed CAMAT version, then ``main``.
    """
    dest_path = Path(dest or Path.cwd() / DEFAULT_DEST_NAME).expanduser().resolve()
    if is_source_checkout(dest_path) or is_tutorial_workspace(dest_path):
        return activate_workspace(dest_path)
    if dest_path.exists():
        raise FileExistsError(
            f"{dest_path} already exists and is not a CAMAT tutorial workspace. "
            "Choose another directory or remove it first."
        )

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
        help="Git branch or tag (default: installed camat version, then main)",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help="Git remote to copy from",
    )
    args = parser.parse_args(argv)
    _warn_python_version()
    root = fetch_tutorial_workspace(args.dest, repo=args.repo, ref=args.ref)
    print(f"Tutorial workspace: {root}")
    print(f"Open notebooks in:  {root / 'notebooks'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
