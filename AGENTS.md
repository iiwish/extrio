# Extrio Project Guidance

## Product Surface

- Extrio Web is a desktop-only operational console. Do not design, implement, test, or document mobile layouts unless the user explicitly changes this scope.
- Target desktop viewports at `1024px` and wider. Use `1440x900` as the primary visual QA viewport, plus `1280x800`, `1132x1028`, and the minimum `1024x800` viewport.
- Narrower viewports are unsupported. Existing responsive behavior may remain when it does not add complexity, but mobile polish and mobile acceptance evidence are out of scope.
- Prefer dense, scan-friendly operational layouts with stable columns, explicit status, evidence, blockers, and next actions over marketing composition or card-heavy dashboards.

## Delivery

- Keep `docs/SSOT.md`, `docs/product-contract.md`, `docs/frontend-prototype.md`, and `docs/releases/v0.2-acceptance.md` aligned when product or UX scope changes.
- Frontend work uses `pnpm`, Vite, React, TypeScript, Tailwind CSS, and shadcn/ui.
- Maintain one frontend entry, router, auth context, API client, and build. Product prototypes are iterations of the real frontend, not separate sample applications. Unimplemented backend capabilities must not report simulated success.
- Validate frontend changes with the relevant tests, `pnpm build`, and desktop browser QA at the supported viewports.
