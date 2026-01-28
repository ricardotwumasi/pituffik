# Pituffik: Research Grant Radar for Psychology, Psychiatry, and Health

## 1. Overview

Pituffik is a sibling project to McMurdo. It reuses the same operational pipeline and lightweight Python stack (Python, httpx, feedparser, BeautifulSoup, lxml, SQLite, GitHub Actions, Shiny for Python, Gemini, and email delivery) but targets externally advertised research funding opportunities rather than academic job adverts.

McMurdo’s architecture is explicitly a scheduled GitHub Actions pipeline that performs “Collect → Dedup → Verify → Enrich → Notify”, persists into a committed SQLite database, and serves a public Shiny for Python dashboard on Posit Connect Cloud, with Gemini-based enrichment and Resend-based email digests. citeturn12view0turn12view2  
Pituffik should preserve this pattern, swapping “jobs” for “grants” while retaining the reliability properties (idempotent crawls, deduplication, verification, traceable enrichment, and delta-based notifications).

Pituffik’s primary objective is coverage with high precision. It should cast a wide net across major public funders, charities, foundations, and selected institutional funding pages, then use deterministic verification plus Gemini enrichment to reduce noise and improve triage.

## 2. Product goals and success criteria

Pituffik exists to answer a practical question: “What substantial funding calls relevant to my research profile are newly open, still open, or approaching deadline, and why should I care?”

A successful v1, after two weeks of operation, should show: (a) stable ingestion from the initial source set with minimal breakage, (b) low duplicate rate across syndicators and reposts, (c) correct open versus closed status for the majority of opportunities where a deadline is advertised, (d) conservative but useful amount extraction and USD conversion when amounts are provided, and (e) email digests that primarily contain genuinely new and relevant opportunities rather than repeats.

## 3. Scope and filtering policy

### 3.1 Subject coverage

Pituffik covers research grants broadly within psychology, psychiatry, mental health, health psychology, behavioural science, occupational and organisational psychology, implementation science, health services research, and adjacent areas that plausibly support work in psychosis, functional outcomes, work and wellbeing, or computational and registry-based mental health research.

Keywords and topic tags are seeded from your CV and then refined through observed performance. The initial keyword universe should include: psychosis, schizophrenia spectrum, first-episode psychosis, early intervention, severe mental illness, antipsychotics and functional outcomes, employment and vocational rehabilitation, supported employment and IPS, stigma and discrimination, occupational health, organisational psychology, work stress and burnout, wellbeing and behaviour change, causal inference and DAGs, registry and administrative data, longitudinal cohort studies, meta-analysis and evidence synthesis, AI and mental health, and digital phenotyping.

### 3.2 Award size threshold

Pituffik prioritises opportunities whose advertised total value is at least USD 100,000 (or currency-equivalent). This filter is applied using extracted monetary information and currency conversion as described in Section 7.

Pituffik should also store opportunities that do not state a value, because these may be strategically important. However, they must be visibly flagged as “amount unknown”, and the default dashboard and email views should focus on those that meet the threshold or have high-confidence evidence that they likely exceed it.

### 3.3 Geography and languages

Pituffik is global by design, with a “UK first” lens but broad international coverage.

Pituffik must handle Scandinavian postings in Danish, Swedish, and Norwegian. The dashboard should present an English synopsis while preserving critical original-language constraints (for example, legal eligibility language) when present. McMurdo already establishes this multilingual enrichment pattern via Gemini. citeturn12view0turn12view1

## 4. System architecture

Pituffik mirrors McMurdo’s split architecture.

The pipeline runs on GitHub Actions on a schedule (recommended: every 6 hours, matching McMurdo) and performs collection, deduplication, verification, enrichment, persistence, and notification. citeturn12view0turn12view2  
The dashboard is deployed as a public Shiny for Python application on Posit Connect Cloud and reads a committed SQLite database in read-only mode. citeturn12view0turn12view2

This design intentionally avoids a paid backend. The trade-off is that the database is committed to the repository and grows over time. SQLite WAL mode can keep reads responsive while GitHub Actions updates the file. citeturn12view2turn12view3

## 5. Data model

