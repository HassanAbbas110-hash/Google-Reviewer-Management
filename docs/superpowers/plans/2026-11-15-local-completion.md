# Local completion implementation plan

**Goal:** Complete the authorised local-only improvements without enabling Google publishing.
**Architecture:** A separate durable SQLite evaluation queue uses the same AI/safety path as demos. A polling UI displays progress; exports describe routing checks, not proven AI quality. One offline code-only updater replaces the accumulated patch workflow.
**Scope approved:** grounding, complaint tone, broader tests, shorter explanations, batch evaluation, progress/errors, notification/restart verification and consolidated updates.

## Constraints
- Never call Google, send alerts or alter live publishing flags from evaluation jobs.
- Preserve local business records and credentials during updates.
- Real model quality, SMTP delivery and Google roundtrip remain external acceptance tasks.
- Model generation remains serial on the 16 GB laptop; cancellation finishes the current request.

## Tasks
- [x] Grounding: reject unsupported offers/advice; shorten generation explanations. Test observed parking-help offer and dismissive complaint language.
- [x] Durable lab: add run persistence, FIFO claim, per-case checkpoints, cancel/resume and 24-case regression set; test isolation, failures and restart recovery.
- [x] UI: background single/batch runs, progress polling, actionable errors and safe CSV/JSON exports. Test CSRF, unknown business/run, cross-business access and spreadsheet injection.
- [x] Operations: notification retry visibility/reset and tests; open browser only after listener is ready; verify configuration recovery remains passing.
- [x] Release: canonical Update-App package with exact allowlist/hashes, backups, rollback and data-preservation tests. Run suite and fresh review, push GitHub, provide laptop instructions.

Validation: 111 local tests passing; Python compilation and JS syntax checked. Real model, Windows and external delivery checks remain pending.
