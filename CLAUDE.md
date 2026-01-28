# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Pituffik is a health research grant discovery system with two components:
1. **Scheduled pipeline** (GitHub Actions) -- crawls, deduplicates, verifies, enriches, and notifies
2. **Dashboard** (Shiny for Python on Posit Connect Cloud) -- displays and filters grant opportunities

## Architecture

```
+------------------------------------------------------------------+
|  GitHub Actions (every 6 hours)                                   |
|  +----------+ +--------+ +--------+ +--------+ +------+ +------+ |
|  | Collect  |>| Dedup  |>| Verify |>| Enrich |>|  FX  |>|Notify| |
|  | (sources)|  (URLs)  |  (pages) | (Gemini) | (ECB) | (Resend)| |
|  +----------+ +--------+ +--------+ +--------+ +------+ +------+ |
+------------------------------------------------------------------+
                              |
                              v
                    data/grants.sqlite (committed)
                              |
                              v
+------------------------------------------------------------------+
|  Posit Connect Cloud                                              |
|  +------------------------------------------------------------+  |
|  | app.py (Shiny for Python)                                  |  |
|  | - Table view (sorted by deadline)                          |  |
|  | - Detail pane with Gemini rationale                        |  |
|  | - Diagnostics view                                         |  |
|  | - "New since last visit" via localStorage                  |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+
```

## Repository Layout

```
app.py                     # Shiny for Python dashboard (required at root)
requirements.txt           # Python dependencies (required at root)
data/grants.sqlite         # SQLite database (committed or artifact)
pipeline/                  # Pipeline modules
  collector.py            # Source adapters
  normaliser.py           # URL canonicalisation, deduplication
  verifier.py             # Fetch authoritative pages, extract deadlines
  enricher.py             # Gemini API calls
  notifier.py             # Resend weekly email digest
  fx.py                   # ECB currency conversion to GBP
.github/workflows/crawl.yml
```

## Database Schema

Core tables in `data/grants.sqlite`:
- `opportunities` -- canonical grant records with stable `opportunity_id`
- `opportunity_snapshots` -- raw HTML/text per crawl for change detection
- `enrichments` -- Gemini outputs (JSON) with prompt versioning
- `pipeline_runs` -- audit log per execution
- `fx_rates` -- ECB exchange rates cached by date+currency
- `user_actions` -- optional saved/hidden/notes

## Key Gemini Tasks

1. **Relevance classification**: score (0-1), health research match flag, one-sentence justification
2. **Structured extraction**: JSON with `title`, `funder_name`, `scheme_name`, `deadline_date`, `deadline_type`, `eligibility`, `career_stage`, `amount_min/max/currency`, `duration_months`, `topic_tags`
3. **Synopsis**: English summary for Scandinavian-language grant adverts
4. **Grant type fallback**: Classify ambiguous titles into 9 grant type buckets

## Grant Type Buckets

fellowship, project, programme, seed, studentship, infrastructure, centre, travel, other

## Thematic Scope

Health research broadly, prioritising:
- Psychosis and psychosis-adjacent clinical research
- Mental health, psychiatry, severe mental illness
- Organisational, occupational, work, I-O psychology
- Health psychology and behaviour change
- Epidemiology, causal inference, registry-based research
- Digital health and AI in mental health

## Language Support

English, Danish, Swedish, Norwegian -- store original text, produce English-normalised fields.

## Secrets (never commit)

- `GEMINI_API_KEY` -- for enrichment
- `RESEND_API_KEY` -- for email notifications

Store in GitHub Actions secrets and Posit Connect Cloud secret variables.

DO NOT use any emojis for this project

Write all comments and code in British English, however also use alternatives, US, Australian etc to ensure all key words in search are included