Pituffik uses SQLite with a stable, auditable schema. It should be intentionally similar to McMurdo’s schema and repository conventions (seed schema SQL, a single canonical table, and support tables for enrichment and snapshots). citeturn12view2

### 5.1 Core table: `opportunities`

Required fields:

`opportunity_id` (stable primary key), `title`, `funder_name`, `scheme_name`, `url_canonical`, `url_source`, `country_or_region`, `language`, `deadline_date`, `deadline_type` (fixed, rolling, none, unknown), `open_date` (nullable), `status` (open, closed, unverified), `summary_en`, `topics` (normalised tag list), `eligibility` (short structured text), `career_stage` (nullable), `amount_min`, `amount_max`, `amount_currency`, `amount_usd_min`, `amount_usd_max`, `amount_confidence` (high, medium, low, unknown), `duration_months` (nullable), `host_institution_required` (boolean or nullable), `first_seen_at`, `last_seen_at`, `last_verified_at`, `relevance_score`, and `relevance_rationale`.

### 5.2 Snapshot table: `opportunity_snapshots`

Fields:

`opportunity_id`, `captured_at`, `http_status`, `content_type`, `source_hash`, `extracted_text_excerpt`, `extractor_version`, and `notes`.

The purpose is traceability. When an opportunity changes (deadline moved, amount clarified), Pituffik can show what changed and when, without relying on the funder to keep older versions visible.

### 5.3 Enrichment table: `enrichments`

Fields:

`opportunity_id`, `created_at`, `model_name`, `prompt_version`, `response_json`, `confidence`, and optional token and cost metadata.

Prompt and schema versioning are first-class. This is non-negotiable if the system will be trusted for deadline and eligibility triage.

## 6. Pipeline stages

Pituffik should preserve McMurdo’s functional staging, with grant-specific substitutions.

McMurdo’s pipeline modules include a main orchestrator, a collector registry, a normaliser (URL canonicalisation, deduplication), a verifier (page verification, closing date extraction), an enricher (Gemini integration), and a notifier (email digest), plus a database access layer and Pydantic models. citeturn12view2  
Pituffik should adopt the same module pattern and naming, but for grants.

### 6.1 Collect

Collection uses three adapter modes, matching McMurdo’s existing technology choices (RSS via feedparser; APIs via httpx; HTML via BeautifulSoup and lxml). citeturn12view2turn12view3

The output of collection is a list of candidate opportunities with minimal metadata: source name, source URL, title, link, and any dates or values the source explicitly provides.

### 6.2 Normalise and deduplicate

Normalisation includes URL canonicalisation and stable signature generation.

Deduplication is two-stage: exact match on canonical URL or stable signature, then fuzzy matching on title plus funder plus deadline window. McMurdo’s stack suggests url-normalize plus rapidfuzz for fuzzy matching. citeturn12view2turn12view3  
Pituffik should reuse these choices to remain consistent.

### 6.3 Verify

Verification is the most important “anti-noise” stage for grants.

Pituffik should fetch the authoritative opportunity page, confirm that it is reachable, and attempt to extract: whether applications are open, whether the deadline has passed, whether there are rolling deadlines, and whether the call has been superseded or withdrawn.

Verification must be conservative. If the page is reachable but the parser cannot confidently extract dates, status remains “unverified” and the dashboard should clearly show that.

### 6.4 Enrich (Gemini)

Enrichment is used for tasks that benefit from semantic interpretation: extracting structured eligibility constraints from prose, identifying whether the call is relevant to your thematic profile, producing short English synopses, and extracting monetary ranges from human-formatted text.

McMurdo uses Gemini 1.5 Flash for relevance scoring, structured extraction, and English synopses for Scandinavian adverts. citeturn12view0turn12view2  
Pituffik should do the same, but with a grant-focused schema and prompt templates.

Enrichment must return strict JSON conforming to a Pydantic schema, including evidence snippets for critical extracted fields (amount and deadline). If Gemini output fails validation, the system should retry once with a stricter “repair” prompt, then fall back to partial enrichment.

### 6.5 Persist

Persist updates the canonical record, writes a snapshot, and stores the enrichment output with prompt versioning. Persist must be idempotent, so re-running a workflow produces the same database state given the same inputs.

### 6.6 Notify

Notify computes the delta since the last successful run and sends email only when new, relevant opportunities are present.

