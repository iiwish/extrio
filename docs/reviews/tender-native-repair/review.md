# Native Tender Trial Review

Status: Initial Trials Verified / User Review. Test date: 2026-10-19. This is the retained initial-trial evidence set. Current regression, source-inspection dispositions and acceptance blockers are in [regression-review.md](regression-review.md). All six representative sources have reviewed signed rules and bounded native trials; withheld records are not all proven source errors. This is not production crawling readiness or full-column acceptance.

## Verified Results

| Source | Signed Rule | List Pages | Details / Accepted / Rejected | Native Run |
| --- | --- | --- | --- | --- |
| 浙大一院 | v2 | 3 | 30 / 30 / 0 | `run_x_793c07e54e5f42` |
| 南方电网 | v1 | 3 | 30 / 30 / 0 | `run_x_9b3c46e1f8324c` |
| 中国政府采购网 | v4 | 3 | 50 / 50 / 0 | `run_ba3b3097520c492a` |
| 复旦大学 | v1 | 3 | 30 / 26 / 4 | `run_f48121297c8e4aaa` |
| 厦门大学 | v1 | 3 | 45 / 33 / 12 | `run_x_76b2af72fd1241` |
| 广东省机电设备招标中心 | v1 | 3 | 44 / 35 / 9 | `run_x_8bb8d3b9b33341` |

The six initial selected runs contain 229 results: 204 accepted and 25 rejected. Every result is compared with its own retained official responses. Page URL sets and response hashes differ across all three pages per source. CCGP stops at the requested 50-item cap with native `partially_succeeded` / `max_items`; Fudan, XMU and GDEbidding are `partially_succeeded` because strict quality gates withhold records. The initial data workspace contains 230 deduplicated entities including historical and rejected test records. Historical retry observations are not added to the selected-run acceptance count; current counts and corrected parser cases belong to the current regression report.

All selected runs have verified rule attestations. All 1480 imported sources retain disabled schedules. The original database remains outside this execution path; its read-only count check is collections=6, collectors=11, runs=26. The isolated test instance is `backend/data/tender-manual-20261019`, served at http://127.0.0.1:5173. Native runs, AI failures, source instructions, items and lineage remain in the interface. The earlier EPS trial, and two cancelled queued preflight runs, remain historical evidence rather than additional accepted coverage.

## Repairs

- Field evidence uses explicit stage bindings, exact URL-matched list rows and the corresponding accepted detail sample. A missing numbered detail file cannot shift subsequent HTML onto another sampled URL. JSON proof is labeled JSON; no navigation-anchor fallback is used.
- Hospital paging is the anonymous GET endpoint wired by its public `pagedata.js`. The source shell, script and raw JSON remain local evidence. Numeric IDs use a constrained same-host `url_path` transform. Category/ID mismatches fail closed.
- Known static publisher templates use guarded HTTP samples instead of executing counter/analytics POSTs. No POST, robots, host or private-network policy is relaxed.
- CCGP's script-generated pager requires browser list transport. Static detail HTTP transport is explicit in the signed rule. Runtime does not silently change a signed transport.
- CSG's truncated list title requires a long matching prefix, the exact handoff URL, matching publication day and a matching full detail breadcrumb. The global strict title comparator is unchanged.
- MiMo uses the configured `mimo-v2.6-flash` model, bounded task budgets and official JSON mode. Provider credentials and raw model response text are not delivery artifacts. Reference: [MiMo Structured Output](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/structured-output).
- Published output fields have read-only access to the existing evidence drawer. The rule flow displays its signed effective list entrypoint, not a substituted landing URL.
- `official_notice_v1` is a signed application-owned profile for exact publisher/original hosts. It follows publisher-emitted CCGP links, checks project/stage/date and upgrades the exact Fudan HTTP redirect target to HTTPS, including explicit port 80, without sending a downgrade request. General network guards remain fail-closed.
- Official document envelopes are explicitly derived JSON. Raw HTML, JSON, PDFs, EPS templates and rendering assets have retained hashes. The list handoff remains the identity URL; resolved originals are separate lineage links.
- PDF extraction runs in a bounded subprocess with CPU, wall-clock, page, byte and memory limits. Three real text-layer PDF notices are accepted; three image/incomplete-text-layer notices are rejected. Publisher-provided printed-page PDFs can include source headers, navigation and sidebars; PDF text is not promised to be a cleaned article-only field.
- EPS uses only guarded anonymous GET on the source network. Captured public responses are consumed by the publisher's read callbacks inside a browser with a nonforwarding proxy. Login probes are aborted; unknown data requests, restricted visibility and mismatched stages are rejected. Numeric receive IDs are source-observed public identifiers, not guessed UUIDs. Structured project JSON is not substituted for rendered notice text.
- Item lineage exposes resolution kind, original/PDF/API links, PDF page count, hashes and errors. Missing bodies do not claim that the frozen contract allows empty content. EPS title wording differences are distinguished from verified GUID/package/stage identity.

