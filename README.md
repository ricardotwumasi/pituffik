# Pituffik

Health research grant discovery system. Crawls major funders, classifies and enriches opportunities with Gemini, and serves a colourful Shiny dashboard.

## Architecture

**Scheduled pipeline** (GitHub Actions, every 6 hours):
Collect > Deduplicate > Verify > Enrich (Gemini) > FX Convert (ECB) > Notify (Resend)

**Dashboard** (Shiny for Python on Posit Connect Cloud):
Filterable table of open grant opportunities with detail pane, diagnostics, and "new since last visit" tracking.

## Sources

### Tier 1 -- APIs / RSS
- NIH Grants RSS (US)
- Grants.gov REST API (US federal)
- EU Funding & Tenders Portal
- UKRI Funding Finder (all UK councils)
- NSF Funding RSS (US)

### Tier 2 -- HTML Scraping
- NIHR (UK health research)
- Wellcome Trust
- Cancer Research UK
- British Heart Foundation
- Alzheimer's Research UK
- Novo Nordisk Foundation (Denmark)
- Swedish Research Council (Vetenskapsradet)
- Research Council of Norway (Forskningsradet)

### Seed Pages
User-editable `config/seed_urls.yml` -- add any funder URL, no code needed. Pre-populated with 40+ URLs from UKRI, Wellcome, NIHR, Royal Society, Leverhulme, and more.

## Thematic Scope

Psychology, psychiatry, mental health, health psychology, behavioural science, occupational psychology, implementation science, health services research, and adjacent areas. Prioritises opportunities >GBP 70,000.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run pipeline (dry run, no email)
python -m pipeline.main --dry-run

# Run dashboard locally
shiny run app.py

# Run tests
pytest tests/ -v
```

## Configuration

Copy `.env.example` to `.env` and set:
- `GEMINI_API_KEY` -- Gemini 2.5 Flash-Lite for enrichment
- `RESEND_API_KEY` -- email digest delivery
- `NOTIFICATION_EMAIL` -- recipient address

## Adding New Sources

Edit `config/seed_urls.yml` and add an entry:
```yaml
- url: "https://funder.org/grants/open-call"
  funder: "Funder Name"
  deadline_type: rolling  # optional
```

The pipeline will scrape the page, extract grant information, and enrich it with Gemini on the next run.

## Technology

- Python, httpx, feedparser, BeautifulSoup, Gemini 2.5 Flash-Lite
- Shiny for Python on Posit Connect Cloud
- SQLite (committed to git)
- GitHub Actions (crawl every 6 hours)
- Resend (weekly email digests)
- ECB daily exchange rates (currency conversion)

## AI Assistance Statement

This project was built with the assistance of Claude Code powered by Opus 4.5.

## Licence

MIT