McMurdo uses Resend for digest email delivery. citeturn12view0turn12view2  
Pituffik should keep the same provider unless you explicitly choose otherwise, to reduce operational variability.

## 7. Amount extraction and currency conversion

### 7.1 Amount extraction

Pituffik should extract monetary values from authoritative pages using a hybrid strategy.

Deterministic extraction should capture common formats: “up to £X”, “€X–€Y”, “DKK X million”, “total budget”, and “maximum award”.

Gemini extraction should be used when deterministic parsing fails, but Gemini must provide the matched text evidence and clearly indicate uncertainty.

### 7.2 Currency conversion

Pituffik should normalise amounts to USD for filtering and cross-country comparison.

The recommended reference source is the European Central Bank’s daily exchange rate XML feed, which provides a stable, openly accessible set of reference rates. citeturn8search3turn8search7  
Pituffik should cache a daily rates snapshot in the repository (for example, `data/fx/YYYY-MM-DD.json`) so that historical conversions remain reproducible.

The system should treat conversion as informational, not accounting grade. This should be explicit in UI text, mirroring the ECB’s framing that reference rates are published for information. citeturn8search7

## 8. Source strategy and initial source list

Pituffik treats syndicators and aggregators primarily as discovery mechanisms and then attempts to verify against the authoritative opportunity page, since reposts and stale listings are common.

### 8.1 Core high-coverage portals

UKRI “Funding finder” is a UK-wide entry point for opportunities across UKRI councils and Innovate UK, and it exposes an RSS feed on the listing pages. citeturn8search0turn8search8

The EU Funding and Tenders Portal supports subscribing to a Funding Opportunities RSS feed for updates on new calls. citeturn8search2

Grants.gov provides a documented API, including a search endpoint for opportunities. citeturn8search1turn8search5  
This is a major US federal discovery channel and is especially useful for broad health and behavioural science calls, even when the downstream funder is NIH or another agency.

NIH offers RSS feeds and subscription routes for grants news and the NIH Guide for Grants and Contracts. citeturn9search0turn9search20  
Pituffik should treat these as supplementary and then verify on the underlying FOA or notice pages.

NSF provides RSS feeds for funding opportunities and upcoming due dates. citeturn9search1turn9search13  
This can improve coverage for behavioural science adjacent programmes and methods funding.

### 8.2 Scandinavia and Nordic sources

The Swedish Research Council provides an RSS feed for calls. citeturn9search3turn10search16

The Research Council of Norway provides RSS feeds, including one for “Utlysninger”, and maintains an index of its available feeds. citeturn10search0turn10search4

The Research Council of Finland publishes open calls on a stable “calls for applications” page; this can be ingested via HTML, and later expanded using national aggregation services. citeturn10search7turn11search1

Finland’s Research.fi service lists funding calls and can act as a broad discovery channel for Finnish opportunities if scraping is permitted under its terms. citeturn11search17

Independent Research Fund Denmark and Innovation Fund Denmark are high-value targets, but their calls are not uniformly presented via a single RSS interface. V1 should implement dedicated HTML adapters for their call and news pages, with conservative verification and explicit “unverified” status when extraction is ambiguous. citeturn10search9turn10search17

### 8.3 Major charities and foundations (initial adapters)

In v1, Pituffik should implement dedicated adapters for a small set of high-yield charitable and foundation funders relevant to mental health and behavioural science, prioritising those with stable “scheme” pages and consistent URL patterns. Wellcome is a prototypical example of a funder with scheme pages suited to structured extraction. citeturn8search0

This funder set is intended to be expanded iteratively, driven by what appears in your inbox and what your collaborators repeatedly cite as relevant.

### 8.4 Institutional funding pages

Institutional sites are heterogeneous and expensive to maintain. Pituffik v1 should support them via an explicit “seed list” that you curate, rather than trying to discover them automatically.

Each institutional seed entry should include: the institution name, the funding page URL, the country, the typical language, and an adapter strategy (RSS, HTML list page, HTML PDF index). The pipeline should treat institutional adapters as “best effort” and keep a clear log of failures without breaking the whole run.

## 9. Dashboard requirements (Shiny for Python)

