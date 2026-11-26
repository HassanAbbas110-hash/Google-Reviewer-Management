# WebRift Review Manager

Manage Google reviews for many businesses from one local inbox. Replies are drafted by a **local** AI model (Ollama, free, on your laptop) in each business's own voice, checked by the app, and published only after a person approves them.

- **Staff (e.g. Miki)** work the inbox: read why each review was routed, edit or regenerate the draft, approve, publish, add notes, set the next action.
- **Owners** are alerted only when their judgement is needed (product safety, billing disputes, threats, serious allegations).
- **Sensitive reviews never get an AI reply.** They are held for staff investigation and a staff-written reply.
- **Publishing starts off.** Manual publishing needs the owner's recorded authorisation. Automatic publishing is a separate opt-in, for clear praise only.
- **Works without Ollama** (blank 5-star reviews still get a quick reply; everything else waits for staff) and **without Google** (fictional demo + test lab).

## Install on a clean Windows laptop

1. Install **Python 3.11+** from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*).
2. Install **Ollama** from [ollama.com/download](https://ollama.com/download), then in a terminal: `ollama pull qwen3:4b` (2.5 GB, once). Optional: the app runs without it.
3. Get this folder: GitHub Desktop → *Clone* `HassanAbbas110-hash/Google-Reviewer-Management`, or download the ZIP and extract it.
4. Double-click **`Setup.cmd`** (installs and self-tests, a few minutes).
5. Double-click **`Start.cmd`**. The browser opens at `http://127.0.0.1:8765`. Keep the black window open while you work.

Daily use: **just `Start.cmd`**. On first start, type your name in *Working as* (every action is recorded with it), then either **Create the demo shop** (fictional) or **Add a business**.

| File | What it does |
|---|---|
| `Start.cmd` | Opens the app (runs setup automatically the first time) |
| `Setup.cmd` | Installs or repairs; safe to rerun |
| `Update.cmd` | Backs up your data, pulls the newest version, reinstalls |
| `Doctor.cmd` | Checks database, Ollama, model, Google, alerts; says what to fix |
| `Connect-Google.cmd` | Connects a business to its Google Business Profile ([guide](docs/GOOGLE_SETUP.md)) |

The **Status** page in the app shows the same checks as Doctor.

## Upgrading an existing install

1. Close the Review Manager window.
2. Double-click **`Update.cmd`** (or in GitHub Desktop: *Fetch* then *Pull*, then run `Setup.cmd`).
3. Start the app. If the database needs upgrading, the app first copies it to `data\backups\reviews-schema<N>-<date>.db` and prints the path.

What changes on upgrade: existing businesses, reviews, investigations and settings are kept. Old statuses are renamed (`needs approval` → `needs review`). **Publishing is switched off for every business** (re-enable it per business after checking). The old "tone" becomes the new "voice".

**Rollback:** close the app, copy the newest file from `data\backups\` over `data\reviews.db`, and go back to the previous version (GitHub Desktop → *History* → right-click the older commit → *Checkout*, or re-extract the old ZIP and copy `data\` into it).

## How reviews are routed

Routing is rule-based code (`reviewer/policy.py`) and runs **before** any AI, identically for the demo, the test lab and the live inbox. The star rating never hides the content: a 5-star review saying the battery smoked is a safety case.

| Type | Example | What happens |
|---|---|---|
| Routine praise | "Helped me find the right tools. Friendly service." | AI draft that mentions a real detail; staff approve (or auto-publish if opted in) |
| Rating only | 5★, no text | Instant short thank-you, no AI, no invented details |
| Mixed | 4★ "Helpful advice. Parking was difficult." | AI draft that addresses both; **staff must approve** |
| Complaint | 2★ "Waited ages, staff were rude" | AI draft that acknowledges each concern without confirming allegations; **staff must approve** |
| Unclear | "Great shop but…" | Staff check |
| Sensitive | safety, injury, double charge, refunds, threats, legal, discrimination, personal details, instructions aimed at the AI | **Held. No AI reply. Investigation opened. Owner alerted** (safety, billing, threats, allegations) |

If the AI model escalates a review, the app follows; if it tries to downgrade one, the app ignores it. Every draft is then checked in code: no placeholders (`support@example.com`), only approved contact channels, no invented hours/prices/policies/numbers, no refunds/replacements/promises, no "thanks for the advice" when the shop gave the advice, every concern acknowledged, no confirming disputed staff allegations, no boilerplate like "Thank you for your kind feedback". A draft that fails gets one rewrite; if it fails again, staff write it.

## Each business's voice

On the business page: **voice** (who's speaking and how), **approved facts**, **approved contact channels**, **example replies**, sign-off, language, owner contact. Website text can be imported, but it's shown with its source and is only used after someone approves it.

## Publishing safeguards (checked on the server at the moment of sending)

Business publishing mode, owner authorisation, Google connection, the exact approved text (hash), unchanged review, unchanged business details, no failed checks, global pause, and Google's rate limit. Then the app reads the review from Google: if someone already replied there, or the customer edited the review, nothing is sent. A double click or retry can't post twice (atomic claim). If a send times out, the case shows **Publish result unknown** and the only way forward is **Check Google**, which reads back before anything is resent.

## Data, privacy, retention

Everything stays on this computer in `data\`. Google tokens and the SMTP password live in Windows Credential Manager, never in files. Review text and drafts are deleted after 29 days (Google allows at most 30). Open investigations keep their status, notes and history without the review text. Disconnecting a business deletes its token and cached review text. Configuration-only backups (no reviews, no tokens): `.venv\Scripts\python.exe -m reviewer backup settings.json` / `restore settings.json`.

Optional owner emails: `.venv\Scripts\python.exe -m reviewer smtp --host smtp.yourmail.com --sender alerts@you.com --user alerts@you.com` (password prompt). Emails never include review text. Without SMTP, alerts are dashboard-only and stay visible until someone marks "Owner told".

## Models and speed

See [docs/MODEL_BENCHMARK.md](docs/MODEL_BENCHMARK.md). Drafting runs in the background; a slow model never blocks the dashboard. Timeout is set on the Status page (default 120 s); a timed-out draft shows *Draft failed* with a retry button. Rerun the benchmark on any laptop:

```powershell
.venv\Scripts\python.exe tools\benchmark.py qwen3:4b llama3.2:3b
```

## Development

```powershell
.venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"
```

| Area | Files |
|---|---|
| Routing + publish eligibility | `reviewer/policy.py`, tests `tests/test_policy.py` |
| Drafting, voice, reply checks, Ollama | `reviewer/ai.py`, tests `tests/test_replies.py` |
| Workflow (sync, draft, approve, publish, reconcile, cases) | `reviewer/engine.py`, tests `tests/test_workflow.py` |
| Storage, migrations, audit, alerts, retention | `reviewer/database.py` |
| Google adapter / fictional adapter | `reviewer/google.py`, `reviewer/mock_google.py` |
| Dashboard | `reviewer/web.py`, `reviewer/templates/`, tests `tests/test_web.py` |

This is a single-computer app for WebRift staff, bound to 127.0.0.1. Don't expose it on a network without adding real user accounts.
