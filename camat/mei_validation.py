"""Read-only validation orchestration with independent execution records.

This general entry point does not select any edition's publication conventions.
Consumers and network checks are optional. Required skipped checks block a pass.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .check_mei_consistency import check_mei_files
from .mei_schematron import sha256, run_schematron_validation
from .mei_resources import image_resource_rows
from .mei_references import REFERENCE_ATTRS, resolve_pointer
from .mei_consistency_workflow import MEI_CMN_51_SCHEMA, run_relaxng_validation, run_verovio_warning_check

DEFAULT_REQUIRED = ("xml_references", "relaxng", "schematron", "resources", "input_hashes")
CHECKS = (*DEFAULT_REQUIRED, "musical_diagnostics", "image_network", "verovio", "camat_parse")


def camat_provenance() -> dict:
    package = Path(__file__).resolve().parent
    files = {p.relative_to(package).as_posix(): sha256(p)
             for p in sorted(package.rglob("*")) if p.is_file() and p.suffix in {".py", ".rng", ".xsl"}}
    record = {"module_version": getattr(sys.modules.get("camat"), "__version__", None),
              "module_path": str(package), "source_hashes": files,
              "source_tree_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
    try:
        dist = importlib.metadata.distribution("camat")
        record["distribution_version"] = dist.version
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            record["installation"] = json.loads(direct_url)
    except importlib.metadata.PackageNotFoundError:
        record["distribution_version"] = None
    if (package.parent / ".git").exists():
        def git(*args):
            result = subprocess.run(["git", "-C", str(package.parent), *args], text=True, capture_output=True)
            return result.stdout.strip() if result.returncode == 0 else None
        record.update(git_commit=git("rev-parse", "HEAD"), git_branch=git("branch", "--show-current"),
                      git_status=git("status", "--porcelain", "--untracked-files=normal"))
    return record


@dataclass
class ValidationResult:
    findings: list[dict]
    record: dict

    @property
    def passed(self) -> bool:
        return self.record["conformance"] == "passed" and self.record["required_checks_status"] == "passed"

    def write(self, output_dir: Path) -> None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, data in (("run.json", self.record), ("findings.json", self.findings)):
            temporary = output_dir / (name + "." + uuid.uuid4().hex + ".tmp")
            temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            temporary.replace(output_dir / name)
        columns = ["severity", "category", "origin", "check", "file", "line", "element", "xml_id",
                   "measure_n", "staff_n", "layer_n", "message", "expected", "actual", "context"]
        with (output_dir / "findings.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.findings)


def _summary(executions, required):
    missing = [name for name in required if name not in executions or executions[name]["status"] in {"skipped", "execution-error", "not-applicable"}]
    failed = [name for name in required if name in executions and executions[name]["status"] == "failed"]
    return "failed" if failed else ("incomplete" if missing else "passed")


def run_mei_validation(files, *, root: Path, output_dir: Path, schema: Path = MEI_CMN_51_SCHEMA,
                       profile: str = "MEI-5.1-CMN", document_mode: str = "standalone",
                       check_relaxng: bool = True, check_schematron: bool = True,
                       check_resources: bool = True, check_network: bool = False,
                       check_verovio: bool = False, check_camat_parse: bool = False,
                       verovio_render_pages: bool = True, editorial_diagnostics: bool = False,
                       group_diagnostics: bool = False,
                       parsing_backend: str = "verovio", check_ppq: bool = True,
                       required_checks=DEFAULT_REQUIRED) -> ValidationResult:
    """Return and save findings plus statuses, hashes, paths and tool identities.

    ``profile`` is a descriptive general profile name, not a DdT policy switch.
    Inputs are local, explicitly selected files. Downloading/installation is a
    separate operation. Remote graphic reachability does not decide conformance.
    """
    files = list(dict.fromkeys(Path(p).resolve() for p in files))
    root, output_dir, schema = Path(root).resolve(), Path(output_dir).resolve(), Path(schema).resolve()
    required_checks = tuple(required_checks)
    if document_mode not in {"standalone", "assembly"}:
        raise ValueError("document_mode must be standalone or assembly")
    if set(required_checks) - set(CHECKS):
        raise ValueError(f"Unknown required checks: {set(required_checks) - set(CHECKS)}")
    if any(path == output_dir or output_dir in path.parents for path in files):
        raise ValueError("Report output must not contain input MEI files; use a separate directory.")
    output_dir.mkdir(parents=True, exist_ok=True)
    before = {str(path): sha256(path) if path.is_file() else None for path in files}
    findings, executions = [], {}
    versions = {}
    for name in ("lxml", "Pillow", "saxonche", "verovio", "music21", "partitura"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    record = {"format_version": 1, "dependency_versions": versions, "started_utc": datetime.now(timezone.utc).isoformat(),
              "profile": profile, "document_mode": document_mode, "root": str(root),
              "schema": {"path": str(schema), "sha256": sha256(schema) if schema.is_file() else None},
              "camat": camat_provenance(), "python": {"version": platform.python_version(), "executable": sys.executable},
              "required_checks": list(required_checks), "executions": executions,
              "options": {"check_ppq": check_ppq, "parsing_backend": parsing_backend,
                          "check_relaxng": check_relaxng, "check_schematron": check_schematron,
                          "check_resources": check_resources, "check_network": check_network,
                          "check_verovio": check_verovio, "check_camat_parse": check_camat_parse,
                          "verovio_render_pages": verovio_render_pages, "editorial_diagnostics": editorial_diagnostics,
                          "group_diagnostics": group_diagnostics}}

    record.update(completion_status="running", conformance="incomplete",
                  required_checks_status="incomplete", consumer_diagnostics="incomplete")
    record["inputs"] = [{"path": str(path), "sha256_before": before[str(path)],
                         "sha256_after": None, "unchanged": None} for path in files]

    def checkpoint():
        ValidationResult(findings, record).write(output_dir)

    checkpoint()

    def run(name, enabled, function, *, warning_failure=False):
        entry = {"requested": enabled, "required": name in required_checks, "status": "skipped"}
        executions[name] = entry
        if not enabled:
            entry["reason"] = "Not requested."
            checkpoint()
            return
        entry.update(status="execution-error", running=True, reason="Requested check has not completed.")
        record["active_check"] = name
        checkpoint()
        try:
            result = function()
            rows = result.pop("rows", [])
            for row in rows:
                row.setdefault("origin", f"CAMAT {name}")
            findings.extend(rows)
            failed = result.pop("failed", False) or any(r.get("severity") == "error" or
                                                        (warning_failure and r.get("severity") == "warning") for r in rows)
            entry.pop("reason", None)
            status = "failed" if failed else ("passed" if result.get("applicable", True) else "not-applicable")
            entry.update(status=status, findings_count=len(rows), **result)
        except Exception as exc:
            entry.update(status="execution-error", reason=f"{type(exc).__name__}: {exc}")
            findings.append({"severity": "error", "category": "execution", "origin": "CAMAT execution",
                             "check": name + "_execution", "message": entry["reason"]})
        entry["running"] = False
        record["active_check"] = None
        checkpoint()

    core = None
    def core_pass():
        nonlocal core
        if not files:
            raise ValueError("No MEI inputs selected.")
        core = [asdict(f) for f in check_mei_files(files, root_dir=root, document_mode=document_mode, check_ppq=check_ppq,
                                                    editorial_diagnostics=editorial_diagnostics, group_diagnostics=group_diagnostics)]
        remote = []
        import xml.etree.ElementTree as ET
        for path in files:
            try:
                document = ET.parse(path).getroot()
            except ET.ParseError:
                continue
            parents = {child: parent for parent in document.iter() for child in parent}
            for element in document.iter():
                for attr, value in element.attrib.items():
                    if attr in REFERENCE_ATTRS:
                        for token in value.split():
                            pointer = resolve_pointer(token, element, path, parents)
                            if pointer.document is None:
                                remote.append({"file": str(path), "attribute": attr, "uri": pointer.uri})
        return {"rows": [r for r in core if r["category"] in {"xml", "mei", "references"}], "files_checked": len(files),
                "remote_references": remote, "remote_reference_policy": "Not fetched; local/bundle integrity only."}
    run("xml_references", True, core_pass)
    run("musical_diagnostics", True, lambda: {"rows": [r for r in (core or []) if r["category"] not in {"xml", "mei", "references"}],
                                              "failed": core is None})
    def relaxng():
        if not files:
            raise ValueError("No inputs")
        result = run_relaxng_validation(files, root=root, schema=schema)
        for row in result.rows:
            row["check"] = "relaxng_validation"
        return {"rows": result.rows,
                "tool": subprocess.run(["xmllint", "--version"], capture_output=True, text=True).stderr.strip(),
                "files_checked": len(files)}
    run("relaxng", check_relaxng, relaxng)

    def schematron():
        if not files:
            raise ValueError("No inputs")
        result = run_schematron_validation(files, schema=schema, output_dir=output_dir / "schematron")
        result["failed"] = result["error_assertions"] > 0
        return result
    run("schematron", check_schematron, schematron)
    run("resources", check_resources, lambda: image_resource_rows(files))
    run("image_network", check_network, lambda: image_resource_rows(files, check_network=True, network_only=True), warning_failure=True)

    def verovio():
        result = run_verovio_warning_check(files, root=root, render_pages=verovio_render_pages)
        return {"rows": result.rows, "version": result.version, "render_pages": verovio_render_pages,
                "files_checked": result.files_checked}
    run("verovio", check_verovio, verovio, warning_failure=True)

    def parse():
        from .parser_registry import parse_files_quiet
        rows, counts = [], []
        for path in files:
            results, tables, _ = parse_files_quiet(
                [str(path)], parsing_backend=parsing_backend, backend="none",
                display_preview_df_pitch=False, display_preview_df_events=False,
                show_progress=False, return_plots=False,
            )
            if not results or not tables or all(table.empty for table in tables.values()):
                rows.append({"severity": "error", "category": "consumer", "check": "empty_camat_parse",
                             "file": str(path), "message": "Consumer returned no event table for this score."})
            counts.append({"file": str(path), "event_rows": sum(len(table) for table in tables.values())})
        return {"rows": rows, "backend": parsing_backend, "counts": counts}
    run("camat_parse", check_camat_parse, parse)
    after = {str(path): sha256(path) if path.is_file() else None for path in files}
    record["inputs"] = [{"path": str(path), "sha256_before": before[str(path)], "sha256_after": after[str(path)],
                          "unchanged": before[str(path)] is not None and before[str(path)] == after[str(path)]} for path in files]
    run("input_hashes", True, lambda: {"rows": [], "failed": not files or any(not item["unchanged"] for item in record["inputs"])})
    record["conformance"] = _summary(executions, DEFAULT_REQUIRED)
    record["required_checks_status"] = _summary(executions, required_checks)
    record["consumer_diagnostics"] = _summary(executions, ("verovio", "camat_parse"))
    record["completion_status"] = "completed"
    record["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result = ValidationResult(findings, record)
    result.write(output_dir)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--schema", type=Path, default=MEI_CMN_51_SCHEMA)
    parser.add_argument("--profile", default="MEI-5.1-CMN")
    parser.add_argument("--document-mode", choices=("standalone", "assembly"), default="standalone")
    parser.add_argument("--no-relaxng", action="store_true")
    parser.add_argument("--no-schematron", action="store_true")
    parser.add_argument("--no-resources", action="store_true")
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--verovio", action="store_true")
    parser.add_argument("--camat-parse", action="store_true")
    parser.add_argument("--parsing-backend", default="verovio")
    args = parser.parse_args(argv)
    result = run_mei_validation(args.files, root=Path.cwd(), output_dir=args.output_dir, schema=args.schema,
                                profile=args.profile, document_mode=args.document_mode,
                                check_relaxng=not args.no_relaxng, check_schematron=not args.no_schematron,
                                check_resources=not args.no_resources, check_network=args.network,
                                check_verovio=args.verovio, check_camat_parse=args.camat_parse,
                                parsing_backend=args.parsing_backend)
    print(f"MEI conformance: {result.record['conformance']}; consumers: {result.record['consumer_diagnostics']}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
