# Design QA: Collector task workspace

## Scope

- Route: `/collectors/:collectorId`
- Supported desktop viewports: `1280x800`, `1440x900`
- Intended change: organize the detail page around the operator's current task
  and keep field, rule, and item evidence available on demand.

## Evidence

- Review workspace at `1280x800`: `01-review-1280.png`
- Review workspace at `1440x900`: `02-review-1440.png`
- Configuration workspace at `1440x900`: `03-config-1440.png`
- Validation workspace at `1440x900`: `04-validation-1440.png`
- Field evidence panel at `1440x900`: `05-field-evidence-drawer-1440.png`

## Findings

- `ready_review` opens on review and publish; draft or exploring collectors open
  on configuration; published collectors open on runs.
- The first viewport presents the blocking decision, review totals, field
  decisions, and primary publication action before secondary configuration.
- Four task views replace five mixed-purpose tabs. Field review and samples
  share one workspace; crawl flow and validation metrics share another.
- Version comparison and GatherSpec are subordinate actions rather than
  permanent page tabs.
- Source definition, rule summary, and incremental policy remain complete but
  compact. Policy controls appear only while editing.
- Selecting a blocker, field, rule, or sample opens matching evidence without
  changing the main layout.
- The evidence surface traps focus, scrolls independently, has an accessible
  close label, and restores focus to its invoker.
- Both supported viewports have no document-level horizontal overflow,
  overlapping controls, clipped primary actions, or blank primary regions.

## Verification

- `pnpm test`: passed.
- `pnpm lint`: passed.
- `pnpm build`: passed.
- Browser walkthrough covered primary tabs, field evidence, item lineage,
  version comparison, GatherSpec, close behavior, and focus restoration.

Final result: passed.
