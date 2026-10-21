# Current Candidate Regression Review

Status: Verification Complete / Acceptance Blocked. Date: 2026-10-19. This report covers the working candidate, not the historical frozen release or an independent human acceptance signature.

## Acceptance Decision

The collection console supports bounded functional review. Commercial tender-platform acceptance and six-source live incremental acceptance remain blocked. Passing repeat-run deduplication is not evidence of a committed source checkpoint. Product and technical signatures remain user-owned.

## Repaired Findings

- Same-minute observations use persistence time before random IDs when selecting the latest accepted baseline and current entity. A deterministic counterexample reproduced the old-version selection. The signed API-to-real-HTTP-to-Worker integration test verifies initial checkpoint creation, two incremental runs, changed values, late publication within lookback, unchanged revisions, duplicate URL suppression and no duplicate delivery enqueue.
- XMU's complete 405-character amendment contains an earlier-notice link. A source-specific complete-amendment check distinguishes it from a link-only stub; incomplete stubs remain rejected. Native retest accepts the actual amendment as publisher HTML.
- EPS project-name identity comparison normalizes whitespace while preserving publisher-rendered title/body text, GUID, package, visibility and stage gates. Native retest accepts the actual 966-character procurement notice whose API project name contains a leading space and trailing tab.

## Automated Gates

| Current Candidate Gate | Result |
| --- | --- |
| Complete backend suite with owned PostgreSQL 16 | 965 passed, zero failures/errors/skips; 169.20 seconds. Includes 21 PG store tests and the same-minute counterexample in both SQLite and PG. |
| Complete frontend suite | 270 passed across 42 files. Existing jsdom document-navigation warnings remain nonblocking. |
| Backend Ruff and frontend lint | Passed. Initial full lint exposed only an import-order issue in the independent source-adapter test; imports are mechanically ordered without behavior changes. |
| Frontend production build | Passed. |
| OpenAPI generation parity | Passed; generated TypeScript bytes unchanged. |
| Documentation manifest | Passed; unapproved current-review manifest matches authoritative files. |
| Wheel and packaged OpenAPI | Passed; packaged OpenAPI bytes match source. |
| Disposable source startup | Passed: API readiness, authenticated boundary and Web startup; temporary API/Worker/Web stop cleanly. |
| Whitespace and candidate stability | `git diff --check` passed. All 332 recorded code/test/contract/package files remain identical across the final suite and final-health verification. |

Raw final gate logs, JUnit and before/after source hashes are in `regression-20261019/final/`. The first regression receipt preserves initial lint/manifest failures and a pre-test edit interval; it is not the final stable-candidate receipt. No checks are removed or skipped to obtain the final result.

## Native Results

Every row is a real persisted run with a signed rule, fixed policy, three list pages and at most fifty details. Use the six selected runs below for current per-source coverage; historical retries are not additional unique notice coverage.

| Source | Selected Native Run | Accepted | Rejected | New / Updated / Unchanged |
| --- | --- | ---: | ---: | --- |
| 浙大一院 | `run_f44ab71ef71e40de` | 30 | 0 | 0 / 0 / 30 |
| 中国政府采购网 | `run_x_3f1dee284c4247` | 50 | 0 | 50 / 0 / 0 |
| 南方电网 | `run_e3dc7be4d5c14a95` | 30 | 0 | 3 / 0 / 27 |
| 复旦大学 | `run_x_9dc48691193541` | 26 | 4 | 0 / 0 / 26 |
| 厦门大学 | `run_x_30644416a2194d` | 34 | 11 | 1 / 0 / 33 |
| 广东省机电设备招标中心 | `run_x_242db2f799ea49` | 36 | 8 | 1 / 0 / 35 |

The selected set contains 229 results: 206 accepted and 23 rejected. CCGP stops at `max_items`; the others stop at `max_pages`. The first repeat round and the targeted post-fix round contain nine runs, 27 list-page fetches and 348 observations in total. These observations must not be reported as 348 unique notices. Entity keys increase from 230 to 283 in the first repeat round, exactly matching the union of retained keys and newly observed source URLs. The targeted retest adds no entity keys: its two first accepted records already existed as rejected entities. No run calls a model; AI-run count remains 25.