The dashboard is public and deployed to Posit Connect Cloud, as with McMurdo. citeturn12view0turn12view2  
It reads the SQLite database committed to git and provides a fast triage experience.

The default view is a filterable table of open opportunities. Filters should include deadline window, country or region, language, funder type, amount threshold met, amount confidence, and topic tags.

Selecting a row opens a detail pane showing: English synopsis, eligibility summary, extracted deadline and evidence snippet, extracted amount and evidence snippet, relevance rationale, and both the canonical and source links.

The dashboard must include a “New since last visit” badge, implemented client-side via a browser-stored timestamp that is compared to `first_seen_at` fields, matching the behaviour you requested for McMurdo.

## 10. Email notifications

Pituffik sends a digest email when there are newly discovered opportunities that satisfy the configured relevance threshold and the amount policy.

Each digest entry should contain: title, funder and scheme, deadline (or rolling indicator), amount with confidence and USD estimate, region and eligibility headline, a 2 to 3 sentence synopsis, and a single authoritative link.

Email delivery should use the same provider as McMurdo to reduce integration risk (Resend). citeturn12view0turn12view2

## 11. Configuration and secrets

Pituffik should follow McMurdo’s pattern of a repository `.env.example` plus GitHub Actions secrets for production. McMurdo uses `GEMINI_API_KEY`, `RESEND_API_KEY`, and `NOTIFICATION_EMAIL` as core secrets. citeturn12view2  
Pituffik should add: a minimum USD threshold (`MIN_USD_AMOUNT`, default 100000), a relevance threshold (`MIN_RELEVANCE_SCORE`, default 0.65), and optional source toggles.

## 12. Repository layout (proposed)

Pituffik should closely mirror McMurdo’s layout to maximise code reuse and reduce cognitive overhead. McMurdo’s layout includes `app.py`, `requirements.txt`, `data/jobs.sqlite`, a seed schema, configuration, pipeline modules, templates, tests, and workflows. citeturn12view2

Pituffik should use:

`app.py` for the Shiny dashboard  
`data/grants.sqlite` for the committed SQLite database  
`data/seed_schema.sql` for DDL  
`pipeline/` for orchestrator, collector, normaliser, verifier, enricher, notifier, db, models, adapters, prompts  
`templates/` for email templates  
`config/` for source definitions and keyword profiles  
`.github/workflows/` for scheduled crawl and tests

## 13. Compliance, politeness, and operational guardrails

Pituffik must respect robots.txt and site terms where applicable, adopt low request rates, and use conditional requests (ETag, If-Modified-Since) when supported to reduce load. The system should log adapter-level failures rather than failing the run, because long-tail institutional sources will be brittle.

The system must avoid scraping paywalled subscription databases unless you have explicit institutional permission and credentials configured. These can be added later as optional adapters.

## 14. Milestones for v1

Milestone 1 is an operational copy of McMurdo with a new schema and a minimal set of working adapters, deployed publicly, with email digests functioning.

Milestone 2 expands the source set, improves amount parsing and deadline verification, and establishes a stable “relevance” calibration so that the digest remains high signal.

Milestone 3 adds funder-specific heuristics, for example, recognising recurring large-scale programme calls where award size is reliably above threshold even if not stated on the listing.

---

## Appendix: Key external references

UKRI Funding Finder: https://www.ukri.org/opportunity/ citeturn8search0  
EU Funding and Tenders Portal (RSS mention in Online Manual): https://webgate.ec.europa.eu/funding-tenders-opportunities/spaces/OM/pages/1867921/Search%2Bfunding%2Bopportunities%2B%E2%80%94%2BFind%2Ba%2Bcall citeturn8search2  
Grants.gov API Guide: https://grants.gov/api/api-guide citeturn8search1  
NIH RSS and subscriptions: https://grants.nih.gov/news-events/subscribe-follow/email-updates-and-rss-feeds citeturn9search0  
NSF RSS: https://www.nsf.gov/rss citeturn9search1  
Swedish Research Council RSS: https://www.vr.se/english/applying-for-funding/calls-and-decisions/calls-as-rss-feed.html citeturn9search3  
Research Council of Norway RSS index: https://www.forskningsradet.no/en/rss-feed/ citeturn10search0  
ECB daily XML rates: https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml citeturn8search3  
Posit Connect Cloud: https://connect.posit.cloud/ citeturn12view2

