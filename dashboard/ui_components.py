"""UI components for the Pituffik Shiny dashboard.

Provides reusable UI elements: detail panels, badges, amount displays,
and localStorage JavaScript for "new since last visit" tracking.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from shiny import ui

from dashboard.filters import GRANT_TYPE_LABELS


def opportunity_detail_panel(opp: dict) -> ui.Tag:
    """Render a detailed view of a single grant opportunity.

    Args:
        opp: An opportunity dict from the database.

    Returns:
        A Shiny UI Tag with the detail panel content.
    """
    elements = []

    # Title and link
    title = opp.get("title") or "Untitled opportunity"
    url = opp.get("url_canonical") or opp.get("url_source", "#")
    elements.append(
        ui.h3(ui.a(title, href=url, target="_blank"))
    )

    # Funder and scheme
    meta_parts = []
    if opp.get("funder_name"):
        meta_parts.append(opp["funder_name"])
    if opp.get("scheme_name"):
        meta_parts.append(opp["scheme_name"])
    if opp.get("country_or_region"):
        meta_parts.append(opp["country_or_region"])
    if meta_parts:
        elements.append(ui.p(" -- ".join(meta_parts), class_="text-muted"))

    # Badges row
    badges = []

    # Relevance score badge
    if opp.get("relevance_score") is not None:
        score = opp["relevance_score"]
        score_pct = f"{score * 100:.0f}%"
        if score >= 0.7:
            badges.append(
                ui.span(f"{score_pct} match", class_="badge badge-relevance-high me-1")
            )
        elif score >= 0.5:
            badges.append(
                ui.span(f"{score_pct} match", class_="badge badge-relevance-medium me-1")
            )
        else:
            badges.append(
                ui.span(f"{score_pct} match", class_="badge badge-relevance-low me-1")
            )

    # Health research match badge
    if opp.get("health_research_match"):
        badges.append(
            ui.span("Health research", class_="badge badge-domain-match me-1")
        )

    # Grant type badge (violet)
    if opp.get("grant_type_bucket") and opp["grant_type_bucket"] != "other":
        gt_label = GRANT_TYPE_LABELS.get(
            opp["grant_type_bucket"],
            opp["grant_type_bucket"].replace("_", " ").title(),
        )
        badges.append(
            ui.span(gt_label, class_="badge badge-grant-type me-1")
        )

    # Funder badge (teal outline)
    if opp.get("funder_name"):
        badges.append(
            ui.span(opp["funder_name"], class_="badge badge-funder me-1")
        )

    # Deadline urgency badge
    deadline_badge = deadline_urgency_badge(opp.get("deadline_date"))
    if deadline_badge is not None:
        badges.append(deadline_badge)

    if badges:
        elements.append(ui.div(*badges, class_="mb-2"))

    # Key details table
    details = []
    if opp.get("deadline_date"):
        details.append(("Deadline", opp["deadline_date"]))
    if opp.get("deadline_type") and opp["deadline_type"] != "unknown":
        details.append(("Deadline type", opp["deadline_type"].title()))
    if opp.get("open_date"):
        details.append(("Opens", opp["open_date"]))
    if opp.get("career_stage"):
        details.append(("Career stage", opp["career_stage"].replace("_", " ").title()))
    if opp.get("duration_months"):
        details.append(("Duration", f"{opp['duration_months']} months"))
    if opp.get("host_institution_required") is not None:
        details.append((
            "Host institution required",
            "Yes" if opp["host_institution_required"] else "No",
        ))
    if opp.get("language") and opp["language"] != "en":
        details.append(("Language", opp["language"].upper()))
    if opp.get("source_id"):
        details.append(("Source", opp["source_id"]))
    if opp.get("first_seen_at"):
        details.append(("First seen", opp["first_seen_at"][:10]))

    if details:
        rows = [
            ui.tags.tr(ui.tags.td(ui.strong(k)), ui.tags.td(v))
            for k, v in details
        ]
        elements.append(
            ui.tags.table(
                ui.tags.tbody(*rows),
                class_="table table-sm table-borderless",
            )
        )

    # Amount display
    amt = amount_display(opp)
    if amt is not None:
        elements.append(ui.div(ui.strong("Funding amount: "), amt, class_="mb-2"))

    # Eligibility
    if opp.get("eligibility"):
        elements.append(
            ui.div(
                ui.strong("Eligibility: "),
                opp["eligibility"],
                class_="mb-2",
            )
        )

    # Topic tags (violet pills)
    tags = opp.get("topics", [])
    if tags and isinstance(tags, list):
        tag_badges = [
            ui.span(tag, class_="badge badge-topic me-1 mb-1")
            for tag in tags
        ]
        elements.append(ui.div(ui.strong("Topics: "), *tag_badges, class_="mb-2"))

    # Relevance rationale
    if opp.get("relevance_rationale"):
        elements.append(
            ui.div(
                ui.strong("Relevance rationale: "),
                opp["relevance_rationale"],
                class_="mb-2 fst-italic",
            )
        )

    # Synopsis
    if opp.get("summary_en"):
        elements.append(
            ui.div(
                ui.strong("Synopsis: "),
                opp["summary_en"],
                class_="mb-2",
            )
        )

    # Canonical link
    if url and url != "#":
        elements.append(
            ui.div(
                ui.a("View original listing", href=url, target="_blank",
                     class_="btn btn-sm btn-pituffik-primary mt-2"),
                class_="mb-2",
            )
        )

    return ui.div(*elements, class_="opportunity-detail p-3")


def new_since_last_visit_js() -> str:
    """Return JavaScript for tracking 'new since last visit' via localStorage.

    The script stores the current timestamp in localStorage on page load,
    and exposes the previous timestamp as a Shiny input value.
    """
    return """
    (function() {
        const STORAGE_KEY = 'pituffik_last_seen_ts';
        const previous = localStorage.getItem(STORAGE_KEY) || '1970-01-01T00:00:00';
        const now = new Date().toISOString();

        // Set Shiny input value so the server can use it
        if (typeof Shiny !== 'undefined') {
            Shiny.setInputValue('last_seen_ts', previous);
        } else {
            document.addEventListener('shiny:connected', function() {
                Shiny.setInputValue('last_seen_ts', previous);
            });
        }

        // Update the stored timestamp
        localStorage.setItem(STORAGE_KEY, now);
    })();
    """


def diagnostics_panel(diag: dict) -> ui.Tag:
    """Render the diagnostics view with gradient value boxes.

    Args:
        diag: Diagnostics data dict from data_access.get_diagnostics().

    Returns:
        A Shiny UI Tag with diagnostics content.
    """
    elements = []

    # Summary cards with gradient backgrounds
    elements.append(
        ui.layout_columns(
            _gradient_value_box(
                "Total Opportunities",
                str(diag["total_opportunities"]),
                "value-box-teal",
            ),
            _gradient_value_box(
                "Open",
                str(diag["open_opportunities"]),
                "value-box-emerald",
            ),
            _gradient_value_box(
                "Closed",
                str(diag["closed_opportunities"]),
                "value-box-coral",
            ),
            _gradient_value_box(
                "Enrichments",
                str(diag["enrichment_count"]),
                "value-box-violet",
            ),
            col_widths=[3, 3, 3, 3],
        )
    )

    # By source
    if diag.get("sources"):
        source_rows = [
            ui.tags.tr(
                ui.tags.td(s["source_id"]),
                ui.tags.td(str(s["n"])),
            )
            for s in diag["sources"]
        ]
        elements.append(
            ui.div(
                ui.h4("Opportunities by source"),
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(ui.tags.th("Source"), ui.tags.th("Count"))
                    ),
                    ui.tags.tbody(*source_rows),
                    class_="table table-sm table-striped",
                ),
                class_="mb-4",
            )
        )

    # By grant type
    if diag.get("grant_types"):
        gt_rows = [
            ui.tags.tr(
                ui.tags.td(
                    GRANT_TYPE_LABELS.get(
                        g["grant_type_bucket"],
                        g["grant_type_bucket"].replace("_", " ").title(),
                    )
                ),
                ui.tags.td(str(g["n"])),
            )
            for g in diag["grant_types"]
        ]
        elements.append(
            ui.div(
                ui.h4("Opportunities by grant type"),
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(ui.tags.th("Grant Type"), ui.tags.th("Count"))
                    ),
                    ui.tags.tbody(*gt_rows),
                    class_="table table-sm table-striped",
                ),
                class_="mb-4",
            )
        )

    # By funder
    if diag.get("funders"):
        funder_rows = [
            ui.tags.tr(
                ui.tags.td(f["funder_name"]),
                ui.tags.td(str(f["n"])),
            )
            for f in diag["funders"]
        ]
        elements.append(
            ui.div(
                ui.h4("Opportunities by funder"),
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(ui.tags.th("Funder"), ui.tags.th("Count"))
                    ),
                    ui.tags.tbody(*funder_rows),
                    class_="table table-sm table-striped",
                ),
                class_="mb-4",
            )
        )

    # By country/region
    if diag.get("countries"):
        country_rows = [
            ui.tags.tr(
                ui.tags.td(c["country_or_region"]),
                ui.tags.td(str(c["n"])),
            )
            for c in diag["countries"]
        ]
        elements.append(
            ui.div(
                ui.h4("Opportunities by country / region"),
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(ui.tags.th("Country / Region"), ui.tags.th("Count"))
                    ),
                    ui.tags.tbody(*country_rows),
                    class_="table table-sm table-striped",
                ),
                class_="mb-4",
            )
        )

    # Latest pipeline run
    if diag.get("latest_run"):
        run = diag["latest_run"]
        elements.append(
            ui.div(
                ui.h4("Latest pipeline run"),
                ui.p(f"Started: {run.get('started_at', 'N/A')}"),
                ui.p(f"Status: {run.get('status', 'N/A')}"),
                ui.p(
                    f"Found: {run.get('opportunities_found', 0)}, "
                    f"New: {run.get('opportunities_new', 0)}, "
                    f"Updated: {run.get('opportunities_updated', 0)}"
                ),
                ui.p(f"Enrichments: {run.get('enrichments_made', 0)}"),
                class_="mb-4",
            )
        )

    return ui.div(*elements)


def deadline_urgency_badge(deadline_date: Optional[str]) -> Optional[ui.Tag]:
    """Return a coloured badge indicating deadline urgency.

    Args:
        deadline_date: ISO-format date string (YYYY-MM-DD) or None.

    Returns:
        A Shiny UI Tag with an appropriately coloured badge, or None if
        no deadline is set.
    """
    if not deadline_date:
        return None

    try:
        deadline = datetime.strptime(deadline_date[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

    today = date.today()
    days_remaining = (deadline - today).days

    if days_remaining < 0:
        return ui.span(
            f"Past deadline ({deadline_date[:10]})",
            class_="badge badge-deadline-past me-1",
        )
    elif days_remaining < 7:
        return ui.span(
            f"{days_remaining}d remaining",
            class_="badge badge-deadline-urgent me-1",
        )
    elif days_remaining < 30:
        return ui.span(
            f"{days_remaining}d remaining",
            class_="badge badge-deadline-soon me-1",
        )
    else:
        return ui.span(
            f"{days_remaining}d remaining",
            class_="badge badge-deadline-ok me-1",
        )


def amount_display(opp: dict) -> Optional[ui.Tag]:
    """Render the funding amount with currency and USD conversion.

    Shows the original currency range and, where available, a USD
    equivalent.  Uses a gold accent when the amount confidence is high.

    Args:
        opp: An opportunity dict.

    Returns:
        A Shiny UI Tag with formatted amount, or None if no amount data.
    """
    amount_min = opp.get("amount_min")
    amount_max = opp.get("amount_max")
    currency = opp.get("amount_currency", "")
    confidence = opp.get("amount_confidence", "unknown")
    usd_min = opp.get("amount_usd_min")
    usd_max = opp.get("amount_usd_max")

    if amount_min is None and amount_max is None:
        return None

    # Build the primary amount string
    parts = []
    if amount_min is not None:
        parts.append(f"{amount_min:,.0f}")
    if amount_max is not None:
        parts.append(f"{amount_max:,.0f}")
    amount_str = " -- ".join(parts)
    if currency:
        amount_str = f"{currency} {amount_str}"

    # CSS class -- gold accent for high confidence
    css_class = "amount-display"
    if confidence == "high":
        css_class += " high-confidence"

    # Build USD conversion string
    usd_parts = []
    if usd_min is not None:
        usd_parts.append(f"USD {usd_min:,.0f}")
    if usd_max is not None:
        usd_parts.append(f"USD {usd_max:,.0f}")
    usd_str = " -- ".join(usd_parts) if usd_parts else None

    children = [ui.span(amount_str)]
    if usd_str:
        children.append(ui.span(f" ({usd_str})", class_="amount-usd"))
    if confidence == "high":
        children.append(
            ui.span(" [high confidence]", class_="confidence-indicator")
        )

    return ui.span(*children, class_=css_class)


def _gradient_value_box(title: str, value: str, css_class: str) -> ui.Tag:
    """Render a value box with a gradient background.

    Args:
        title: Short descriptive label.
        value: The numeric value to display.
        css_class: CSS class for the gradient (e.g. "value-box-teal").

    Returns:
        A Shiny UI Tag.
    """
    return ui.div(
        ui.h4(title),
        ui.div(value, class_="value-box-number"),
        class_=f"value-box {css_class}",
    )
