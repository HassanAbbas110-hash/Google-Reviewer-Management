# Pilot checklist

✅ = verified on the HP ZBook test laptop (16 GB RAM, Intel UHD) with the fictional demo and mocked Google, 26 Nov 2026.
⬜ = needs a real, authorised Google account / owner. Do not fake these with test reviews on a real listing.

## Local (done)
- ✅ Setup/Start/Doctor scripts on Windows; Windows Credential Manager detected
- ✅ All owner regression cases + 50 paraphrases route correctly (`tests/test_policy.py`)
- ✅ Sensitive reviews produce no AI reply in demo, test lab and live workflow (`tests/test_workflow.py`, `tests/test_replies.py`)
- ✅ Every failed safeguard blocks publishing (`PublishEligibilityTests`)
- ✅ First sync = backlog; existing Google replies preserved; edited reviews clear approval
- ✅ Double click / concurrent publish / timeout + retry post exactly once (mock post counter)
- ✅ Owner alerts deduplicated, visible without SMTP, failed email stays visible with retry
- ✅ Business isolation (jobs, alerts, lab runs, adapters)
- ✅ Form save after restart / with other local apps' cookies (old 403)
- ✅ Real Ollama drafts benchmarked (see MODEL_BENCHMARK.md)

## Needs the real Google account and owner
- ⬜ Google Cloud project approved for Business Profile API (quota 300 QPM, not 0)
- ⬜ OAuth consent screen + Desktop client; owner signs in via Connect-Google.cmd; correct location chosen
- ⬜ First live sync: backlog only, no replies sent; existing owner replies shown as "Replied on Google"
- ⬜ Owner's written authorisation to publish recorded (tick box) — and kept on file outside the app
- ⬜ Draft-only pilot for ~2 weeks: staff approve/edit drafts; owner reads a sample; note edits needed per draft
- ⬜ One manual publish on a genuine review, then check it on Google Maps; press Sync and confirm the case stays Published
- ⬜ Token expiry (7 days while the consent screen is in Testing): confirm "Reconnect needed" appears and reconnecting works
- ⬜ If wanted: SMTP set up and one real owner alert received
- ⬜ Then switch to "Reply automatically to most reviews" and spot-check the Done tab for the first week
