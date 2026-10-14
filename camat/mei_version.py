"""Prepare conservative MEI 5.1 text edits without serializing an XML tree.

The returned candidate still needs RELAX NG validation before publication.
Retained text keeps its original bytes, apart from repeat-list indentation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from html import unescape
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat


MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_NAME = rb"[^\s/<>='\"]+"
_START_TAG = re.compile(rb"<(" + _NAME + rb")(?:[^<>\"']|\"[^\"]*\"|'[^']*')*/?>")
_ATTRIBUTE = re.compile(
    rb"\s+(?P<name>" + _NAME + rb")\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)


@dataclass
class MeiVersionRewriteResult:
    """A candidate text and report fields; only validation can mark it rewritten.

    ``text`` is ``None`` when no candidate can be built or no edit is needed. A
    candidate's ``status`` remains ``incomplete`` until its caller validates it.
    Refusals can accompany a candidate containing all other safe edits.
    Counts describe constructs found/attempted, even if the candidate is refused.
    """

    text: str | None = None
    status: str = "incomplete"
    source_mei_version: str | None = None
    rewrites: dict[str, int] = field(default_factory=lambda: {
        "meiversion": 0,
        "mrest_to_mspace": 0,
        "choice_unwrapped": 0,
        "dynam_enclose_dropped": 0,
    })
    dynam_enclose_dropped: list[dict[str, str]] = field(default_factory=list)
    unrewritable: list[dict[str, str | None]] = field(default_factory=list)
    remaining_errors: list[dict[str, str | None]] = field(default_factory=list)
    remaining_errors_total: int = 0

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe report fields, excluding the candidate text."""
        report = asdict(self)
        del report["text"]
        return report


@dataclass
class _TagSpan:
    start: int
    end: int
    name: bytes
    close_start: int | None = None
    close_end: int | None = None


def _parse(data: bytes) -> tuple[ET.Element, dict[ET.Element, _TagSpan]]:
    builder = ET.TreeBuilder(insert_comments=True, insert_pis=True)
    parser = expat.ParserCreate(namespace_separator="}")
    spans: dict[ET.Element, _TagSpan] = {}
    stack: list[ET.Element] = []

    def qname(name: str) -> str:
        return "{" + name if "}" in name else name

    def start(name: str, attributes: dict[str, str]) -> None:
        element = builder.start(qname(name), {qname(k): v for k, v in attributes.items()})
        match = _START_TAG.match(data, parser.CurrentByteIndex)
        if match is None:
            raise ValueError("Cannot locate parsed XML start tag.")
        spans[element] = _TagSpan(match.start(), match.end(), match[1])
        stack.append(element)

    def end(name: str) -> None:
        span = spans[stack.pop()]
        if not data[span.start:span.end].endswith(b"/>"):
            span.close_start = parser.CurrentByteIndex
            span.close_end = data.index(b">", span.close_start) + 1
        builder.end(qname(name))

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    parser.CommentHandler = builder.comment
    parser.ProcessingInstructionHandler = builder.pi
    # Entity expansions could have no unique location in the original text.
    def reject_doctype(*_args) -> None:
        raise ValueError("DOCTYPE declarations are not supported for text rewriting.")

    parser.StartDoctypeDeclHandler = reject_doctype
    parser.Parse(data, True)
    return builder.close(), spans


def _attribute_edit(data: bytes, span: _TagSpan, name: bytes, value: bytes | None) -> tuple[int, int, bytes]:
    matches = [m for m in _ATTRIBUTE.finditer(data, span.start, span.end) if m["name"] == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name.decode()} attribute in anchored tag.")
    match = matches[0]
    if value is None:
        return match.start(), match.end(), b""
    return match.start("value"), match.end("value"), value


def _tag_line(data: bytes, start: int, end: int) -> tuple[int, int] | None:
    """Locate a whole line containing only the tag and XML whitespace."""
    line_start = data.rfind(b"\n", 0, start) + 1
    newline = data.find(b"\n", end)
    line_end = len(data) if newline < 0 else newline + 1
    if data[line_start:start].strip(b" \t\r\n") or data[end:line_end].strip(b" \t\r\n"):
        return None
    return line_start, line_end


