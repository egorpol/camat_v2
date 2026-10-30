---
title: Edition and IIIF pipeline
---

# Edition and IIIF pipeline

These Workflow 1 modules operate on explicit MEI files or score directories.
Downloading BSB images, checking manifests, validating remote images, and
uploading to the measure detector require network access. Integration from an
existing annotation XML file is local.

## Page selection and BSB coverage

::: camat.page_filter
    options:
      members:
        - page_number_for_path
        - parse_page_ranges
        - page_in_ranges
        - filter_mei_files

::: camat.check_bsb_page_coverage
    options:
      members:
        - infer_bsb_id
        - local_stems
        - fetch_manifest_stems
        - compare_to_manifest
        - main

## Single-file and batch IIIF jobs

::: camat.iiif_page
    options:
      members:
        - IiifPagePlan
        - collect_iiif_jobs_from_directory
        - plan_iiif_page
        - plan_iiif_pages
        - integrate_iiif_page
        - integrate_iiif_pages
        - format_iiif_page_plans
        - format_iiif_page_results

## Facsimile acquisition

::: camat.facsimile_downloader
    options:
      members:
        - parse_bsb_filename_stem
        - parse_bsb_viewer_url
        - resolve_iiif_image_url
        - stage_mei_copy
        - collect_mei_files
        - infer_bsb_id
        - resolve_width_for_stem
        - download_facsimile_image
        - download_images
        - main

## Measure detection and integration

::: camat.integrate_measure_annotations
    options:
      members:
        - get_measure_alignment_report
        - validate_measure_alignment
        - integrate_facsimile
        - integrate_measure_facs
        - integrate_annotation_file
        - main

::: camat.upload_and_integrate_measure_annotations
    options:
      members:
        - DETECTOR_URL
        - SkipFile
        - build_annotation_tree
        - upload_image
        - process_mei_file
        - main

## PDF facsimiles

Render and review local PDF pages, reuse detector or manual measure boxes,
and link regions by movement, measure label and occurrence. Integration
preserves notation; writing page and system breaks is a separate operation.

::: camat.pdf_facsimile
    options:
      members:
        - POPPLER_INSTALL_HINTS
        - NON_MUSIC_PAGE_ROLES
        - check_poppler
        - render_pdf_pages
        - parse_page_layout
        - check_page_layout
        - apply_page_layout
        - detect_measure_boxes
        - edit_measure_boxes
        - group_measure_boxes_into_systems
        - build_measure_alignment
        - approve_alignment_review
        - draw_alignment_overlays
        - number_single_mdiv
        - integrate_pdf_facsimile
        - write_page_breaks
        - main

The guided notebook uses a separate presentation module with plain-language
step messages and pictures. Scripts should use `camat.pdf_facsimile` above.
The BSB example downloader is shared by both notebooks.

::: camat.pdf_facsimile_guided
    options:
      members:
        - NotDone
        - download_example_pdf
        - make_page_images
        - describe_pages
        - find_bars
        - check_bars
        - merge_with_mei
        - open_result

## Web edition

Build a static site from finished MEI files and a JSON site config; see
[From MEI to a web edition](../guides/web-edition.md) for the config keys.

::: camat.web_edition
    options:
      members:
        - SiteConfigError
        - LABELS
        - VEROVIO_OPTIONS
        - build_site
        - main

## Review pages

Build a local page to confirm corrected readings against the source; see
[Review pages](../guides/review-pages.md) for the review workflow and spec.

::: camat.review_page
    options:
      members:
        - build_review_page
        - ReviewSpecError
        - diff_events
        - main

## IIIF validation and orchestration

::: camat.validate_iiif_vs_local
    options:
      members:
        - IIIF_IMAGE_URL_TEMPLATE
        - read_image_size
        - sha256_file
        - find_image_for_stem
        - parse_graphic_from_output_mei
        - main

::: camat.run_pipeline
    options:
      members:
        - STEPS
        - step1_args
        - step2_args
        - step3_args
        - step4_args
        - step5_args
        - main

## Corpus maintenance

The migrated metadata, volume-page, and cleanup utilities remain available as
`camat.fetch_bsb_metadata`, `camat.generate_volume_pages`, and
`camat.corpus_cleanup`. Cleanup is a dry run unless `--run` is supplied and
still asks for confirmation before deleting anything.
