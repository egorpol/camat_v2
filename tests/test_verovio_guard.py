from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from camat.verovio_guard import python_executable


def test_python_executable_prefers_a_real_python_when_sys_executable_is_not_python(
    monkeypatch,
) -> None:
    monkeypatch.setattr(sys, "executable", "/usr/local/bin/cursor")

    resolved = Path(python_executable())

    assert resolved.name.startswith("python")
    result = subprocess.run(
        [str(resolved), "-c", "import sys; print(sys.version_info[:2])"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(tuple(sys.version_info[:2]))


def test_python_executable_keeps_sys_executable_when_it_is_python(monkeypatch, tmp_path: Path) -> None:
    fake_python = tmp_path / "python3.14"
    fake_python.write_text("", encoding="utf-8")
    fake_python.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake_python))

    assert python_executable() == str(fake_python)
