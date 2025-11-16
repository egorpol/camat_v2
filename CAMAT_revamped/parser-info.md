# Parser Data Flow Notes

`py_scripts/parser_registry.py` normalizes `PARSING_BACKEND` (`music21` or `partitura`) and forwards every option to the selected backend. Both backends share the same downstream helpers (`filter_and_adjust_durations`, `draw_piano_roll`, TSV export), so the main behavioral differences stem from how the libraries ingest each score format.

## MEI

### music21 backend
- Files are parsed through `music21.converter.parse`, flattened via `extract_voice_data`, then normalized in `music21_backend.parse_files` (`CAMAT_revamped/py_scripts/music21_backend.py:124-205`).
- xml:id data is **not** preserved by music21’s MEI importer. We keep a nullable `xml_id` column filled with `pd.NA` whenever `include_xml_ids=True` to maintain schema compatibility.
- Ties may be merged (`strip_ties=True` default), which can change note segmentation relative to partitura.
- `ALIGN_ACCIDENT_SCHEMA` is the only cross-backend harmonization knob and simply re-spells pitches after parsing.

### partitura backend
- Files go through `_sanitize_source_for_partitura` and `_load_partitura_score`, ensuring MEI text, humdrum quirks, and encodings are cleaned before parsing.
- `partitura_score_to_dataframe` (`CAMAT_revamped/py_scripts/partitura_backend.py:214-439`) keeps the MEI structure intact and surfaces `xml_id`, `note_id`, etc., so MEI ids populate the dataframe reliably when `include_xml_ids=True`.
- When a non-MEI source is parsed but the caller still requests xml ids, the backend now emits an `xml_id` column filled with `pd.NA` to preserve schema compatibility.
- Subsequent processing (duration filtering, piano-roll rendering) mirrors the music21 backend.

## MusicXML files (`.xml` / `.musicxml`)

### music21 backend
- Standard use case for music21: `converter.parse` reads MusicXML directly, we extract measure/onset/duration/pitch/voice, compute MIDI, and optionally canonicalize enharmonic spellings.
- Tie stripping, hover fields, and visualization behave exactly as with MEI.

### partitura backend
- MusicXML is loaded via `importmusicxml.load_musicxml` first; failures fall back to `pt.load_score`.
- When `include_xml_ids=True`, we still add the column but fill it with `pd.NA` because those identifiers are not present in MusicXML exports. Otherwise the pipeline (enharmonic parsing, accidental alignment, piano rolls) matches the MEI flow.

## Humdrum/Kern files (`.krn`, `.kern`, `.hum`)

### music21 backend
- `music21.converter.parse` attempts to read the text-based source directly. Once parsed, data extraction mirrors the MusicXML path; no xml-id data is expected.
- Because humdrum imports go through the same `extract_voice_data` routine, alignments/tie stripping behave exactly like other formats.

### partitura backend
- Kern inputs are pre-cleaned in `_sanitize_source_for_partitura` (BOM removal, comment stripping, removing troublesome `*part` lines) before calling `importkern.load_kern(..., force_same_part=True)`.
- The resulting `partitura` score is converted to the dataframe identical to other formats. If `include_xml_ids=True`, we output an `xml_id` column of `pd.NA` values since humdrum/kern do not expose MEI-style identifiers.

## Shared behaviors
- Both backends round/truncate durations/onsets through `filter_and_adjust_durations`, sort rows by `Global Onset`, and compute measure offsets for plotting.
- `ALIGN_ACCIDENT_SCHEMA` is applied within each backend after parsing; enabling it yields consistent pitch spelling between pipelines regardless of source format.
- Hover metadata, piano-roll rendering, TSV export, and downstream notebooks operate on whichever dataframe the chosen backend emits.
