# Reply-quality update v2 — awaiting actual model retest

The first laptop examples confirmed generation but showed praise/rating-only reviews incorrectly classified as complaints, ordinary rudeness escalated as sensitive, unnecessary support contacts in praise, and invented product/service experience in rating-only replies.

Changes: explicit category definitions and calibration examples; classify only review content/rating rather than business complaint policies; classify before writing in the output schema; lower sampling temperature; concise replies; rating-only grounding checks; reject the observed confirmation of alleged rudeness. The same validation applies to demo and live generated drafts. Model warnings are never silently downgraded. Failed output remains held rather than automatically rewritten as safe.

Automated checks verify validation behavior and adapter boundaries, not actual model classification accuracy. Repeat the same four laptop samples, then broader tests, before updating any quality rating or enabling live publishing. Validation is conservative English-pattern checking plus model instructions, not proof of semantic safety in all languages.
