#!/usr/bin/env python3
"""Fetch BSB IIIF metadata for DdT volumes listed in a CSV file."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import ssl
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MANIFEST_URL = "https://api.digitale-sammlungen.de/iiif/presentation/v2/{zend_id}/manifest"
VIEWER_URL = "https://digitale-sammlungen.de/en/view/{zend_id}"
USER_AGENT = "camat-corpus-metadata-fetcher/1.0"
SYSTEM_CA_BUNDLES = (
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/ssl/cert.pem"),
    Path("/etc/pki/tls/certs/ca-bundle.crt"),
)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.parts.append("|")

    def text(self) -> str:
        text = " ".join(self.parts)
        text = re.sub(r"\s*\|\s*", " | ", text)
        return re.sub(r"\s+", " ", text).strip()


def clean_html(value: str) -> str:
    parser = TextExtractor()
    parser.feed(html.unescape(value))
    text = parser.text()
    return text if text else re.sub(r"\s+", " ", html.unescape(value)).strip()


def localized_text(value: Any, preferred: str = "en") -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return clean_html(value)
    if isinstance(value, dict):
        return localized_text(value.get("@value") or value.get("value") or value.get("label"), preferred)
    if isinstance(value, list):
        chosen = None
        for item in value:
            if isinstance(item, dict) and item.get("@language") == preferred:
                chosen = item
                break
        if chosen is None:
            chosen = value[0] if value else None
        return localized_text(chosen, preferred)
    return str(value)


def read_input_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    header_index = None
    for index, row in enumerate(rows):
        if row and row[0].strip() == "DdT Folge":
            header_index = index
            break
    if header_index is None:
        raise ValueError(f"Could not find DdT header row in {path}")

    header = rows[header_index]
    records = []
    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * (len(header) - len(row))
        records.append(dict(zip(header, padded[: len(header)])))
    return records


def ssl_context(cafile: Path | None) -> ssl.SSLContext:
    if cafile:
        return ssl.create_default_context(cafile=str(cafile))
    for candidate in SYSTEM_CA_BUNDLES:
        if candidate.exists():
            return ssl.create_default_context(cafile=str(candidate))
    return ssl.create_default_context()


def fetch_manifest(zend_id: str, timeout: float, context: ssl.SSLContext) -> dict[str, Any]:
    request = Request(MANIFEST_URL.format(zend_id=zend_id), headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=context) as response:
        return json.load(response)


def metadata_map(manifest: dict[str, Any]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for item in manifest.get("metadata", []):
        label = localized_text(item.get("label"))
        value = localized_text(item.get("value"))
        if not label or not value:
            continue
        grouped.setdefault(label, [])
        if value not in grouped[label]:
            grouped[label].append(value)
    return {label: " | ".join(values) for label, values in grouped.items()}


def identifiers(metadata: dict[str, str]) -> dict[str, str]:
    result = {"bsb_system_id": "", "bv_from_bsb": "", "worldcat": "", "other_identifiers": ""}
    others: list[str] = []
    for value in metadata.get("Identifier", "").split(" | "):
        value = value.strip()
        if not value:
            continue
        if value.startswith("BSB-ID"):
            result["bsb_system_id"] = value.replace("BSB-ID", "", 1).strip()
        elif re.fullmatch(r"BV\d+", value):
            result["bv_from_bsb"] = value
        elif value.startswith("WorldCat:"):
            result["worldcat"] = value.replace("WorldCat:", "", 1).strip()
        else:
            others.append(value)
    result["other_identifiers"] = " | ".join(others)
    return result


def split_creation(creation: str) -> dict[str, str]:
    result = {"publication_place": "", "publisher": "", "publication_year": ""}
    if not creation:
        return result
    year_match = re.search(r"(\d{4})(?!.*\d{4})", creation)
    if year_match:
        result["publication_year"] = year_match.group(1)
    before_year = creation[: year_match.start()].strip(" |,;") if year_match else creation
    if " : " in before_year:
        place, publisher = before_year.split(" : ", 1)
        result["publication_place"] = place.strip()
        result["publisher"] = publisher.strip(" |,;")
    else:
        result["publication_place"] = before_year.strip()
    return result


def ddt_band(title: str, location: str) -> str:
    location_patterns = (
        r"\bDDT,\s*([0-9]+(?:[/,][0-9]+)?[A-Za-z]?)\b",
        r"\b3951(?:\s+[a-z])?-([0-9]+(?:[/,][0-9]+)?[A-Za-z]?)\b",
        r"\b347\s+[a-z]-([0-9]+(?:[/,][0-9]+)?[A-Za-z]?)\b",
    )
    for pattern in location_patterns:
        location_match = re.search(pattern, location)
        if location_match:
            return location_match.group(1)
    title_match = re.search(r"\.\s*([0-9]+(?:/[0-9]+)?[A-Za-z]?)\s*$", title)
    if title_match:
        return title_match.group(1)
    return ""


def first_thumbnail(manifest: dict[str, Any]) -> str:
    thumbnail = manifest.get("thumbnail", {})
    if isinstance(thumbnail, dict):
        return thumbnail.get("@id", "")
    if isinstance(thumbnail, list) and thumbnail and isinstance(thumbnail[0], dict):
        return thumbnail[0].get("@id", "")
    return ""


def build_row(source_row: dict[str, str], manifest: dict[str, Any]) -> dict[str, str]:
    zend_id = source_row.get("ZEND ID", "").strip()
    metadata = metadata_map(manifest)
    ids = identifiers(metadata)
    creation = metadata.get("Creation", "")
    publication = split_creation(creation)
    title = metadata.get("Title", "")
    location = metadata.get("Location", "")
    see_also = manifest.get("seeAlso", [])
    marcxml_url = ""
    opac_url = ""
    for item in see_also:
        if isinstance(item, dict) and item.get("label") == "MARCXML":
            marcxml_url = item.get("@id", "")
            opac_url = marcxml_url.split("?", 1)[0]

    return {
        "ddt_folge": source_row.get("DdT Folge", "").strip(),
        "ddt_band": ddt_band(title, location),
        "bv_nummer_input": source_row.get("BV-Nummer", "").strip(),
        "zend_id": zend_id,
        "manifest_label": localized_text(manifest.get("label")),
        "title": title,
        "preferred_title_of_work": metadata.get("Preferred title of work", ""),
        "composer": metadata.get("Composer", ""),
        "by": metadata.get("By", ""),
        "editor": metadata.get("Editor", ""),
        "creation": creation,
        **publication,
        "extent": metadata.get("Extent", ""),
        "language": metadata.get("Language", ""),
        "location": location,
        "bsb_system_id": ids["bsb_system_id"],
        "bv_nummer_bsb": ids["bv_from_bsb"],
        "worldcat": ids["worldcat"],
        "other_identifiers": ids["other_identifiers"],
        "urn": metadata.get("URN", ""),
        "media_type": metadata.get("Media type", ""),
        "nav_date": manifest.get("navDate", ""),
        "license": " | ".join(manifest.get("license", [])),
        "attribution": localized_text(manifest.get("attribution")),
        "manifest_url": MANIFEST_URL.format(zend_id=zend_id),
        "viewer_url": VIEWER_URL.format(zend_id=zend_id),
        "opac_url": opac_url,
        "marcxml_url": marcxml_url,
        "thumbnail_url": first_thumbnail(manifest),
        "fetch_status": "ok",
        "fetch_error": "",
    }


def error_row(source_row: dict[str, str], error: Exception) -> dict[str, str]:
    zend_id = source_row.get("ZEND ID", "").strip()
    row = {
        "ddt_folge": source_row.get("DdT Folge", "").strip(),
        "ddt_band": "",
        "bv_nummer_input": source_row.get("BV-Nummer", "").strip(),
        "zend_id": zend_id,
        "manifest_label": "",
        "title": "",
        "preferred_title_of_work": "",
        "composer": "",
        "by": "",
        "editor": "",
        "creation": "",
        "publication_place": "",
        "publisher": "",
        "publication_year": "",
        "extent": "",
        "language": "",
        "location": "",
        "bsb_system_id": "",
        "bv_nummer_bsb": "",
        "worldcat": "",
        "other_identifiers": "",
        "urn": "",
        "media_type": "",
        "nav_date": "",
        "license": "",
        "attribution": "",
        "manifest_url": MANIFEST_URL.format(zend_id=zend_id),
        "viewer_url": VIEWER_URL.format(zend_id=zend_id),
        "opac_url": "",
        "marcxml_url": "",
        "thumbnail_url": "",
        "fetch_status": "error",
        "fetch_error": str(error),
    }
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="metadata/DdT_BSB_IDs.csv", type=Path)
    parser.add_argument("--output", default="metadata/DdT_BSB_metadata.csv", type=Path)
    parser.add_argument("--cafile", type=Path, help="CA bundle for HTTPS verification")
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--retries", default=2, type=int)
    parser.add_argument("--sleep", default=0.1, type=float)
    args = parser.parse_args()

    source_rows = read_input_rows(args.input)
    output_rows = []
    context = ssl_context(args.cafile)
    for index, source_row in enumerate(source_rows, start=1):
        zend_id = source_row.get("ZEND ID", "").strip()
        try:
            last_error: Exception | None = None
            for attempt in range(args.retries + 1):
                try:
                    manifest = fetch_manifest(zend_id, args.timeout, context)
                    break
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                    last_error = exc
                    if attempt == args.retries:
                        raise
                    time.sleep(max(args.sleep, 0.5))
            else:
                raise RuntimeError(last_error or f"Failed to fetch {zend_id}")
            output_rows.append(build_row(source_row, manifest))
            print(f"[{index}/{len(source_rows)}] {zend_id} ok")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            output_rows.append(error_row(source_row, exc))
            print(f"[{index}/{len(source_rows)}] {zend_id} error: {exc}")
        if args.sleep and index < len(source_rows):
            time.sleep(args.sleep)

    fieldnames = list(output_rows[0].keys()) if output_rows else []
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"Wrote {len(output_rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
