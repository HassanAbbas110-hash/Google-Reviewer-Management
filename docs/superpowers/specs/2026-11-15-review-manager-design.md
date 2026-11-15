# Google Reviewer Management design

## Intent and agreed approach
Build a local-first reusable WebRift service for automatic Google review replies, with per-business facts, tone, contacts and owner consent. User selected the free official Google API, local AI and local scheduling after comparing manual drafting, browser automation and paid cloud hosting. Manual copy/paste does not satisfy the goal. Cloud migration is later.

## Scope
New reviews by default; historical backlog requires explicit opt-in. Preserve human replies. Changed reviews require reassessment rather than automatic overwrite. Routine replies may publish only with business consent, approved facts, enabled automation and successful validation. Sensitive or uncertain cases require human approval. Complaint acknowledgements must not fabricate investigations or resolutions; track investigation independently from publishing.

## Architecture (builder proposals)
Python 3.11+, SQLite, localhost-only dashboard, Ollama local generation, desktop Google OAuth and a scheduled worker. No paid services configured. Poll every 30 minutes subject to quota. Persist jobs across restarts; catch up after downtime. Store secrets in OS credential storage when OAuth is implemented, never Git. Keep one installation with business isolation. A paid AI adapter may be added later without changing business workflows.

## Constraints and dependencies
Google API approval and business authorisation are external prerequisites. Existing hardware suitability is unknown. Offline or sleeping computer cannot process reviews. No guarantee of perfect AI judgement or uninterrupted availability. Google content retention requirements must be verified and implemented before storing live review data. No client data is seeded.

## Safety and recovery
Pause controls, bounded retries, no blind retry after ambiguous publishing outcome, review-version checks before publication, preserve staff replies, reject stale approval after review or facts change. Block prompt injection and unsupported commitments. Approval does not close an investigation. Website extraction must limit domains, redirects, response size and block local/private networks. Notifications must exclude unnecessary sensitive information.

## Initial foundation deliverable
A standard-library processing core with business-isolated durable ingestion, stable duplicate detection, conservative change handling and publish eligibility decisions. This does not constitute a live service. Persist audit/status state; no network calls yet.

## Acceptance before live activation
Representative 100-review evaluation, credential isolation, duplicate prevention, edited review handling, restart recovery, failed/ambiguous publication reconciliation, consent revocation, alert failure visibility, secret handling, retention and backup recovery. One actual shop in approval mode before routine auto-publishing. Report measured results, not invented ratings.
