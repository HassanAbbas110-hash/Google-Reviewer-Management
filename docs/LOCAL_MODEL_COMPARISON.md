# Local model comparison: 16 GB Windows laptop

Observed hardware: 16 GB RAM, Intel UHD integrated graphics; about 4.4 GB memory available in the supplied screenshot. Shared GPU memory is system RAM, not additional dedicated VRAM. Hardware suitability and speed must be measured; no throughput guarantee.

Candidate for comparison: `qwen3:4b`, listed by Ollama at approximately 2.5 GB Q4_K_M weights, Apache 2.0 licence. Runtime memory is larger than model download size. Close unused applications and unload the previous model with `ollama stop llama3.2:3b` before testing. Keep existing model files as the baseline.

Install with `ollama pull qwen3:4b`. Apply Update-Qwen.cmd, select `qwen3:4b` in the business settings, save and approve facts again. Saving the business deliberately disables automatic publishing. The app sends `think: false` only to the `qwen3` family via Ollama's native chat endpoint; other models are unaffected.

Compare the same fresh reviews for safety routing, coverage, approved contact, factual grounding, tone and elapsed time. Do not assume better quality from model size or published general benchmarks. Google publishing remains off until live acceptance is complete.

Official sources checked 15 November 2026:
- https://ollama.com/library/qwen3:4b
- https://ollama.com/blog/thinking
