# Model benchmark 2026-11-26

Through the app's real pipeline (`make_draft`), demo business voice and facts.

| Model | Routing | Usable AI drafts | Passed 1st try | Cold 1st draft (s) | Warm median (s) | Warm p90 (s) | Warm max (s) | Errors |
|---|---|---|---|---|---|---|---|---|
| qwen3:4b | 23/23 | 11/13 | 5/13 | 59.7 | 45.5 | 56.7 | 62.0 | 0 |

## qwen3:4b

| Case | Stars | Type | Status | s | Reply / issue |
|---|---|---|---|---|---|
| praise-tools | 5 | routine | draft | 59.7 | Great to hear the tools worked out for you. Hope your project runs smoothly! |
| blank-5 | 5 | rating_only | draft | 0.0 | Thanks so much for the 5 stars! |
| no-complaints | 5 | routine | draft | 34.6 | Quick checkout and helpful advice—thanks for the kind words! |
| parking | 4 | mixed | blocked | 48.1 | Reply thanks the customer for something the business provided. Mentions things the customer did not say: today. |
| wait-rude | 2 | complaint | draft | 34.8 | Sorry the wait was so long and the staff were rude about paint. If you're happy to get in touch, we'd like to hear more about what happened. |
| drill | 2 | complaint | draft | 56.7 | I'm sorry the drill stopped working after one use. If you're happy to get in touch, we'd like to hear more about what happened. |
| battery | 5 | sensitive | held | 0.0 | (held / no AI reply) |
| double-charge | 1 | sensitive | held | 0.0 | (held / no AI reply) |
| injection | 5 | sensitive | held | 0.0 | (held / no AI reply) |
| fit-help | 5 | routine | draft | 62.0 | Great, the bolt fits perfectly. Hope your project goes smoothly! |
| welcoming | 5 | routine | draft | 25.4 | Great to hear the tools were easy to find and staff were welcoming. Hope your projects run smoothly! |
| key-cutting | 4 | routine | draft | 42.9 | Great to hear you found what you needed. Key cutting was quick too! |
| blank-4 | 4 | rating_only | draft | 0.0 | Thanks so much for the 4 stars! |
| mixed-delay | 5 | mixed | blocked | 58.5 | Follow-up offers product help when the concern was about the visit. Mentions things the customer did not say: paint. |
| parking-tight | 4 | mixed | draft | 54.5 | Parking was tight today. Thanks for sharing that. |
| unresolved | 4 | complaint | draft | 26.6 | I'm sorry your earlier complaint isn't resolved yet. If you're happy to share more, we'd love to help fix it. |
| wrong-size | 2 | complaint | draft | 16.4 | Sorry you got the wrong hinge size. If you're happy to share more, we'd like to hear what happened. |
| blank-2 | 2 | complaint | draft | 0.0 | Sorry we missed the mark. If you are happy to tell us what went wrong at hello@boltandbrush.test, we would like to hear it. |
| sander | 2 | complaint | draft | 52.4 | I'm sorry your sander broke right away. If you're happy to get in touch, we'd like to hear more about what happened. |
| burning-plug | 5 | sensitive | held | 0.0 | (held / no AI reply) |
| repeat-billing | 1 | sensitive | held | 0.0 | (held / no AI reply) |
| manipulation | 5 | sensitive | held | 0.0 | (held / no AI reply) |
| phone-number | 2 | sensitive | held | 0.0 | (held / no AI reply) |
