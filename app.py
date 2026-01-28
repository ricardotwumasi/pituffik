"""Pituffik -- Health Research Grant Discovery Dashboard.

A Shiny for Python application displaying grant opportunities
collected, verified, and enriched by the Pituffik pipeline.

Deployed on Posit Connect Cloud.
"""

from __future__ import annotations

from pathlib import Path

from shiny import App, Inputs, Outputs, Session, reactive, render, ui

from dashboard.data_access import (
    get_all_opportunities,
    get_connection,
    get_diagnostics,
    get_filtered_opportunities,
    get_opportunity_detail,
)
from dashboard.filters import GRANT_TYPE_LABELS, get_filter_choices
from dashboard.ui_components import (
    diagnostics_panel,
    new_since_last_visit_js,
    opportunity_detail_panel,
)

_CSS_PATH = Path(__file__).parent / "dashboard" / "styles.css"


# -- UI --

app_ui = ui.page_navbar(
    # Custom CSS and localStorage JS
    ui.head_content(
        ui.tags.style(_CSS_PATH.read_text(encoding="utf-8")),
        ui.tags.script(new_since_last_visit_js()),
    ),

    # Tab 1: Opportunities
    ui.nav_panel(
        "Opportunities",
        ui.layout_sidebar(
            ui.sidebar(
                ui.h5("Filters"),
                ui.input_text(
                    "search_text", "Search",
                    placeholder="Free-text search...",
                ),
                ui.input_select("funder", "Funder", choices=["All funders"]),
                ui.input_select(
                    "grant_type", "Grant Type", choices=["All grant types"],
                ),
                ui.input_select("region", "Region", choices=["All regions"]),
                ui.input_select(
                    "career_stage", "Career Stage",
                    choices=["All career stages"],
                ),
                ui.input_select("status", "Status", choices={
                    "open": "Open",
                    "closed": "Closed",
                    "unverified": "Unverified",
                }),
                ui.input_slider(
                    "min_relevance", "Min. relevance",
                    min=0, max=100, value=0, step=5, post="%",
                ),
                ui.input_numeric(
                    "min_amount_gbp", "Min. amount (GBP)",
                    value=None, min=0, step=10000,
                ),
                ui.hr(),
                ui.input_action_button(
                    "refresh", "Refresh data",
                    class_="btn-pituffik-primary w-100",
                ),
                width=280,
            ),
            ui.layout_columns(
                ui.card(
                    ui.card_header("Grant Opportunities"),
                    ui.output_data_frame("opportunities_table"),
                ),
                ui.card(
                    ui.card_header("Details"),
                    ui.output_ui("detail_panel"),
                ),
                col_widths=[7, 5],
            ),
        ),
    ),

    # Tab 2: Diagnostics
    ui.nav_panel(
        "Diagnostics",
        ui.card(
            ui.card_header("Pipeline Diagnostics"),
            ui.output_ui("diagnostics_view"),
        ),
    ),

    # Tab 3: About
    ui.nav_panel(
        "About",
        ui.card(
            ui.card_header("About Pituffik"),
            ui.card_body(
                ui.tags.img(
                    src="pituffik_hero.png",
                    alt="Pituffik -- a radar dish in an arctic landscape scanning for grant opportunities",
                    style=(
                        "width:100%;max-width:700px;display:block;"
                        "margin:0 auto 24px auto;border-radius:8px;"
                    ),
                ),
                ui.h3("Pituffik -- Health Research Grant Discovery"),
                ui.p(
                    "Pituffik is an automated grant discovery system for health "
                    "research funding opportunities. It crawls international "
                    "funder websites and grant databases every six hours, "
                    "deduplicates and verifies listings, enriches them with "
                    "AI-powered relevance scoring and structured field extraction, "
                    "converts amounts to GBP via ECB exchange rates, and delivers "
                    "weekly email digests of the most relevant opportunities."
                ),
                ui.h4("Thematic scope"),
                ui.tags.ul(
                    ui.tags.li(
                        "Health research broadly, with priority for psychosis and "
                        "psychosis-adjacent clinical research"
                    ),
                    ui.tags.li(
                        "Mental health, psychiatry, and severe mental illness"
                    ),
                    ui.tags.li(
                        "Organisational, occupational, work, and I-O psychology"
                    ),
                    ui.tags.li("Health psychology and behaviour change"),
                    ui.tags.li(
                        "Epidemiology, causal inference, and registry-based research"
                    ),
                    ui.tags.li("Digital health and AI in mental health"),
                ),
                ui.h4("Sources"),
                ui.tags.ul(
                    ui.tags.li("UKRI Gateway to Research (UK)"),
                    ui.tags.li("NIHR Funding and Awards (UK)"),
                    ui.tags.li("Wellcome Trust (UK/global)"),
                    ui.tags.li("NIH Reporter / Grants.gov (US)"),
                    ui.tags.li("ERC / Horizon Europe (EU)"),
                    ui.tags.li("DFF / Novo Nordisk / Lundbeck (Denmark)"),
                    ui.tags.li("NordForsk (Nordic)"),
                    ui.tags.li("Vetenskapsradet (Sweden)"),
                    ui.tags.li("Norges Forskningsrad (Norway)"),
                    ui.tags.li("NHMRC / ARC (Australia)"),
                ),
                ui.h4("Technology"),
                ui.tags.ul(
                    ui.tags.li(
                        "Pipeline: Python, httpx, feedparser, BeautifulSoup, "
                        "Gemini 1.5 Flash"
                    ),
                    ui.tags.li(
                        "Dashboard: Shiny for Python on Posit Connect Cloud"
                    ),
                    ui.tags.li("Storage: SQLite (committed to git)"),
                    ui.tags.li("CI/CD: GitHub Actions (crawl every 6 hours)"),
                    ui.tags.li("Currency conversion: ECB exchange rates"),
                    ui.tags.li("Notifications: Resend weekly email digests"),
                ),
                ui.h4("AI Assistance Statement"),
                ui.p(
                    "This dashboard was vibe coded with the assistance of "
                    "Claude Code powered by Opus 4.5."
                ),
                ui.hr(),
                ui.p(
                    ui.a(
                        "GitHub repository",
                        href="https://github.com/ricardotwumasi/pituffik",
                        target="_blank",
                    ),
                    class_="text-muted",
                ),
            ),
        ),
    ),

    title="Pituffik",
    id="main_nav",
)


