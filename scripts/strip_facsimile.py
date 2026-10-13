#!/usr/bin/env python3
"""Remove one MEI <facsimile> block and the @facs tokens that pointed into it.

Edits the file as text so every other byte stays identical (line endings,
indentation, prolog and xml-model PIs included). Stdlib only.

Usage: strip_facsimile.py SOURCE OUTPUT
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(["'])(.*?)\2""", re.S)
_FACS_ATTR = re.compile(r"""(\s)facs(\s*=\s*)(["'])(.*?)\3""", re.S)
_FACSIMILE_TAG = re.compile(r"<facsimile[\s/>]")
_XML_ID = re.compile(r'\bxml:id="([^"]+)"')
_FACSIMILE_OPEN = re.compile(r"^\s*<facsimile(?:\s|>)")
_FACSIMILE_CLOSE = re.compile(r"^\s*</facsimile>\s*$")


def _facsimile_spans(lines: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        if start is None and _FACSIMILE_OPEN.match(line):
            start = index
        elif start is not None and _FACSIMILE_CLOSE.match(line):
            spans.append((start, index))
            start = None
    if start is not None:
        raise SystemExit("unclosed <facsimile> element")
    return spans


def _ids_in_block(lines: list[str], start: int, end: int) -> set[str]:
    return set(_XML_ID.findall("".join(lines[start : end + 1])))


def strip_facsimile(source: Path, output: Path) -> None:
    text = source.read_bytes().decode("utf-8")  # keep \r\n line endings
    lines = text.splitlines(keepends=True)
    tags = len(_FACSIMILE_TAG.findall(text))
    if tags > 1:
        raise SystemExit(
            f"refusing to strip: found {tags} <facsimile> elements; "
            "this script removes exactly one"
        )
    spans = _facsimile_spans(lines)
    if not spans:
        raise SystemExit("no <facsimile> block found on lines of its own")
    start, end = spans[0]
    removed_ids = _ids_in_block(lines, start, end)
    if not removed_ids:
        raise SystemExit("<facsimile> block contains no xml:id values")

    kept = lines[:start] + lines[end + 1 :]
    body = "".join(kept)
    # Any other #id reference into the removed block (@corresp, @sameas, @plist, ...) would dangle.
    for match in _ATTR.finditer(body):
        attr, _, value = match.groups()
        if attr in ("facs", "xml:id"):
            continue
        for token in value.split():
            if token.startswith("#") and token[1:] in removed_ids:
                raise SystemExit(
                    f"refusing to strip: @{attr} still references "
                    f"removed id {token[1:]!r}"
                )

    def rewrite_facs(match: re.Match[str]) -> str:
        space, equals, quote, value = match.groups()
        tokens = value.split()
        kept_tokens = [token for token in tokens if token.lstrip("#") not in removed_ids]
        if len(kept_tokens) == len(tokens):
            return match.group(0)  # unrelated @facs stays byte-identical
        if not kept_tokens:
            return ""
        return f"{space}facs{equals}{quote}{' '.join(kept_tokens)}{quote}"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_FACS_ATTR.sub(rewrite_facs, body).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("Usage: strip_facsimile.py SOURCE OUTPUT", file=sys.stderr)
        return 2
    source, output = Path(args[0]), Path(args[1])
    if not source.is_file():
        print(f"source not found: {source}", file=sys.stderr)
        return 1
    if output.exists() and output.resolve() == source.resolve():
        print("OUTPUT must differ from SOURCE", file=sys.stderr)
        return 1
    try:
        strip_facsimile(source, output)
    except SystemExit as exc:
        message = str(exc)
        if message:
            print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
