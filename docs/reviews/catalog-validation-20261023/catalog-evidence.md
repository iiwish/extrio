# A001 Catalog and Static Inspection Evidence

Task: `CATALOG-20261023/A001`. Scope: offline CSV accounting and conservative static inspection only. Status: implementation and directed verification complete; integrated validation and live catalog results are recorded in [verification.md](verification.md).

## Files and Contract

- `scripts/tender_sources/catalog.py` implements the packet's three dataclasses and five public functions without changing their interfaces. Dataclasses are serializable through `dataclasses.asdict`.
- `backend/tests/test_tender_catalog.py` contains 77 offline cases. No network, database, services, model calls, source requests, commits, pushes, releases or deployments are used by this unit.
- UTF-8 BOM and standard CSV quoting are parsed with `csv.reader`. Each nonblank record retains its original URL, complete metadata, group, physical starting line and stable group/line/URL-derived ID. Duplicate and missing URLs remain separate records. A missing or duplicated `entryUrl` column fails explicitly.
- URL validation rejects unsafe schemes, user information, nonstandard ports, control characters, backslashes, localhost names and nonpublic IP literals. DNS resolution and request-time public-IP enforcement remain the network layer's responsibility.
- Historical list-level login requirements and HTTP 401/403/429 are retained with the historical date and evidence field. Unknown login state, JS shells, TLS errors and detail-only login requirements do not become list-level historical prohibitions.

## Inspection Semantics

`inspect_list` reports `candidate_list` only for actual page links with notice semantics and a nearby valid date. It does not execute scripts, trust HTML base overrides, follow pagination or use CSV sample-detail URLs. Unsafe targets, attachments and cross-host links do not become detail candidates. The existing six exact list-entry profiles can supply their established selectors; unknown layouts use conservative generic static inspection.

`inspect_detail` reports `sample_readable`, not native-run or signed-rule acceptance. Output distinguishes `html_profile` and `html_candidate`. A positive sample requires bound URL and normalized title, an explicit matching publication date, an identifiable notice container, at least 100 non-link body characters, at least 50 percent non-link text and procurement semantics in the body. Existing `titles_consistent`, profile parsers and profile validation helpers are reused. Navigation, login/challenge pages, missing or mismatched metadata, garbled text, short bodies, linked-original pointers, PDF frames and unknown embedded bodies are rejected or marked incomplete. Publication dates after the local current calendar date are not candidate or detail evidence. Generic date/time class names and footer/header/navigation dates are not publication evidence, including self/ancestor class and ID markers for footer, foot, copyright and navigation chrome.

## RED and GREEN

Environment: `/tmp/extrio-health-20261022/backend-venv`, Python 3.12.13. All commands run from the repository root.

1. The initial new test file failed collection because `tender_sources.catalog` did not exist. After introducing only the fixed dataclasses and `NotImplementedError` function interfaces, the same test suite executed and returned **59 failed**. No implementation behavior existed at this RED checkpoint.
2. Initial implementation returned **58 passed, 1 failed**. The failing test proved that a footer date could leak through the document ancestor into a list row. Limiting date lookup to the nearest compact record fixed this case.
3. Independent review's pure-link navigation and footer-node date counterexamples, plus a long generic help-page case, were added before their fixes: **5 failed, 59 passed**. Body prose and semantic evidence plus self-node date exclusions made these cases pass.
4. Final self-check added generic copyright-date and uppercase-PDF cases before their fixes: **2 failed, 68 passed**. Generic `.date`/`.time` selectors were removed, and embedded PDF suffix checks became case-insensitive.
5. Final hardening added future-date, footer/foot/copyright/navigation class and ID, and correctly spelled Chinese selection-term cases before their fixes: **7 failed, 70 passed**. The parser rejects future publication evidence, excludes chrome marker dates and recognizes `\u9048\u9009` and `\u5019\u9009\u4eba`.
6. Final command:

```sh
/tmp/extrio-health-20261022/backend-venv/bin/python -m pytest \
  -c backend/pyproject.toml \
  backend/tests/test_tender_catalog.py \
  backend/tests/test_tender_source_adapters.py -q
```

Result: **112 passed in 0.80 seconds**: 77 new catalog cases and 35 existing source-adapter cases.

```sh
/tmp/extrio-health-20261022/backend-venv/bin/ruff check \
  scripts/tender_sources/catalog.py backend/tests/test_tender_catalog.py
```

Result: **All checks passed**.

## Limits

- Generic parsing intentionally favors false negatives over false claims of successful collection. Unknown templates, copyright-only dates, predominantly linked bodies, PDF/OCR, dynamic JSON/JS and unknown original-document jumps need explicit adapters or further review.
- A positive static sample does not establish complete business-field quality, signed rules, historical pagination, completeness, incremental operation, attachment coverage or console-native operation.
- Exact-host/request security, global budgets, permissions, checkpoint/resume behavior and full CSV denominators require A002 and main-task verification; this unit does not claim those validations.
