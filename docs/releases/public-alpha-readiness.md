# Public-alpha release readiness

## Scope

The candidate is a self-hosted public alpha suitable for a technical portfolio,
not a production-stable 1.0 release. Release repair covers test entry points,
documentation integrity, showcase assets, isolated installation/execution,
authorized real-model samples, source commits and remote CI. Existing UI work is
preserved. Formal version tags and public deployment are outside this scope.

## Release checklist

- Run the README verification commands from the repository root.
- Include all referenced source files and screenshots in the release commit.
  A passing dirty-worktree build alone does not prove a Git checkout is complete.
- Verify the intended commit from a fresh checkout, including locked installs,
  frontend build, backend tests and disposable deterministic collection.
- Require remote CI, including PostgreSQL integration and secret scanning, to pass
  for the exact commit before tagging it.
- Review README screenshots and use `docs/showcase.md` for the presentation.
- Keep the public-alpha label and the security/deployment boundaries visible.

## Evidence boundaries

The deterministic demo verifies worker execution against a local source using a
fixed signed rule. It does not validate real-model generation. Historical real
source runs and G4 observations are not a substitute for a new candidate's soak
test. P28 has a bounded single-source real-model sample: a rejected title-only
attempt and a successful title/URL/body candidate with three accepted detail
samples. See the [closeout evidence](../reviews/release-closeout-2026-09-15/verification.md).
The user waives the 72-hour observation gate for this release on 2026-09-15;
this is an accepted evidence limitation, not a passed soak test. No long-duration
reliability or SLA claim follows from the waiver.

The showcase contains screenshots and a timed walkthrough, not a video recording.
No adoption, production throughput or arbitrary-site compatibility is claimed.
