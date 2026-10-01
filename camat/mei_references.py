"""MEI URI pointer handling shared by checks and ID rewriting.

The registry lists supported MEI linkage attributes, not arbitrary strings.
Resolution follows inherited xml:base, URI escaping, and explicit document URIs.
Bare fragments remain document-local unless an assembly mode is selected.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

REFERENCE_ATTRS = frozenset({
    "facs", "startid", "endid", "target", "plist", "corresp", "sameas",
    "next", "prev", "copyof", "synch", "decls", "resp", "source",
})
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"


@dataclass(frozen=True)
class Pointer:
    uri: str
    document: Path | None
    fragment: str
    has_fragment: bool


def resolve_pointer(token: str, element, document: Path, parents: dict) -> Pointer:
    ancestors = [element]
    while ancestors[-1] in parents:
        ancestors.append(parents[ancestors[-1]])
    base = document.resolve().as_uri()
    for ancestor in reversed(ancestors):
        if ancestor.get(XML_BASE):
            base = urljoin(base, ancestor.get(XML_BASE))
    uri = urljoin(base, token)
    document_uri, fragment = urldefrag(uri)
    parts = urlsplit(document_uri)
    local = Path(unquote(parts.path)).resolve() if parts.scheme == "file" and parts.netloc in {"", "localhost"} else None
    return Pointer(uri, local, unquote(fragment), "#" in token or "#" in uri)