def rewrite_mei_version(text: str, target: str = "5.1") -> MeiVersionRewriteResult:
    """Prepare the agreed Verovio artefact rewrites for a MEI 5.1 target.

    Parsing selects the elements; edits use unique ``xml:id`` anchors in the
    original text, including occurrences in comments and CDATA. Verovio's root
    normally has no ID, so its complete start tag must instead be unique.
    Candidates contain all safe edits even when another target is refused.
    Standalone repeat wrappers lose their lines and their expansions use the
    choice's indentation; compact layouts and comments retain their whitespace.
    Schema validation and file I/O belong to the caller, which must preserve
    the original if any target is refused or the candidate is invalid.
    """
    if target != "5.1":
        raise ValueError("mei_version must be '5.1'.")
    result = MeiVersionRewriteResult()
    data = text.encode("utf-8")
    try:
        root, spans = _parse(data)
    except (expat.ExpatError, ValueError) as exc:
        result.remaining_errors = [{"element": "mei", "message": str(exc)}]
        result.remaining_errors_total = 1
        return result
    result.source_mei_version = root.get("meiversion")

    def mei(name: str) -> str:
        return f"{{{MEI_NS}}}{name}"

    if root.tag != mei("mei"):
        result.remaining_errors = [{"element": "mei", "message": "Root is not an MEI mei element."}]
    elif result.source_mei_version == "5.1":
        result.status = "not_needed"
        return result
    elif result.source_mei_version != "6.0-dev":
        result.remaining_errors = [{
            "element": "mei",
            "message": f"Cannot rewrite source meiversion={result.source_mei_version!r}; expected '6.0-dev'.",
        }]
    if result.remaining_errors:
        result.remaining_errors_total = len(result.remaining_errors)
        return result

    parents = {child: parent for parent in root.iter() for child in parent}
    anchors: Counter[str] = Counter()
    for match in _START_TAG.finditer(data):
        for attribute in _ATTRIBUTE.finditer(data, match.start(), match.end()):
            if attribute["name"] == b"xml:id":
                anchors[unescape(attribute["value"].decode("utf-8"))] += 1
    references = {
        token[1:]
        for element in root.iter()
        for value in element.attrib.values()
        for token in value.split()
        if token.startswith("#")
    }
    edits: list[tuple[int, int, bytes]] = []

    def refuse(element: ET.Element, reason: str) -> None:
        result.unrewritable.append({
            "xml_id": element.get(XML_ID),
            "element": str(element.tag).rsplit("}", 1)[-1],
            "reason": reason,
        })

    def anchored(element: ET.Element) -> bool:
        xml_id = element.get(XML_ID)
        if not xml_id:
            refuse(element, "Target element has no xml:id anchor.")
            return False
        if anchors[xml_id] != 1:
            refuse(element, f"xml:id anchor {xml_id!r} has {anchors[xml_id]} matches; expected exactly one.")
            return False
        return True

    result.rewrites["meiversion"] = 1
    root_span = spans[root]
    if root.get(XML_ID):
        root_ok = anchored(root)
    else:
        root_ok = data.count(data[root_span.start:root_span.end]) == 1
        if not root_ok:
            refuse(root, "Root start-tag anchor is not unique; expected exactly one match.")
    if root_ok:
        edits.append(_attribute_edit(data, root_span, b"meiversion", b"5.1"))

    for element in root.iter():
        if element.tag == mei("mRest") and element.get("visible") == "false":
            result.rewrites["mrest_to_mspace"] += 1
            if not anchored(element):
                continue
            span = spans[element]
            name = span.name.rsplit(b":", 1)[0] + b":mSpace" if b":" in span.name else b"mSpace"
            edits.append((span.start + 1, span.start + 1 + len(span.name), name))
            edits.append(_attribute_edit(data, span, b"visible", None))
            if span.close_start is not None:
                edits.append((span.close_start + 2, span.close_start + 2 + len(span.name), name))

        elif element.tag == mei("dynam") and "enclose" in element.attrib:
            ancestor = parents.get(element)
            while ancestor is not None and ancestor.tag != mei("supplied"):
                ancestor = parents.get(ancestor)
            if ancestor is None:
                refuse(element, "dynam/@enclose outside supplied is not rewritten.")
                continue
            result.rewrites["dynam_enclose_dropped"] += 1
            if anchored(element):
                result.dynam_enclose_dropped.append({
                    "xml_id": element.attrib[XML_ID],
                    "text": "".join(element.itertext()),
                    "enclose": element.attrib["enclose"],
                })
                edits.append(_attribute_edit(data, spans[element], b"enclose", None))

        elif (
            element.tag == mei("choice")
            and parents.get(element) is not None
            and parents[element].tag == mei("section")
            and any(child.tag == mei("expansion") for child in element.iter())
        ):
            result.rewrites["choice_unwrapped"] += 1
            wrappers = [child for child in element if child.tag is not ET.Comment]
            children = {
                wrapper: [child for child in wrapper if child.tag is not ET.Comment]
                for wrapper in wrappers
            }
            if (
                not wrappers or (element.text or "").strip()
                or any((child.tail or "").strip() for child in element)
                or any(
                    wrapper.tag not in {mei("orig"), mei("reg")}
                    or len(children[wrapper]) != 1 or children[wrapper][0].tag != mei("expansion")
                    or (wrapper.text or "").strip()
                    or any((child.tail or "").strip() for child in wrapper)
                    for wrapper in wrappers
                )
            ):
                refuse(element, "Repeat-list choice must contain only orig/reg wrappers, each with one expansion and no other content.")
                continue
            removable = [element, *wrappers]
            safe = True
            for wrapper in removable:
                if not anchored(wrapper):
                    safe = False
                if wrapper.get(XML_ID) in references:
                    refuse(wrapper, "An attribute references this removed wrapper's xml:id.")
                    safe = False
                expansions = [children[w][0] for w in wrappers] if wrapper is element else [children[wrapper][0]]
                if any(
                    attribute != XML_ID and any(child.get(attribute) != value for child in expansions)
                    for attribute, value in wrapper.attrib.items()
                ):
                    refuse(wrapper, "Wrapper attribute information is not preserved on each child expansion.")
                    safe = False
                # Namespace declarations are absent from parsed attributes.
                span = spans[wrapper]
                namespaces = {
                    m["name"]: unescape(m["value"].decode("utf-8"))
                    for m in _ATTRIBUTE.finditer(data, span.start, span.end)
                    if m["name"] == b"xmlns" or m["name"].startswith(b"xmlns:")
                }
                for child in expansions:
                    child_span = spans[child]
                    child_attributes = {
                        m["name"]: unescape(m["value"].decode("utf-8"))
                        for m in _ATTRIBUTE.finditer(data, child_span.start, child_span.end)
                    }
                    if any(child_attributes.get(name) != value for name, value in namespaces.items()):
                        refuse(wrapper, "Wrapper namespace information is not preserved on the child expansion.")
                        safe = False
                        break
            if safe:
                wrapper_tags = []
                for wrapper in removable:
                    span = spans[wrapper]
                    wrapper_tags.append((span.start, span.end))
                    if span.close_start is not None:
                        assert span.close_end is not None
                        wrapper_tags.append((span.close_start, span.close_end))
                wrapper_lines = [_tag_line(data, start, end) for start, end in wrapper_tags]
                for (start, end), line in zip(wrapper_tags, wrapper_lines):
                    edits.append((*(line or (start, end)), b""))
                if all(line is not None for line in wrapper_lines):
                    choice_span = spans[element]
                    choice_line = wrapper_lines[0]
                    assert choice_line is not None
                    indentation = data[choice_line[0]:choice_span.start]
                    for wrapper in wrappers:
                        expansion = children[wrapper][0]
                        span = spans[expansion]
                        line = _tag_line(data, span.start, span.end)
                        if line is not None and data[line[0]:span.start] != indentation and anchored(expansion):
                            edits.append((line[0], span.start, indentation))

    chunks: list[bytes] = []
    position = 0
    for start, end, replacement in sorted(edits):
        if start < position:
            result.remaining_errors = [{"element": "mei", "message": "Overlapping text edits were refused."}]
            result.remaining_errors_total = 1
            return result
        chunks.extend((data[position:start], replacement))
        position = end
    chunks.append(data[position:])
    result.text = b"".join(chunks).decode("utf-8")
    return result
