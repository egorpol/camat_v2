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

## Facsimile acquisition

::: camat.facsimile_downloader
    options:
      members:
        - collect_mei_files
        - infer_bsb_id
        - resolve_width_for_stem
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
