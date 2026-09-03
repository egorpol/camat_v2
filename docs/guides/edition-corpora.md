---
title: Edition corpora
---
# Edition corpora

CAMAT's MEI and editorial workflows were developed while encoding volumes of
*Denkmäler deutscher Tonkunst* and dealing with the problems that work raised:
page-level OMR, IIIF facsimiles and measure zones, assembly into work-level
scores, publication headers, correction in
[mei-friend](https://mei-friend.mdw.ac.at/), and automated consistency checks.

The reusable tooling lives in this package (Workflow 1:
[Handling MEI files](edition-building.md)). The MEI files themselves live in
separate work-in-progress edition repositories. Those repositories are the
source of the editorial problems; CAMAT is the toolbox that grew out of them.

Tutorial notebooks in this checkout use small portable examples under
`test_corpus/`. Point the same notebooks at a clone of an edition repository
when you are working on a volume.

## Volumes in progress

### DdT 1, vol. 11 — Buxtehude instrumental works

Repository: [`egorpol/DdT_1_vol_11`](https://github.com/egorpol/DdT_1_vol_11)

A work-in-progress scholarly MEI edition of *Dietrich Buxtehudes
Instrumentalwerke: Sonaten für Violine, Gambe und Cembalo*, edited by Carl
Stiehl (Leipzig: Breitkopf und Härtel, 1903). Fourteen sonatas in two opus
groups plus three appendix works. Encoding is MEI 5.1 CMN, one file per
complete sonata or appendix work, with IIIF-linked surfaces and measure
zones.

|                       |                                                                                                                                                                                                      |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Digital facsimile     | [BSB `bsb00023199`](https://digitale-sammlungen.de/en/view/bsb00023199)                                                                                                                             |
| Work-level MEI        | `11_buxtehude_sonatas_final/`                                                                                                                                                                      |
| Page-level OMR source | `11_buxtehude_dietrich_buxtehudes_instrumentalwerke_bsb00023199/`                                                                                                                                  |
| Editorial notes       | [editorial workflow](https://github.com/egorpol/DdT_1_vol_11/blob/main/docs/editorial-workflow.md), [encoding profile](https://github.com/egorpol/DdT_1_vol_11/blob/main/docs/mei-encoding-profile.md) |

Several sonatas are already **corrected**; others are **combined** and still
under review; a few remain **pending**. The repository README keeps the
work-by-work table current.

### DdT 1, vol. 29/30 — Instrumentalkonzerte deutscher Meister

Repository: [`egorpol/DdT_1_vol_29_30`](https://github.com/egorpol/DdT_1_vol_29_30)

Work-in-progress MEI for *Instrumentalkonzerte deutscher Meister*, edited by
Arnold Schering (Leipzig: Breitkopf & Härtel, 1907). Composers represented
include Pisendel, Hasse, C. P. E. Bach, Telemann, Graupner, Stölzel, and
Hurlebusch. The corpus is still at the **page-level OMR** stage: 300
facsimile-linked page files (`bsb00023250_00031` through `00330`). Work-level
files have not yet been assembled.

|                          |                                                                                                      |
| ------------------------ | ---------------------------------------------------------------------------------------------------- |
| Digital facsimile        | [BSB `bsb00023250`](https://www.digitale-sammlungen.de/en/view/bsb00023250)                         |
| Page-level MEI           | `29_30_instrumentalkonzerte_deutscher_meister_bsb00023250/`                                        |
| Planned work-level files | listed in the[repository README](https://github.com/egorpol/DdT_1_vol_29_30#planned-work-level-files) |

## Status terms

Both repositories use the same work-level vocabulary:

| Status        | Meaning                                                                          |
| ------------- | -------------------------------------------------------------------------------- |
| `pending`   | no work-level MEI has been assembled yet                                         |
| `combined`  | page files have been joined, with linked facsimile surfaces                      |
| `corrected` | musical text and facsimile references have been reviewed; local checks completed |
| `finalized` | metadata, editorial review, validation, and publication naming are complete      |

An empty consistency CSV means the automated checks found no encoded
inconsistency. It does not replace comparison with the source facsimile.

## How this relates to CAMAT

The editorial loop that these volumes use is the same path Workflow 1 teaches:
integrate facsimiles, combine pages, write a check report, correct in
mei-friend, inspect in the facsimile viewer, and re-check. Conversion
(Workflow 2) is a different path: it imports another encoding and does not
produce a reviewed edition.
