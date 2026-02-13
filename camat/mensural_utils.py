from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "DEFAULT_MENSURAL_DURATION_MAP",
    "inject_default_meter_signature_in_mei_text",
    "inject_default_meter_signature_in_mei_file",
    "normalize_mensural_durations_in_mei_text",
    "normalize_mensural_durations_in_mei_file",
    "normalize_mensural_mei_for_partitura_text",
    "normalize_mensural_mei_for_partitura_file",
]


# Compatibility map from common mensural duration labels to values supported by
# partitura's MEI importer.
DEFAULT_MENSURAL_DURATION_MAP: Dict[str, str] = {
    "maxima": "long",
    "longa": "long",
    "long": "long",
    "brevis": "breve",
    "breve": "breve",
    "semibrevis": "1",
    "minima": "2",
    "semiminima": "4",
    "fusa": "8",
    "semifusa": "16",
}

DEFAULT_METER_COUNT = 4
DEFAULT_METER_UNIT = 4


def normalize_mensural_durations_in_mei_text(
    mei_text: str,
    *,
    duration_map: Optional[Mapping[str, str]] = None,
) -> Tuple[str, int, Dict[str, int]]:
    """
    Normalize mensural dur=... values in MEI text to partitura-compatible values.

    Returns:
        (normalized_text, replacement_count, replacements_by_source_token)
    """
    import re

    mapping = dict(DEFAULT_MENSURAL_DURATION_MAP if duration_map is None else duration_map)
    if not mapping:
        return mei_text, 0, {}

    normalized_map = {str(k).strip().lower(): str(v).strip() for k, v in mapping.items()}
    counts: Dict[str, int] = {}
    replacement_count = 0

    dur_attr = re.compile(r'(\bdur\s*=\s*)(["\'])([^"\']+)(["\'])')

    def _replace(match: re.Match[str]) -> str:
        nonlocal replacement_count
        prefix, quote_open, raw_value, quote_close = match.groups()
        key = raw_value.strip().lower()
        replacement = normalized_map.get(key)
        if replacement is None:
            return match.group(0)
        replacement_count += 1
        counts[key] = counts.get(key, 0) + 1
        return f"{prefix}{quote_open}{replacement}{quote_close}"

    normalized = dur_attr.sub(_replace, mei_text)
    return normalized, replacement_count, counts


def inject_default_meter_signature_in_mei_text(
    mei_text: str,
    *,
    meter_count: int = DEFAULT_METER_COUNT,
    meter_unit: int = DEFAULT_METER_UNIT,
) -> Tuple[str, int]:
    """
    Inject default meter attributes into scoreDef/staffDef tags when missing.

    This targets partitura's MEI importer requirement for meter info.
    Returns:
        (updated_text, number_of_tags_modified)
    """
    import re

    if meter_count <= 0 or meter_unit <= 0:
        raise ValueError("meter_count and meter_unit must be positive integers")

    tags_modified = 0

    tag_pattern = re.compile(r"<(?P<name>[\w:.-]+)\b(?P<attrs>[^<>]*?)(?P<close>/?)>")
    meter_count_re = re.compile(r'\bmeter\.count\s*=\s*["\'][^"\']*["\']')
    meter_unit_re = re.compile(r'\bmeter\.unit\s*=\s*["\'][^"\']*["\']')

    def _replace(match: re.Match[str]) -> str:
        nonlocal tags_modified
        name = match.group("name")
        local = name.split(":")[-1]
        if local not in {"scoreDef", "staffDef"}:
            return match.group(0)

        attrs = match.group("attrs") or ""
        close = match.group("close") or ""
        has_count = meter_count_re.search(attrs) is not None
        has_unit = meter_unit_re.search(attrs) is not None
        if has_count and has_unit:
            return match.group(0)

        extra = ""
        if not has_count:
            extra += f' meter.count="{int(meter_count)}"'
        if not has_unit:
            extra += f' meter.unit="{int(meter_unit)}"'
        tags_modified += 1
        return f"<{name}{attrs}{extra}{close}>"

    updated = tag_pattern.sub(_replace, mei_text)
    return updated, tags_modified


