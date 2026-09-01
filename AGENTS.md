# Extrio Project Guidance

## Product Surface

- Extrio Web is a desktop-only operational console. Do not design, implement, test, or document mobile layouts unless the user explicitly changes this scope.
- Target desktop viewports at `1280px` and wider. Use `1440x900` as the primary visual QA viewport and `1280x800` as the minimum supported QA viewport.
- Narrower viewports are unsupported. Existing responsive behavior may remain when it does not add complexity, but mobile polish and mobile acceptance evidence are out of scope.
- Prefer dense, scan-friendly operational layouts with stable columns, explicit status, evidence, blockers, and next actions over marketing composition or card-heavy dashboards.

## Delivery

- Keep `docs/SSOT.md`, `docs/product-contract.md`, `docs/frontend-prototype.md`, and `docs/releases/v0.2-acceptance.md` aligned when product or UX scope changes.
- Frontend work uses `pnpm`, Vite, React, TypeScript, Tailwind CSS, and shadcn/ui.
- Validate frontend changes with the relevant tests, `pnpm build`, and desktop browser QA at the supported viewports.
