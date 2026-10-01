"""Execute embedded MEI Schematron using SchXslt 1.10.1 and SaxonC.

No network access is needed. The official RNG is never rewritten. A separate
extracted schema, compiled XSLT, and per-input SVRL are retained for inspection.
"""
from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path

SCH = "http://purl.oclc.org/dsdl/schematron"
SVRL = "http://purl.oclc.org/dsdl/svrl"
MEI = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
COMPILER = Path(__file__).parent / "schemas" / "schxslt"
COMPILER_VERSION = "1.10.1"
EXTRACTION_VERSION = "3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compiler_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(COMPILER.rglob("*.xsl")):
        digest.update(path.relative_to(COMPILER).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def extract_schematron(schema: Path) -> tuple[bytes, int]:
    """Preserve namespace bindings, pattern-local variables, and assertion text."""
    from lxml import etree

    tree = etree.parse(str(schema), etree.XMLParser(resolve_entities=False, no_network=True))
    original = tree.getroot()
    if original.tag == f"{{{SCH}}}schema":
        extracted = copy.deepcopy(original)
    else:
        # Namespace declarations on embedded patterns must survive detachment.
        extracted = etree.Element(f"{{{SCH}}}schema", nsmap={"sch": SCH, "mei": MEI})
        extracted.set("queryBinding", "xslt2")
        extracted.append(etree.Element(f"{{{SCH}}}ns", prefix="mei", uri=MEI))
        for child in original.iter():
            if not isinstance(child.tag, str) or not child.tag.startswith(f"{{{SCH}}}"):
                continue
            if any(isinstance(p.tag, str) and p.tag.startswith(f"{{{SCH}}}") for p in child.iterancestors()):
                continue
            extracted.append(copy.deepcopy(child))
    extracted.set("{http://www.w3.org/XML/1998/namespace}base", schema.resolve().as_uri())
    # These MEI schemas are self-contained. Reject external include graphs rather
    # than cache a validator without recording all of its dependent rule bytes.
    if extracted.findall(f".//{{{SCH}}}include"):
        raise ValueError("External Schematron includes are not supported; supply a self-contained schema.")
    bindings = {node.get("prefix"): node.get("uri") for node in extracted.findall(f"{{{SCH}}}ns")}
    for node in original.iter():
        if not isinstance(node.tag, str) or not node.tag.startswith(f"{{{SCH}}}"):
            continue
        for prefix, uri in node.nsmap.items():
            if prefix and prefix not in {"sch", "xml"}:
                if prefix in bindings and bindings[prefix] != uri:
                    raise ValueError(f"Conflicting Schematron namespace binding: {prefix}")
                bindings[prefix] = uri
    for prefix, uri in sorted(bindings.items()):
        if not any(n.get("prefix") == prefix for n in extracted.findall(f"{{{SCH}}}ns")):
            extracted.insert(0, etree.Element(f"{{{SCH}}}ns", prefix=prefix, uri=uri))
    for node in extracted.iter():
        if node.tag not in {f"{{{SCH}}}assert", f"{{{SCH}}}report"} or node.get("id"):
            continue
        context = [(ancestor.get("id", ""), ancestor.get("context", "")) for ancestor in node.iterancestors()]
        identity = repr((context, node.tag, node.get("test"), node.get("role"), "".join(node.itertext())))
        node.set("id", "mei.sch." + hashlib.sha256(identity.encode()).hexdigest()[:16])
    count = len(extracted.findall(f".//{{{SCH}}}assert")) + len(extracted.findall(f".//{{{SCH}}}report"))
    if not count:
        raise ValueError("Schema extraction produced zero Schematron assertions/reports.")
    return etree.tostring(extracted, xml_declaration=True, encoding="utf-8"), count


def _location_xpath(location: str) -> str:
    # SchXslt emits XPath 3 EQNames; lxml requires XPath 1 node tests.
    return re.sub(r"Q\{([^}]*)\}([\w.-]+)",
                  lambda m: f"*[local-name()='{m[2]}' and namespace-uri()='{m[1]}']", location)


def run_schematron_validation(files, *, schema: Path, output_dir: Path) -> dict:
    from lxml import etree
    try:
        from saxonche import PySaxonProcessor
    except ImportError as exc:
        raise RuntimeError("Install CAMAT's validation extra (saxonche) to execute Schematron.") from exc

    files = list(files)
    if not files:
        raise ValueError("No inputs selected for Schematron.")
    schema = Path(schema).resolve()
    output_dir = Path(output_dir).resolve()
    extracted, rule_count = extract_schematron(schema)
    with PySaxonProcessor(license=False) as processor:
        key = hashlib.sha256((sha256(schema) + hashlib.sha256(extracted).hexdigest() + compiler_hash() + processor.version + EXTRACTION_VERSION).encode()).hexdigest()
        cache = output_dir / "cache" / key
        cache.mkdir(parents=True, exist_ok=True)
        sch_path = cache / "rules.sch"
        xsl_path = cache / "validator.xsl"
        sch_path.write_bytes(extracted)
        xslt = processor.new_xslt30_processor()
        if not xsl_path.is_file():
            compiler = xslt.compile_stylesheet(stylesheet_file=str(COMPILER / "pipeline-for-svrl.xsl"))
            compiler.transform_to_file(source_file=str(sch_path.resolve()), output_file=str(xsl_path.resolve()))
        executable = xslt.compile_stylesheet(stylesheet_file=str(xsl_path.resolve()))
        rows, svrl_paths = [], []
        failed_assertions = 0
        error_assertions = 0
        for index, path in enumerate(files):
            path = Path(path).resolve()
            document = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))
            svrl_path = output_dir / f"{index:04d}-{path.stem}.svrl.xml"
            executable.transform_to_file(source_file=str(path), output_file=str(svrl_path.resolve()))
            report = etree.parse(str(svrl_path))
            if report.getroot().tag != f"{{{SVRL}}}schematron-output":
                raise RuntimeError("Schematron processor did not return SVRL.")
            svrl_paths.append(str(svrl_path.resolve()))
            for item in report.getroot().iter():
                if item.tag not in {f"{{{SVRL}}}failed-assert", f"{{{SVRL}}}successful-report"}:
                    continue
                failed = item.tag.endswith("failed-assert")
                failed_assertions += int(failed)
                role = item.get("role", "").lower()
                severity = role if role in {"error", "warning", "info"} else ("error" if failed else "warning")
                error_assertions += int(failed and severity == "error")
                location = item.get("location", "")
                element = None
                try:
                    matches = document.xpath(_location_xpath(location))
                    if matches:
                        element = matches[0]
                        if not hasattr(element, "tag"):
                            element = element.getparent()
                except etree.XPathError:
                    pass
                context = {}
                if element is not None:
                    for tag in ("measure", "staff", "layer"):
                        ancestors = element.xpath(f"ancestor-or-self::*[local-name()='{tag}']")
                        context[tag + "_n"] = ancestors[-1].get("n", "") if ancestors else ""
                rows.append({
                    "severity": severity, "category": "schematron", "origin": "MEI Schematron",
                    "check": item.get("id") or ("schematron_assert" if failed else "schematron_report"),
                    "file": str(path), "line": element.sourceline if element is not None else None,
                    "element": etree.QName(element).localname if element is not None else "",
                    "xml_id": element.get(XML_ID, "") if element is not None else "",
                    "message": " ".join("".join(item.itertext()).split()),
                    "expected": item.get("test", ""), "actual": location, "context": location,
                    **context,
                })
        return {"rows": rows, "failed_assertions": failed_assertions, "error_assertions": error_assertions, "rule_count": rule_count,
                "compiler": {"name": "SchXslt", "version": COMPILER_VERSION, "sha256": compiler_hash()},
                "processor": processor.version, "extracted_schema_sha256": hashlib.sha256(extracted).hexdigest(),
                "compiled_validator_sha256": sha256(xsl_path), "svrl": svrl_paths}
