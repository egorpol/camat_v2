#!/usr/bin/env python3
"""Build and test the installed CAMAT wheel in fresh Python virtual environments.

Examples
--------
Run the complete supported matrix, failing if an interpreter is unavailable::

    python scripts/test_release_matrix.py

Run one version with an explicit interpreter::

    python scripts/test_release_matrix.py --versions 3.14 --python 3.14=/usr/bin/python3.14

The runner owns only ``.release-venvs``, ``.release-dist``, and
``.release-runs`` under the repository root. By default it deletes and
recreates those paths so every release check is a clean wheel installation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_ROOT = REPO_ROOT / ".release-venvs"
DIST_ROOT = REPO_ROOT / ".release-dist"
RUN_ROOT = REPO_ROOT / ".release-runs"
RELEASE_TEST = REPO_ROOT / "tests" / "release" / "test_installed_package.py"
SUPPORTED_VERSIONS = ("3.11", "3.12", "3.13", "3.14")


def _run(command: Sequence[str | Path], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    printable = " ".join(str(part) for part in command)
    print(f"\n+ {printable}", flush=True)
    subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd),
        env=env,
        check=True,
    )


def _reset_owned_path(path: Path) -> None:
    resolved = path.resolve()
    allowed = {ENV_ROOT.resolve(), DIST_ROOT.resolve(), RUN_ROOT.resolve()}
    allowed_parents = {ENV_ROOT.resolve(), RUN_ROOT.resolve()}
    if resolved not in allowed and resolved.parent not in allowed_parents:
        raise RuntimeError(f"Refusing to reset path outside release-owned roots: {resolved}")
    if path.exists():
        shutil.rmtree(path)


def _venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _reported_version(interpreter: str | Path) -> str | None:
    try:
        result = subprocess.run(
            [str(interpreter), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _conda_interpreters() -> dict[str, Path]:
    conda = shutil.which("conda")
    if not conda:
        return {}
    try:
        result = subprocess.run(
            [conda, "env", "list", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        env_paths = [Path(value) for value in json.loads(result.stdout).get("envs", [])]
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {}

    discovered: dict[str, Path] = {}
    for version in SUPPORTED_VERSIONS:
        compact = version.replace(".", "")
        ranked = sorted(
            env_paths,
            key=lambda path: (
                path.name != f"py{compact}",
                not path.name.startswith(f"py{compact}"),
                len(path.name),
                path.name,
            ),
        )
        for env_path in ranked:
            if not env_path.name.startswith(f"py{compact}"):
                continue
            candidate = env_path / ("python.exe" if os.name == "nt" else "bin/python")
            if candidate.exists() and _reported_version(candidate) == version:
                discovered[version] = candidate
                break
    return discovered


def _parse_overrides(values: Iterable[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--python expects VERSION=EXECUTABLE, received {value!r}")
        version, executable = value.split("=", 1)
        version = version.strip()
        executable = executable.strip()
        if version not in SUPPORTED_VERSIONS or not executable:
            raise ValueError(f"Invalid interpreter override: {value!r}")
        overrides[version] = executable
    return overrides


def _find_interpreters(versions: Sequence[str], overrides: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    conda = _conda_interpreters()
    found: dict[str, str] = {}
    missing: list[str] = []
    for version in versions:
        compact = version.replace(".", "")
        configured = overrides.get(version) or os.environ.get(f"CAMAT_PYTHON_{compact}")
        candidates: list[str | Path] = []
        if configured:
            candidates.append(configured)
        system_python = shutil.which(f"python{version}")
        if system_python:
            candidates.append(system_python)
        if version in conda:
            candidates.append(conda[version])

        selected = None
        for candidate in candidates:
            resolved = shutil.which(str(candidate)) or str(candidate)
            if _reported_version(resolved) == version:
                selected = resolved
                break
        if selected is None:
            missing.append(version)
        else:
            found[version] = selected
    return found, missing


def _build_wheel(*, reuse: bool) -> Path:
    build_env = ENV_ROOT / "build"
    if not reuse:
        _reset_owned_path(build_env)
        _reset_owned_path(DIST_ROOT)
    build_env.parent.mkdir(parents=True, exist_ok=True)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "venv", build_env], cwd=REPO_ROOT)
    python = _venv_python(build_env)
    _run([python, "-m", "pip", "install", "--upgrade", "pip"], cwd=REPO_ROOT)
    _run([python, "-m", "pip", "install", "-r", REPO_ROOT / "requirements-release.txt"], cwd=REPO_ROOT)
    _run([python, "-m", "build", "--wheel", "--outdir", DIST_ROOT], cwd=REPO_ROOT)
    wheels = sorted(DIST_ROOT.glob("camat-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"Expected exactly one CAMAT wheel in {DIST_ROOT}, found {wheels}")
    _run([python, "-m", "twine", "check", wheels[0]], cwd=REPO_ROOT)
    return wheels[0]


def _test_version(version: str, interpreter: str, wheel: Path, *, reuse: bool) -> None:
    env_dir = ENV_ROOT / f"py{version.replace('.', '')}"
    run_dir = RUN_ROOT / f"py{version.replace('.', '')}"
    if not reuse:
        _reset_owned_path(env_dir)
        _reset_owned_path(run_dir)
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    _run([interpreter, "-m", "venv", env_dir], cwd=REPO_ROOT)
    python = _venv_python(env_dir)
    _run([python, "-m", "pip", "install", "--upgrade", "pip"], cwd=run_dir)
    _run([python, "-m", "pip", "install", "-r", REPO_ROOT / "requirements-test.txt"], cwd=run_dir)
    _run([python, "-m", "pip", "install", "--force-reinstall", wheel], cwd=run_dir)
    _run([python, "-m", "pip", "check"], cwd=run_dir)

    test_env = dict(os.environ)
    test_env.pop("CAMAT_PARSER", None)
    test_env.update(
        {
            "CAMAT_REPO_ROOT": str(REPO_ROOT),
            "MPLCONFIGDIR": str(run_dir / "matplotlib"),
            "PYTHONNOUSERSITE": "1",
        }
    )
    _run(
        [
            python,
            "-m",
            "pytest",
            "-q",
            "--disable-warnings",
            "--maxfail=1",
            "--import-mode=importlib",
            f"--rootdir={run_dir}",
            RELEASE_TEST,
        ],
        cwd=run_dir,
        env=test_env,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions",
        nargs="+",
        default=list(SUPPORTED_VERSIONS),
        choices=SUPPORTED_VERSIONS,
        help="Python versions to test (default: the complete supported matrix).",
    )
    parser.add_argument(
        "--python",
        action="append",
        default=[],
        metavar="VERSION=EXECUTABLE",
        help="Override interpreter discovery; may be supplied more than once.",
    )
    parser.add_argument(
        "--wheel",
        type=Path,
        help="Test an existing wheel instead of building one.",
    )
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="Reuse release environments. The default is a clean rebuild and reinstall.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip unavailable interpreters instead of failing the matrix.",
    )
    args = parser.parse_args(argv)

    overrides = _parse_overrides(args.python)
    interpreters, missing = _find_interpreters(args.versions, overrides)
    if missing and not args.allow_missing:
        print(
            "Missing required Python interpreter(s): " + ", ".join(missing) + ".\n"
            "Install them, provide --python VERSION=EXECUTABLE, or use --allow-missing for a partial local run.",
            file=sys.stderr,
        )
        return 2
    if missing:
        print("Skipping unavailable interpreter(s): " + ", ".join(missing))
    if not interpreters:
        print("No requested Python interpreters are available.", file=sys.stderr)
        return 2

    if not args.reuse:
        _reset_owned_path(RUN_ROOT)
    wheel = args.wheel.resolve() if args.wheel else _build_wheel(reuse=args.reuse)
    if not wheel.is_file() or wheel.suffix != ".whl":
        print(f"Wheel does not exist: {wheel}", file=sys.stderr)
        return 2

    failures: dict[str, str] = {}
    for version in args.versions:
        interpreter = interpreters.get(version)
        if not interpreter:
            continue
        print(f"\n{'=' * 72}\nTesting CAMAT wheel on Python {version}: {interpreter}\n{'=' * 72}")
        try:
            _test_version(version, interpreter, wheel, reuse=args.reuse)
        except subprocess.CalledProcessError as exc:
            failures[version] = f"command exited with status {exc.returncode}"
        except Exception as exc:  # keep the matrix running to report all versions
            failures[version] = f"{type(exc).__name__}: {exc}"

    print(f"\n{'=' * 72}\nRelease matrix summary\n{'=' * 72}")
    for version in args.versions:
        if version in failures:
            print(f"Python {version}: FAIL ({failures[version]})")
        elif version in interpreters:
            print(f"Python {version}: PASS")
        else:
            print(f"Python {version}: SKIPPED")
    print(f"Wheel: {wheel}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
