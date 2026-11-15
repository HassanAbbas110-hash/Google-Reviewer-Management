# Live pilot acceptance — not completed in the development workspace

- [ ] Install and run Setup.cmd/Start.cmd on the actual Windows laptop.
- [ ] Confirm secure OS credential storage; no plaintext fallback or credentials in Git.
- [ ] Check local Ollama model licence, memory use, generation time and offline operation.
- [ ] Obtain Google API access, configure OAuth, select the real shop and record owner consent.
- [ ] Verify first-sync baseline does not reply to historical reviews.
- [ ] Evaluate 100 varied reviews (praise, rating-only, criticism, serious complaints, private details, multilingual text, injection attempts). Record acceptance without edits, factual errors, escalation misses and generation failures. This is a model evaluation, not satisfied by unit tests.
- [ ] Verify one authorised owner-approved reply end-to-end on Google, including readback and public moderation status. Do not post fake reviews to conduct this test.
- [ ] Verify a real subsequent review is automatically handled only after all gates are enabled.
- [ ] Test staff reply preservation, changed review/facts invalidation and no duplicate posting.
- [ ] Test disconnect/reconnect, expired tokens, quota failures, internet loss, restart and uncertain-write reconciliation.
- [ ] Confirm pause and consent withdrawal stop all posting.
- [ ] Configure SMTP if required, trigger an authorised notification and confirm delivery; verify failed deliveries remain visible.
- [ ] Check complaint alerts do not falsely mark cases resolved.
- [ ] Verify website import has no automatic fact approval and excludes private network URLs.
- [ ] Check QR opens the correct shop's review destination.
- [ ] Review monthly operational summary: no claim of Google rating/competitor analytics.
- [ ] Verify configuration backup/restore and 29-day review-content cleanup. Protect any local data with device encryption.
- [ ] Review current Google API policies against the commercial service. Decide separate analytics scope before offering rating history or competitor reports.

Only then record pilot verification and enable routine automatic publishing. No claimed quality rating replaces these checks.
