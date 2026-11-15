# Google Reviewer Management

WebRift's local-first Google review manager. One installation, separate business settings. No paid AI service or hosting is required for the planned local version.

## Current status

Initial processing foundation only. Google OAuth, live review polling/publishing, Ollama generation, website extraction, dashboard, alerts and reporting are **not implemented yet**. No live Google replies are sent by this version.

Run tests with Python 3.11+:

```powershell
python -m unittest discover -s tests -v
```

Do not commit credentials, business data, tokens or local databases. Production activation requires Google API approval, owner consent, model evaluation and live pilot verification. This folder was prepared in the remote workspace, not on the owner's laptop.

## Laptop setup once GitHub repository exists

In GitHub Desktop select File > Clone repository, select the new repository, and choose a local path ending in `Google Reviewer Management`. Alternatively extract the supplied project archive into that folder. The archive contains no credentials or client data.

## Roadmap

1. Durable business-isolated review queue and explicit publishing safeguards.
2. Google desktop OAuth, location selection, paginated review polling, reconnection.
3. Local Ollama structured generation and conservative escalation.
4. Local dashboard, approved business facts, owner controls.
5. Website extraction with private-network blocking; summaries, alerts, backups and retention.
6. Pilot in approval mode, then explicitly enable routine automatic publishing.
