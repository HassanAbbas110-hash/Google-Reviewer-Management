"""Benchmark local models through the app's real drafting pipeline.

    .venv\\Scripts\\python.exe tools\\benchmark.py qwen3:4b llama3.2:3b

For each model: unload it, then run the owner + paraphrase test sets through
`make_draft` (same code as the live inbox). "Cold" is the first AI draft after
loading the model; "warm" is every later one. Writes a Markdown report.
"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests  # noqa: E402
from reviewer.ai import Ollama, make_draft  # noqa: E402
from reviewer.lab import OWNER, FRESH  # noqa: E402
from reviewer.mock_google import DEMO_BUSINESS  # noqa: E402

BUSINESS = dict(DEMO_BUSINESS, facts_approved=1)


def unload(model):
    try:
        requests.post('http://127.0.0.1:11434/api/generate', json={'model': model, 'keep_alive': 0}, timeout=60)
    except requests.RequestException:
        pass
    time.sleep(2)


def run(model, cases):
    ai = Ollama(model, timeout=300)
    unload(model)
    rows, recent = [], []
    for case in cases:
        started = time.perf_counter()
        try:
            out = make_draft(ai, dict(BUSINESS, model=model), case['text'], case['rating'], recent[-5:])
            err = ''
        except Exception as exc:
            out, err = {'category': '', 'status': 'error', 'reply': '', 'model_calls': 0, 'issues_hard': [], 'issues_soft': []}, repr(exc)
        elapsed = time.perf_counter() - started
        if out['reply']:
            recent.append(out['reply'])
        rows.append(dict(id=case['id'], rating=case['rating'], text=case['text'], expected=case['expected'], category=out['category'],
                         status=out['status'], reply=out['reply'], calls=out['model_calls'], seconds=round(elapsed, 1),
                         issues=' '.join(out['issues_hard'] + out['issues_soft']), error=err))
        print(f"  {model} {case['id']:<16} {out['status']:<8} {elapsed:6.1f}s calls={out['model_calls']} {out['reply'][:70]!r}", flush=True)
    return rows


def summarise(model, rows):
    ai_rows = [r for r in rows if r['calls']]
    cold = ai_rows[0]['seconds'] if ai_rows else None
    warm = [r['seconds'] for r in ai_rows[1:]]
    first_call_ok = [r for r in ai_rows if r['calls'] == 1 and r['status'] == 'draft']
    return {
        'model': model,
        'route_accuracy': f"{sum(r['category'] == r['expected'] for r in rows)}/{len(rows)}",
        'ai_cases': len(ai_rows),
        'usable_drafts': f"{sum(r['status'] == 'draft' for r in ai_rows)}/{len(ai_rows)}",
        'passed_first_try': f'{len(first_call_ok)}/{len(ai_rows)}',
        'cold_first_draft_s': cold,
        'warm_median_s': round(statistics.median(warm), 1) if warm else None,
        'warm_p90_s': round(sorted(warm)[int(0.9 * (len(warm) - 1))], 1) if warm else None,
        'warm_max_s': max(warm) if warm else None,
        'errors': sum(r['status'] == 'error' for r in rows),
    }


def main():
    models = sys.argv[1:] or ['qwen3:4b', 'llama3.2:3b']
    cases = OWNER + FRESH
    out = Path(__file__).resolve().parents[1] / 'docs' / 'benchmarks'
    out.mkdir(parents=True, exist_ok=True)
    summaries, detail = [], {}
    for model in models:
        print('Benchmarking', model, flush=True)
        rows = run(model, cases)
        detail[model] = rows
        summaries.append(summarise(model, rows))
        unload(model)
    stamp = time.strftime('%Y-%m-%d')
    (out / f'{stamp}-raw.json').write_text(json.dumps({'summaries': summaries, 'detail': detail}, indent=2, ensure_ascii=False), encoding='utf-8')
    lines = [f'# Model benchmark {stamp}', '', 'Through the app\'s real pipeline (`make_draft`), demo business voice and facts.', '',
             '| Model | Routing | Usable AI drafts | Passed 1st try | Cold 1st draft (s) | Warm median (s) | Warm p90 (s) | Warm max (s) | Errors |',
             '|---|---|---|---|---|---|---|---|---|']
    for s in summaries:
        lines.append(f"| {s['model']} | {s['route_accuracy']} | {s['usable_drafts']} | {s['passed_first_try']} | {s['cold_first_draft_s']} | "
                     f"{s['warm_median_s']} | {s['warm_p90_s']} | {s['warm_max_s']} | {s['errors']} |")
    for model, rows in detail.items():
        lines += ['', f'## {model}', '', '| Case | Stars | Type | Status | s | Reply / issue |', '|---|---|---|---|---|---|']
        for r in rows:
            shown = (r['reply'] or r['issues'] or r['error'] or '(held / no AI reply)').replace('|', '/').replace('\n', ' ')
            lines.append(f"| {r['id']} | {r['rating']} | {r['category']} | {r['status']} | {r['seconds']} | {shown} |")
    (out / f'{stamp}-benchmark.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines[:len(summaries) + 6]))


if __name__ == '__main__':
    main()
