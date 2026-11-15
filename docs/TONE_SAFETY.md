# Tone and safety update v3 — model retest required

Fresh laptop tests exposed a serious safety miss: five-star praise mentioning a smoking battery was classed routine. Mixed parking feedback was ignored, the rule matched `complain` inside `no complaints`, and the model closely copied full calibration reply examples.

Changes:
- Conservative product-hazard rules hold the tested smoking/fire/explosion/overheat/sparking/electric-shock patterns independently of the star rating or model. They are English-pattern checks, not exhaustive semantic detection.
- Whole-word complaint patterns avoid matching `late` in `chocolate` or `latest`.
- Exclude common absence-of-dissatisfaction `no complaint(s)` phrases from complaint scanning, while retaining passive statements such as `no complaints were addressed`; run safety checks on the full original text and retain any other negative evidence. Never downgrade a model warning.
- Common mixed-feedback terms now require staff review. A parking concern cannot be silently omitted from a generated draft.
- Reject vague support placeholders when an actual approved public contact is supplied.
- Remove complete sample replies and use classification-only examples. Ask for fresh, specific, warm conversational replies without forced slang, canned closings, jokes about complaints or invented actions. Respect formal business tone where applicable.

83 automated tests pass at this checkpoint; they do not verify actual local-model tone or generalisation. Re-run the five fresh laptop cases before changing the quality rating. The previously observed safety failure means unattended publishing remains unverified and should remain disabled.