# -- Server --

def server(input: Inputs, output: Outputs, session: Session) -> None:
    """Shiny server function."""

    # Reactive database connection
    @reactive.calc
    def db_conn():
        # Re-read on refresh button click
        input.refresh()
        return get_connection()

    # Populate filter dropdowns on load
    @reactive.effect
    def _populate_filters():
        conn = db_conn()
        choices = get_filter_choices(conn)

        funders = {code: label for code, label in choices["funders"]}
        ui.update_select("funder", choices=funders)

        grant_types = {code: label for code, label in choices["grant_types"]}
        ui.update_select("grant_type", choices=grant_types)

        regions = {code: label for code, label in choices["regions"]}
        ui.update_select("region", choices=regions)

        career_stages = {code: label for code, label in choices["career_stages"]}
        ui.update_select("career_stage", choices=career_stages)

    # Filtered opportunities
    @reactive.calc
    def filtered_opportunities():
        conn = db_conn()
        min_rel = input.min_relevance() / 100.0 if input.min_relevance() > 0 else None
        min_amt = input.min_amount_gbp() if input.min_amount_gbp() else None
        return get_filtered_opportunities(
            conn,
            funder=input.funder() if input.funder() else None,
            grant_type=input.grant_type() if input.grant_type() else None,
            region=input.region() if input.region() else None,
            career_stage=input.career_stage() if input.career_stage() else None,
            status=input.status(),
            search_text=input.search_text() if input.search_text() else None,
            min_relevance=min_rel,
            min_amount_gbp=min_amt,
        )

    # Opportunities table
    @render.data_frame
    def opportunities_table():
        opportunities = filtered_opportunities()

        # Build display data
        rows = []
        for opp in opportunities:
            score = (
                f"{opp['relevance_score'] * 100:.0f}%"
                if opp.get("relevance_score") is not None
                else ""
            )
            gt_label = GRANT_TYPE_LABELS.get(
                opp.get("grant_type_bucket", ""),
                opp.get("grant_type_bucket", ""),
            )
            # Build a concise amount string for the table
            amount_str = ""
            if opp.get("amount_max") is not None:
                currency = opp.get("amount_currency", "")
                amount_str = f"{currency} {opp['amount_max']:,.0f}".strip()
            elif opp.get("amount_gbp_max") is not None:
                amount_str = f"GBP {opp['amount_gbp_max']:,.0f}"

            rows.append({
                "opportunity_id": opp["opportunity_id"],
                "Title": opp.get("title") or "(No title)",
                "Funder": opp.get("funder_name") or "",
                "Type": gt_label,
                "Region": opp.get("country_or_region") or "",
                "Relevance": score,
                "Deadline": opp.get("deadline_date") or "",
                "Amount": amount_str,
            })

        import pandas as pd

        df = pd.DataFrame(rows)
        if "opportunity_id" in df.columns:
            display_df = df.drop(columns=["opportunity_id"])
        else:
            display_df = df

        return render.DataGrid(
            display_df,
            selection_mode="row",
            height="600px",
        )

    # Detail panel
    @render.ui
    def detail_panel():
        selected = opportunities_table.cell_selection()
        if not selected or "rows" not in selected or not selected["rows"]:
            return ui.p(
                "Select an opportunity to view details.",
                class_="text-muted p-3",
            )

        row_idx = selected["rows"][0]
        opportunities = filtered_opportunities()
        if row_idx >= len(opportunities):
            return ui.p("No opportunity selected.", class_="text-muted p-3")

        opportunity = opportunities[row_idx]
        return opportunity_detail_panel(opportunity)

    # Diagnostics
    @render.ui
    def diagnostics_view():
        conn = db_conn()
        diag = get_diagnostics(conn)
        return diagnostics_panel(diag)


# -- App --

app = App(app_ui, server)
