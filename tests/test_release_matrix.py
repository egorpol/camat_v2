from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from scripts import test_release_matrix as runner


def test_validation_report_accepts_executed_tests(tmp_path: Path) -> None:
    report = tmp_path / "results.xml"
    report.write_text('<testsuites><testsuite><testcase name="valid"/><testcase name="invalid"/></testsuite></testsuites>')
    runner._require_complete_test_report(report)


@pytest.mark.parametrize("outcome", ["skipped", "failure", "error"])
def test_validation_report_rejects_incomplete_tests(tmp_path: Path, outcome: str) -> None:
    report = tmp_path / "results.xml"
    report.write_text(f'<testsuites><testsuite><testcase name="validation"><{outcome}/></testcase></testsuite></testsuites>')
    with pytest.raises(RuntimeError, match="without skips"):
        runner._require_complete_test_report(report)


def test_validation_report_rejects_empty_run(tmp_path: Path) -> None:
    report = tmp_path / "results.xml"
    report.write_text('<testsuites><testsuite tests="0"/></testsuites>')
    with pytest.raises(RuntimeError, match="no test results"):
        runner._require_complete_test_report(report)


@pytest.mark.parametrize("validation", [False, True])
def test_wheel_runner_selects_validation_extra_and_enforces_report(tmp_path: Path, monkeypatch, validation: bool) -> None:
    monkeypatch.setattr(runner, "ENV_ROOT", tmp_path / "envs")
    monkeypatch.setattr(runner, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k skip_everything")
    commands = []

    def run(command, *, cwd, env=None):
        commands.append([str(part) for part in command])
        if "pytest" in command:
            assert "PYTEST_ADDOPTS" not in env
            assert cwd == runner.RUN_ROOT / "py314"
            if validation:
                (cwd / "validation-results.xml").write_text(
                    '<testsuites><testsuite><testcase name="missing_validator"><skipped/></testcase></testsuite></testsuites>'
                )

    monkeypatch.setattr(runner, "_run", run)
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="[]"))
    wheel = tmp_path / "camat-0.2.4-py3-none-any.whl"
    wheel.write_bytes(b"abc")
    if validation:
        with pytest.raises(RuntimeError, match="missing_validator"):
            runner._test_version("3.14", "python", wheel, reuse=False, validation=True)
    else:
        runner._test_version("3.14", "python", wheel, reuse=False)
    extras = "test,validation" if validation else "test"
    assert any(f"{wheel}[{extras}]" in command for command in commands)
    pytest_command = next(command for command in commands if "pytest" in command)
    assert "-I" in pytest_command and "--import-mode=importlib" in pytest_command
    assert str(runner.RELEASE_TEST) in pytest_command
    for path in runner.VALIDATION_TESTS:
        assert (str(path) in pytest_command) == validation
    assert json.loads((runner.RUN_ROOT / "py314" / "tested-wheel.json").read_text()) == {
        "filename": wheel.name,
        "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    }


@pytest.mark.parametrize("failure", [False, True])
def test_validation_gate_failure_controls_matrix_exit(tmp_path: Path, monkeypatch, failure: bool) -> None:
    monkeypatch.setattr(runner, "RUN_ROOT", tmp_path / "runs")
    monkeypatch.setattr(runner, "_find_interpreters", lambda *args: ({"3.14": "python"}, []))
    wheel = tmp_path / "camat-0.2.4-py3-none-any.whl"
    wheel.touch()

    def test_version(version, interpreter, selected_wheel, *, reuse, validation):
        assert version == "3.14" and selected_wheel == wheel
        assert validation and not reuse
        if failure:
            raise RuntimeError("Validation tests skipped")

    monkeypatch.setattr(runner, "_test_version", test_version)
    assert runner.main(["--validation", "--versions", "3.14", "--wheel", str(wheel)]) == int(failure)