Some funders to add:

# From the circular’s “Ongoing calls” / “January” items (external hosting pages)

https://www.ukri.org/opportunity/bbsrc-2025-transformative-research-technologies-25trt/
https://www.arthritis-uk.org/research-professionals/research-opportunities-and-funding/open-and-future-funding-calls/research-facilitation-fund-2026/
https://royalsociety.org/grants/research-professorship/
https://wellcome.org/grant-funding/schemes/early-career-awards
https://royalsociety.org/grants/faraday-discovery-fellowships/accelerated-international-route/
https://www.nihr.ac.uk/funding/research-patient-benefit-november-2025/2025425-2025426-2025427
https://wellcome.org/research-funding/schemes/genomics-in-context-awards
https://wellcome.org/research-funding/schemes/wellcome-career-development-awards
https://wellcome.org/research-funding/schemes/wellcome-discovery-awards

# From “Highlighted Research Grants”

https://action.org.uk/research/apply-research-grant/apply-project-grant
https://www.leverhulme.ac.uk/news/RPG2026
https://acmedsci.ac.uk/grants-and-schemes/grant-schemes/starter-grants
https://www.alzheimers.org.uk/what-we-do/researchers/our-funding-schemes/project-grants
https://www.nihr.ac.uk/funding/eme-programme-researcher-led/2025458
https://www.nuffieldfoundation.org/funding-for-research/main-grants
https://www.nihr.ac.uk/research-funding/funding-programmes/public-health-research
https://www.ukri.org/opportunity/metascience-research-grants-round-2/

# From “Internal Funding & Triage” (includes KCL internal pages)

https://www.ukri.org/opportunity/future-leaders-fellowship-round-11/
https://internal.kcl.ac.uk/about/International/Funding-Opportunities/partnership-fund/partnership-fund
https://www.kcl.ac.uk/impact/fund

# From “Highlighted Personal Awards & Research Fellowships”

https://www.embo.org/funding-awards/fellowships/postdoctoral-fellowships
https://cifarportal.smapply.io/prog/jacobs_cifar_research_fellowship_program_/
https://www.ukri.org/opportunity/adr-uk-research-fellowships-2025/
https://www.alzheimersresearchuk.org/grants/research-fellowship/
https://www.alzheimersresearchuk.org/grants/senior-research-fellowship/
https://www.nihr.ac.uk/funding/development-and-skills-enhancement-dse-award-cohort-9/2025464

# From “Travel grants, Prizes and Studentships”

https://www.alzheimersresearchuk.org/grants/phd-scholarship/
https://www.maudsleybrc.nihr.ac.uk/academic-career-development/current-opportunities/

# From “Always open calls”

https://www.ukri.org/opportunity/mrc-research-grant-applicant-led/
https://www.ukri.org/opportunity/mrc-new-investigator-research-grant-applicant-led/
https://www.ukri.org/opportunity/mrc-partnership-grant-applicant-led/
https://www.ukri.org/opportunity/esrc-responsive-mode-research-grants-round-two/
https://www.ukri.org/opportunity/esrc-responsive-mode-new-investigator-grants-round-two/
https://www.ukri.org/opportunity/esrc-responsive-mode-secondary-data-analysis-round-two/
https://www.ukri.org/opportunity/epsrc-standard-research-grant-nov-2023-responsive-mode/
https://www.ukri.org/opportunity/epsrc-new-investigator-award-nov-2023-responsive-mode/
https://www.ukri.org/opportunity/epsrc-programme-grant-outline-stage/
https://www.kingshealthpartners.org/our-work/personalised-health/centre-translational-medicine/patient-and-public-involvementengagement-pre-grant-support-fund

# KCL ESRC IAA (public landing pages; the specific “New Government Fund” details may sit behind staff-only pages)

https://www.kcl.ac.uk/research/funding/esrc-impact-acceleration-account
https://www.kcl.ac.uk/research/kings-innovation-enterprise/impact-acceleration
```text
 [oai_citation:2‡ioppandn.newsweaver.com](https://ioppandn.newsweaver.com/funding-opportunities/pkzsyo54zxc?a=1&lang=en&p=66277748&t=28631978)