def normalize_mensural_durations_in_mei_file(
    input_path: str | Path,
    *,
    output_path: Optional[str | Path] = None,
    in_place: bool = False,
    encoding: str = "utf-8",
    duration_map: Optional[Mapping[str, str]] = None,
) -> Tuple[Path, int, Dict[str, int]]:
    """
    Normalize mensural durations in an MEI file.

    If in_place is True, input file is overwritten.
    If output_path is set, writes to that path.
    Otherwise writes to a sibling file with suffix '.normalized.mei'.
    """
    src = Path(input_path)
    text = src.read_text(encoding=encoding, errors="ignore")
    normalized, replacement_count, counts = normalize_mensural_durations_in_mei_text(
        text,
        duration_map=duration_map,
    )

    if in_place:
        dst = src
    elif output_path is not None:
        dst = Path(output_path)
    else:
        dst = src.with_suffix(".normalized.mei")

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(normalized, encoding=encoding)
    return dst, replacement_count, counts


def inject_default_meter_signature_in_mei_file(
    input_path: str | Path,
    *,
    output_path: Optional[str | Path] = None,
    in_place: bool = False,
    encoding: str = "utf-8",
    meter_count: int = DEFAULT_METER_COUNT,
    meter_unit: int = DEFAULT_METER_UNIT,
) -> Tuple[Path, int]:
    """
    Inject default meter signature attributes into an MEI file.
    """
    src = Path(input_path)
    text = src.read_text(encoding=encoding, errors="ignore")
    normalized, meter_injections = inject_default_meter_signature_in_mei_text(
        text,
        meter_count=meter_count,
        meter_unit=meter_unit,
    )

    if in_place:
        dst = src
    elif output_path is not None:
        dst = Path(output_path)
    else:
        dst = src.with_suffix(".meter.mei")

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(normalized, encoding=encoding)
    return dst, meter_injections


def normalize_mensural_mei_for_partitura_text(
    mei_text: str,
    *,
    duration_map: Optional[Mapping[str, str]] = None,
    meter_count: int = DEFAULT_METER_COUNT,
    meter_unit: int = DEFAULT_METER_UNIT,
) -> Tuple[str, int, Dict[str, int], int]:
    """
    Apply both mensural duration normalization and default meter injection.

    Returns:
        (updated_text, duration_replacement_count, by_token, meter_injection_count)
    """
    out, duration_count, by_token = normalize_mensural_durations_in_mei_text(
        mei_text,
        duration_map=duration_map,
    )
    out, meter_count_added = inject_default_meter_signature_in_mei_text(
        out,
        meter_count=meter_count,
        meter_unit=meter_unit,
    )
    return out, duration_count, by_token, meter_count_added


def normalize_mensural_mei_for_partitura_file(
    input_path: str | Path,
    *,
    output_path: Optional[str | Path] = None,
    in_place: bool = False,
    encoding: str = "utf-8",
    duration_map: Optional[Mapping[str, str]] = None,
    meter_count: int = DEFAULT_METER_COUNT,
    meter_unit: int = DEFAULT_METER_UNIT,
) -> Tuple[Path, int, Dict[str, int], int]:
    """
    File-oriented wrapper for full mensural MEI normalization.
    """
    src = Path(input_path)
    text = src.read_text(encoding=encoding, errors="ignore")
    normalized, duration_count, by_token, meter_injections = normalize_mensural_mei_for_partitura_text(
        text,
        duration_map=duration_map,
        meter_count=meter_count,
        meter_unit=meter_unit,
    )

    if in_place:
        dst = src
    elif output_path is not None:
        dst = Path(output_path)
    else:
        dst = src.with_suffix(".normalized.mei")

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(normalized, encoding=encoding)
    return dst, duration_count, by_token, meter_injections


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize mensural MEI for partitura compatibility."
    )
    parser.add_argument("input", help="Input MEI file path")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output MEI file path (default: <input>.normalized.mei)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file",
    )
    parser.add_argument(
        "--meter-count",
        type=int,
        default=DEFAULT_METER_COUNT,
        help=f"Default meter.count to inject when missing (default: {DEFAULT_METER_COUNT})",
    )
    parser.add_argument(
        "--meter-unit",
        type=int,
        default=DEFAULT_METER_UNIT,
        help=f"Default meter.unit to inject when missing (default: {DEFAULT_METER_UNIT})",
    )
    args = parser.parse_args()

    if args.in_place and args.output:
        raise SystemExit("Use either --in-place or --output, not both.")

    out_path, count, by_token, meter_injections = normalize_mensural_mei_for_partitura_file(
        args.input,
        output_path=args.output,
        in_place=bool(args.in_place),
        meter_count=int(args.meter_count),
        meter_unit=int(args.meter_unit),
    )
    print(f"Wrote: {out_path}")
    print(f"Duration replacements: {count}")
    print(f"Meter injections: {meter_injections}")
    if by_token:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(by_token.items()))
        print(f"By token: {parts}")


if __name__ == "__main__":
    _main()
