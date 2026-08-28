"""
generate_volume_pages.py
------------------------
Fetches metadata from the BSB IIIF Presentation API for each volume listed in
metadata/bsb_ids.txt, generates a markdown page per volume in metadata/, and
rewrites metadata/ddt_volumes.md with links to all generated pages.

Usage (run from the repository root):
    camat-generate-volume-pages
"""

import argparse
import re
import time
from pathlib import Path

import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────

METADATA_DIR = Path("metadata")
BSB_IDS_FILE = METADATA_DIR / "bsb_ids.txt"
VOLUMES_INDEX = METADATA_DIR / "ddt_volumes.md"
DELAY = 0.5  # polite delay in seconds between IIIF requests

# ── END CONFIG ────────────────────────────────────────────────────────────────

IIIF_MANIFEST = "https://api.digitale-sammlungen.de/iiif/presentation/v2/{bsb_id}/manifest"


def strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)  # <br/> → space
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text.strip()


def clean_person(text: str) -> str:
    """Strip GND/authority annotations like '-- (GND: 118917447)' from person names."""
    text = re.sub(r"\s*--\s*\(GND:[^)]*\)", "", text)
    text = re.sub(r"\s*\(GND:[^)]*\)", "", text)
    return text.strip()


def _coerce_str(v) -> str:
    """Flatten a IIIF label/value that may be a str, list, or language-map dict."""
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        # Language-tagged object {"@value": "...", "@language": "de"} or language map {"en": [...]}
        v = v.get("@value") or next(iter(v.values()), "")
        if isinstance(v, list):
            v = v[0] if v else ""
    return str(v) if v else ""


def get_meta_value(metadata: list, *labels: str) -> str:
    """
    Return the first non-empty value whose label matches any of the given labels
    (case-insensitive). Handles string, list, and language-map IIIF v2 formats.
    """
    label_set = {lbl.lower() for lbl in labels}
    for item in metadata:
        raw_label = _coerce_str(item.get("label", ""))
        if raw_label.lower() in label_set:
            value = _coerce_str(item.get("value", ""))
            return strip_html(value)
    return ""


def short_title(full_title: str) -> str:
    """Return the portion of the title before the first colon."""
    if ":" in full_title:
        return full_title.split(":")[0].strip()
    return full_title.strip()


def composer_display(raw_composer: str) -> str:
    """
    Return a display name for the composer field:
    - Multiple composers (separated by ; or ' und ' or ' and '): return 'Various'
    - Single composer: return last name only
      Handles both 'Firstname Lastname' and 'Lastname, Firstname' formats.
    """
    if not raw_composer:
        return ""
    # Detect multiple composers
    if any(sep in raw_composer for sep in (";", " und ", " and ", " & ")):
        return "Various"
    # Single composer — extract last name
    name = raw_composer.strip()
    if "," in name:
        # "Scheidt, Samuel" → "Scheidt"
        return name.split(",")[0].strip()
    # "Samuel Scheidt" → "Scheidt"
    return name.split()[-1] if name else ""


def fetch_manifest(bsb_id: str) -> dict:
    url = IIIF_MANIFEST.format(bsb_id=bsb_id)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_meta(manifest: dict) -> dict:
    """Pull the fields we need from a IIIF v2 manifest."""
    md = manifest.get("metadata", [])

    # Try common English and German label variants used by BSB
    title = (
        get_meta_value(md, "Title", "Titel")
        or strip_html(str(manifest.get("label", "")))
    )
    composer = clean_person(get_meta_value(md, "Creator", "Urheber", "Composer", "Author"))
    editor = clean_person(get_meta_value(md, "Contributor", "Beteiligte Person(en)", "Editor", "Herausgeber"))

    # BSB uses a "Creation"/"Entstehung" field for place/publisher/year
    publication = get_meta_value(md, "Creation", "Entstehung", "Publication", "Erscheinungsvermerk", "Imprint")
    if not publication:
        place = get_meta_value(md, "Place of publication", "Erscheinungsort", "Place")
        publisher = get_meta_value(md, "Publisher", "Verlag")
        date = get_meta_value(md, "Date", "Erscheinungsjahr", "Year")
        parts = []
        if place:
            parts.append(place)
        if publisher:
            parts.append(f": {publisher}")
        if date:
            parts.append(date)
        publication = " ".join(parts)

    urn = get_meta_value(md, "Identifier", "URN", "Persistent identifier")
    # BSB sometimes puts the URN inside a longer identifier string; extract it
    urn_match = re.search(r"urn:nbn:de:[^\s<\"]+", urn)
    urn = urn_match.group(0) if urn_match else urn

    return {
        "title": title,
        "composer": composer,
        "editor": editor,
        "publication": publication,
        "urn": urn,
    }


