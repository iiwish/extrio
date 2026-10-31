# Extrio console walkthrough

Extrio is a desktop, self-hosted collection console. This walkthrough targets 1440x900 and uses
local or explicitly authorized data. It does not demonstrate multi-tenant isolation,
production-scale throughput, or a hosted service.

## Three-minute sequence

| Time | Surface | What to demonstrate |
| --- | --- | --- |
| 0:00-0:30 | Collection requirements | Open a requirement and inspect required fields and the output contract. |
| 0:30-1:00 | Collection sources | Show the entry URL and its linked requirement; explain the source boundary. |
| 1:00-1:40 | Source detail | Inspect candidate evidence and publication state. AI proposes rules; a human approves publication. |
| 1:40-2:15 | Runs | Open a completed run; inspect outcome, counts and failure evidence rather than only a success badge. |
| 2:15-3:00 | Data | Page through results and open an item to trace its source, run and rule version. |

Use pre-existing completed runs for a timed presentation. Do not present a fixture
as a live model response. Fresh AI exploration requires a configured model and can
take longer than the presentation. Do not expose API keys, private URLs or personal
data in screenshots or recordings.

## Screenshot tour

![Requirements](assets/screenshots/requirements.png)

![Requirement output fields](assets/screenshots/requirement-fields.png)

![Sources](assets/screenshots/sources.png)

![Rule workspace](assets/screenshots/rule-workspace.png)

![Run history](assets/screenshots/runs.png)

![Results](assets/screenshots/items.png)

These screenshots come from a local instance with demonstration data, with the console set to
Chinese. The console also supports English.

## Reproducible execution

Follow the root README for locked installation and startup. The disposable
`scripts/benchmark.py --collectors 1 --pages 1` path executes a fixed signed rule
through the worker without model charges, external scraping or writes to an
existing instance. AI onboarding is a separate validation boundary.