One earlier EPS repeat records a real `source_connection_failed` rejection and accepts 34 notices. The post-fix run recovers that notice and the whitespace case, accepting 36. The failed observation remains in history.

## Source Inspection

Thirty accepted samples, five per source, are independently compared with their retained title/body/date evidence. Coverage includes native HTML, publisher-linked CCGP originals, text-layer PDF and EPS visible-template text. All original 25 rejected records have individual source evidence and dispositions in the local review index.

| Disposition Of Original Rejections | Count | Decision |
| --- | ---: | --- |
| Image-only PDFs and employee-scope EPS projects | 7 | Correctly withheld: two PDFs have no extractable text and five EPS projects expose scope 51 rather than approved scope 10. |
| Footer-only PDF threshold | 1 | Visually inspected final page contains a footer and two logos. This conservative hold is not proof of an unreadable body; a footer-aware PDF policy requires review. |
| Linked-original identity adaptation gaps | 10 | Publisher links, buyer and context support the procurement, but agency prefixes, conjunctions and suffixes differ. Do not claim ten genuinely wrong projects or silently relax identity matching. |
| Publisher/original publication dates differ | 2 | One-day conflicts require separate publication/repost timestamp semantics. |
| EPS stage mapping unverified | 3 | Source stage is 2; the adapter approves 1. Stage semantics need evidence before expansion. |
| Parser defects with successful native retests | 2 | Complete XMU amendment and whitespace-padded EPS project name. |

This is assistant-executed retained-source inspection, not an external business reviewer's signature. Printed PDF text may contain publisher navigation/footer content. Hospital image specifications and general attachments are not parsed; clean full business-field coverage is not accepted.

## Incremental Boundary

All nine live runs are `executionMode=initial`, with no checkpoint before or after. No checkpoint is forged. Four signed source rules lack a list-date binding: hospital, CCGP, Fudan and XMU. Hospital and XMU additionally use query-page pagination, outside the currently declared general next-link incremental scope. CSG has a list date but reaches the three-page cap; EPS reaches the cap and has quality rejections. Those outcomes correctly withhold checkpoint advancement.

The isolated real-HTTP fixture verifies the engine's successful initial/incremental lifecycle, three-day lookback, a late new notice, a revision update and a stable repeat. Existing regression tests cover partial/capped runs, cancellation, timeout and lease loss without unsafe checkpoint commits. Fixture proof does not certify any of the six live sources' incremental coverage. Multi-day availability, capacity, production recovery and release-image/security refresh are not part of this validation.

## Evidence

Local raw evidence root: `backend/data/tender-manual-20261019/regression-20261019/`, protected as an owner-only test directory. No keys, cookies or raw model responses are included in this tracked report.

- `manual-review.json`: 30 accepted samples, all 25 original rejection dispositions and retained source hashes; PDF visual checks are `mixed-pdf-page-4.png` and `scanned-pdf-page-1.png`.
- `repeat-validation.json`, `postfix/repeat-validation.json`: native limits, classification against retained accepted baselines, exact entity-key union, no checkpoint advancement, no AI activity and database isolation.
- `postfix/xmu-independent-checks.json`, `postfix/agency-independent-checks.json`: all 89 targeted result documents independently checked, including both repaired records.
- `same-minute-red.log`, `manual-defects-red.log`, `manual-incremental-green.log`: focused counterexamples and repaired behavior.
- `browser-scope-qa.json`, `incremental-scope-*.png`: all four supported desktop sizes show no document overflow and explicitly display no initial checkpoint/no advancement.
- `final-health.json`: ready API and matching live Worker, zero queued/running jobs, 1480 sources with all schedules off, 283 entities including rejected/history-derived records, AI-run count 25, owner-only evidence directory, removed owned PG container, and original database read-only counts of 6 collections / 11 collectors / 26 runs.
- `final-results-ui.png`, `xmu-amendment-ui.png`, `eps-repaired-ui.png`: native UI results and both repaired notices. The results browser tab remains on the selected EPS run; temporary viewport overrides are reset.

The app remains available at http://127.0.0.1:5173. No commit, deployment, schedule enablement or acceptance signature is performed. Business signoff, unresolved identity/stage/date/PDF policy cases and source-level incremental qualification remain open.