def build_markdown(bsb_id: str, meta: dict) -> str:
    """Render the metadata dict as a markdown page."""
    title = meta["title"]
    composer = meta["composer"]
    editor = meta["editor"]
    publication = meta["publication"]
    urn = meta["urn"]

    display = composer_display(composer)
    heading = f"{display}: {short_title(title)}" if display else short_title(title)

    by_line = composer
    if editor:
        by_line += f". Hrsg. von {editor}"

    permalink_url = f"https://mdz-nbn-resolving.de/details:{bsb_id}"
    permalink_label = urn if urn else f"urn:nbn:de:bvb:12-{bsb_id}-0"

    lines = [f"# {heading}", ""]
    if title:
        lines += [f"**Title:** {title}", ""]
    if by_line:
        lines += [f"**By:** {by_line}", ""]
    if publication:
        lines += [f"**Edition:** {publication}", ""]
    lines += [f"**Permalink:** [{permalink_label}]({permalink_url})", ""]

    return "\n".join(lines)


def series_from_id(bsb_id: str) -> str:
    if bsb_id.startswith("bsb00023"):
        return "DdT 1"
    if bsb_id.startswith("bsb00064"):
        return "DdT 2"
    return "Unknown"


def slugify(text: str) -> str:
    """Lowercase, strip accents/punctuation, replace spaces with underscores."""
    text = text.lower()
    # Replace common accented chars and ß
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^\w\s]", "", text)   # remove remaining punctuation
    text = re.sub(r"\s+", "_", text.strip())
    return text



SERIES_NUM = {"DdT 1": "01", "DdT 2": "02"}


def make_filename(bsb_id: str, series: str, band_num: int, meta: dict) -> str:
    """
    Generate the output .md filename from metadata.
    Pattern: {series_nn}_{band_nn}_{composer_slug}_{title_slug}_{bsb_id}.md
    """
    series_prefix = SERIES_NUM.get(series, "00")
    display = composer_display(meta["composer"])
    composer_slug = slugify(display) if display else ""
    title_slug = slugify(short_title(meta["title"]))
    parts = [series_prefix, f"{band_num:02d}"]
    if composer_slug:
        parts.append(composer_slug)
    parts += [title_slug, bsb_id]
    return "_".join(parts) + ".md"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        default=METADATA_DIR,
        help="Directory for generated pages (default: metadata)",
    )
    parser.add_argument(
        "--bsb-ids",
        type=Path,
        help="BSB id list (default: METADATA_DIR/bsb_ids.txt)",
    )
    parser.add_argument(
        "--index",
        type=Path,
        help="Volume index output (default: METADATA_DIR/ddt_volumes.md)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DELAY,
        help=f"Delay between IIIF requests (default: {DELAY})",
    )
    return parser


def main(argv=None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.delay < 0:
        parser.error("--delay must be >= 0")

    metadata_dir = args.metadata_dir
    bsb_ids_file = args.bsb_ids or metadata_dir / BSB_IDS_FILE.name
    volumes_index = args.index or metadata_dir / VOLUMES_INDEX.name
    metadata_dir.mkdir(parents=True, exist_ok=True)
    bsb_ids = [line.strip() for line in bsb_ids_file.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    total = len(bsb_ids)
    print(f"Found {total} BSB IDs\n")

    entries: dict[str, list[tuple[str, str]]] = {"DdT 1": [], "DdT 2": [], "Unknown": []}
    band_counters: dict[str, int] = {"DdT 1": 0, "DdT 2": 0, "Unknown": 0}
    created = skipped = errors = 0

    for i, bsb_id in enumerate(bsb_ids, 1):
        series = series_from_id(bsb_id)
        band_counters[series] += 1
        band_num = band_counters[series]

        try:
            manifest = fetch_manifest(bsb_id)
            meta = extract_meta(manifest)
            time.sleep(args.delay)
        except Exception as e:
            print(f"[{i}/{total}] ERROR {bsb_id}: {e}")
            errors += 1
            continue

        filename = make_filename(bsb_id, series, band_num, meta)
        out_file = metadata_dir / filename
        existing = out_file.exists()

        composer = meta["composer"]
        title = meta["title"]
        display = composer_display(composer)
        link_text = f"{display}: {short_title(title)}" if display else short_title(title)
        entries[series].append((link_text, filename))

        if existing:
            print(f"[{i}/{total}] SKIP  {filename} (already exists)")
            skipped += 1
            continue

        content = build_markdown(bsb_id, meta)
        out_file.write_text(content, encoding="utf-8")
        print(f"[{i}/{total}] OK    {filename}")
        created += 1

    # Rewrite metadata/ddt_volumes.md
    index_lines = ["# Volumes of DdT", ""]
    for section in ["DdT 1", "DdT 2"]:
        if not entries[section]:
            continue
        index_lines += [f"## {section}", ""]
        for link_text, filename in entries[section]:
            index_lines.append(f"[{link_text}]({filename})")
            index_lines.append("")

    volumes_index.write_text("\n".join(index_lines), encoding="utf-8")
    print(f"\nUpdated {volumes_index}")
    print(f"Finished — created: {created}, skipped (already exist): {skipped}, errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
