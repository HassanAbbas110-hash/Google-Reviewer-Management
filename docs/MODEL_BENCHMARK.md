# Local model benchmark: HP ZBook Firefly 14 G7

Hardware: Intel i5-10310U (4 cores), 15.3 GB RAM, Intel UHD Graphics (no GPU acceleration). Ollama 0.34.3.
Method: `tools/benchmark.py` runs 23 fictional reviews (owner regression set + paraphrases) through the app's real drafting code (`make_draft`), with the demo shop's voice and facts. "Cold" = first AI draft right after the model was unloaded. Raw data: `docs/benchmarks/`.

## Result (final run, 26 Nov 2026, after the reply checks were tightened)

| Model | Routing | Sensitive held, no AI reply | Usable AI drafts | Cold first draft | Warm, 1 model call | Warm, with rewrite |
|---|---|---|---|---|---|---|
| **qwen3:4b** (2.5 GB) | 23/23 | 7/7 | 11/13 | 60 s | 16 to 35 s | 43 to 62 s |

Earlier run (before the checks were tightened; most drafts passed on the first call): cold 51 s, warm 9.5 to 16 s per draft.

No-model paths: blank 4- and 5-star reviews take under 0.1 s. Sensitive holds take 0 s, because no model is called.

## Why qwen3:4b

- **llama3.2:3b** (partial run, stopped early): similar speed (8 to 47 s), but worse replies. It wrote "our demo shop", "We'll keep working on getting our checkout…" (an unapproved promise), and stacked "Sorry… sorry…". It needed more rewrites.
- **qwen2.5-coder:3b / 7b**: built for code, not customer-facing writing. Not chosen. Not benchmarked fully.
- **gemma4:26b** (18 GB): won't fit in 16 GB RAM.
- **qwen3:4b**: the smallest model that kept the facts straight and followed the voice. The app turns its "thinking" mode off, which makes it much faster.

Routing does not depend on the model. Rules decide it first, so a weaker or absent model never lets a safety case through.

## Things to know

- The first draft after starting (or after 30 idle minutes) loads the model: about 50 to 60 s. Later drafts are faster. Drafting runs in the background, so the dashboard stays usable.
- When a draft fails a check, the app asks for one rewrite (2 model calls). If the rewrite also fails, the case says "write it yourself" with the reason. In the final run that happened for 2 of the 13 AI cases (parking, and slow checkout).
- Some passed drafts still carry a "style" note (for example "thanks for the kind words", or an invented "today"). Staff see the note, and drafts with notes are never auto-published.
- Close heavy apps (browsers with many tabs, Teams) for faster drafts. If drafts time out, raise the timeout on the Status page.

## Re-run on any laptop

```powershell
.venv\Scripts\python.exe tools\benchmark.py qwen3:4b llama3.2:3b
```
