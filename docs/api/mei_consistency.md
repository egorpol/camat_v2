---
title: MEI consistency and cleanup
---

# MEI consistency and cleanup

The checker and report helpers are read-only. Functions that can change an MEI
file expose an explicit `apply` argument or are named as cleanup/copy
operations. `run_relaxng_validation(...)` uses the packaged schema and requires
the `xmllint` executable. The Workflow 1 guide explains how these layers fit
together.

Check results are meant to be reviewed from **CSV/JSON reports** produced by
`run_checker(...)` and `run_editorial_checks(...)`. CAMAT also integrates
`annotate_mei_from_report(...)` to write selected rows into MEI `<annot>`
elements, but mei-friend's per-score annotation display limit (default 100)
makes CSV the practical hand-off for large reports; see
[Handling MEI files — Check, combine, and review reports](../guides/edition-building.md#annot-export-integrated-csv-preferred).

## Consistency checker

::: camat.check_mei_consistency
    options:
      members:
        - Finding
        - MeiChecker
        - check_mei_files
        - strip_ppq_text
        - strip_accid_ges_text
        - main

## Workflow and report helpers

::: camat.mei_consistency_workflow
    options:
      members:
        - MEI_CMN_51_SCHEMA
        - CleanupResult
        - SchemaValidationResult
        - VerovioLogResult
        - resolve_mei_inputs
        - prepare_pages_for_combine
        - combine_meis
        - apply_safe_cleanup
        - normalize_single_layer_number_copies
        - run_checker
        - run_editorial_checks
        - facsimile_graphic_targets
        - iiif_graphic_target_rows
        - figured_bass_report_rows
        - page_break_facs_report_rows
        - run_relaxng_validation
        - run_verovio_warning_check
        - annotate_mei_from_report
        - load_report
        - report_summary
        - source_snippet

## Figured-bass anchors

::: camat.convert_harm_startid_to_tstamp
    options:
      members:
        - HarmConversion
        - ConversionResult
        - convert_file
        - normalize_figured_bass_accidentals
        - main

## Page-break facsimile links

::: camat.link_pb_to_surface
    options:
      members:
        - PbSurfaceRow
        - PbSurfaceResult
        - analyze_file
        - link_file
        - main
