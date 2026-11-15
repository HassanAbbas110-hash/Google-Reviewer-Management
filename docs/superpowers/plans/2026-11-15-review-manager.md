# Google Reviewer Management Implementation Plan

> Implement sequentially with tests before code. User authorised building on 15 November 2026.

**Goal:** Local automatic review management with no paid hosting or AI dependency.

**Architecture:** SQLite persistence, explicit policy decisions and replaceable Google/AI adapters; localhost management app and scheduled worker.

**Tech Stack:** Python 3.11+, SQLite, Ollama; remaining dependencies chosen at the integration stage.

**Spec:** ../specs/2026-11-15-review-manager-design.md

## Global Constraints
- No live posting until consent, approved facts and pilot verification.
- No credentials or real client records in Git.
- Business isolation applies to every review operation.

## Review Focus
- Same Google review identifier on different businesses must not collide.
- Revised text or rating invalidates prior handling.
- Human replies are preserved, including on revised reviews.
- Restart must not duplicate queued work.
- Missing consent or uncertain output cannot become automatic publication.

## Task 1: Durable queue and publication policy
Files: reviewer/core.py; tests/test_core.py.
Interfaces: Store(path).ingest(business_id, review_id, text, rating, existing_reply='') -> state; Store.get(business_id, review_id) -> dict; decision(consent, facts_approved, auto_enabled, risk, valid, existing_reply='') -> str.
- [ ] Write tests for duplicate ingestion, tenant isolation, revision invalidation, human-reply preservation, restart persistence, missing consent/facts and sensitive output.
- [ ] Run `python -m unittest discover -s tests -v`; observe failure before implementation.
- [ ] Implement SQLite ingestion transaction and fail-closed decision function.
- [ ] Run full suite; expected all passing; inspect diff and commit.

## Task 2: Google adapter
- [ ] Read current official OAuth/review API and content-retention documentation.
- [ ] Add desktop OAuth and credential-store integration, account/location selection, paginated polling and bounded retries.
- [ ] Verify authorisation errors, quota handling and incomplete page retrieval without marking unseen reviews handled.
- [ ] Implement publishing reconciliation: inspect current reply/version before write; ambiguous writes require readback before retry.

## Task 3: Ollama and fact controls
- [ ] Verify model hardware fit and commercial licence; configure localhost-only Ollama.
- [ ] Test schema validation, injection attempts, prohibited promises and model failure; fail closed.
- [ ] Implement facts/version approval and deterministic safeguards in addition to model risk classification.

## Task 4: Local management and operations
- [ ] Add business settings, queue, approval, consent, pause, investigation and reconnect screens.
- [ ] Add safe public website extraction, summaries, notification delivery state, backups and retention.
- [ ] Test CSRF protection, host/origin restrictions, secret redaction and data separation.

## Task 5: Pilot release
- [ ] Run 100-review evaluation and recovery scenarios.
- [ ] Verify actual Google roundtrip with owner-authorised pilot; no tests post to real clients by default.
- [ ] Document hardware/Google prerequisites, Windows startup, restore and operating limits.
- [ ] Enable automatic publishing only following recorded pilot review and explicit business consent.