## Manual Review Boundaries

| Source | Current Boundary | Visible State |
| --- | --- | --- |
| 复旦大学 | Accepted: 10 publisher HTML, 13 linked originals, 3 text-layer PDFs. Rejected: 3 scanned/incomplete-text-layer PDFs and 1 original identity/stage mismatch. | Published; 4 rejected records and their evidence are visible. |
| 厦门大学 | Accepted: 18 publisher HTML and 15 linked originals. Rejected: 9 original identity/stage mismatches, 2 publication-day mismatches and 1 missing/unsupported body. | Published; 12 rejected records remain outside delivery. |
| 广东省机电设备招标中心 | Accepted: 35 public rendered templates. Rejected: 5 visibility-scope cases, 3 notice-stage mismatches and 1 rendered-title/project mismatch. | Published; 9 rejected records remain outside delivery. No login-only attachments. |

No independent script samples are imported into Items or counted as native successes. The three official-document trials retain 119 results with 94 accepted bodies and 25 rejected records. Rejections are not repaired by weakening identity, visibility or empty-body gates.

## Validation

- 318 related backend tests pass, including signature/security/repair, stage evidence, missing-file provenance, JSON pagination, official-original scope, PDF subprocesses, numeric EPS IDs, offline read callbacks and mixed transport. The numeric receive-ID regression has a recorded RED/GREEN check.
- All 270 frontend tests (42 files), production build and lint pass. Detailed source/row checks and screenshots remain in the isolated test directory.
- Desktop QA covers 1440x900, 1280x800, 1132x1028 and 1024x800. Native runs, JSON field ID 10347, clean hospital date DOM, and CCGP announcement href evidence are visibly verified. Dense run tables retain their existing contained horizontal scrolling at narrower desktop widths. Viewport overrides are reset.
- Official-document QA verifies PDF page count/URL, scanned-PDF rejection, CCGP original links, EPS derived-evidence labels and GUID/package identity wording. PDF and EPS lineage screens fit all four desktop widths without document-level horizontal overflow. All three native result summaries are visible with the verified counts. One real publisher-provided PDF is visually rendered and checked against its retained text layer. Evidence: `documents-browser-qa.json` and `screenshots/documents-*.png` in the isolated test directory. The final results tab remains available; viewport overrides are reset.
- `verify_multipage.py` retains the first three source proofs. `verify_documents_runs.py` independently checks all 119 official-document results, raw response/PDF/asset hashes, publication and model lineage, three distinct page sets, signed-rule status, disabled schedules, readiness and original database counts. Result: `backend/data/tender-manual-20261019/official-documents-result.json`. Local artifacts are sampled, not complete replay manifests.

Only embedded body PDFs are downloaded within the existing byte budget. General attachments, notice-image OCR, login-only files, multi-day stability, incremental-window correctness, complete business-field coverage and cross-source project deduplication are not accepted. No commit or deployment is performed.
