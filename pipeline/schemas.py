"""Extraction schemas — one per doc_type. The schema IS the product:
deterministic diffing only works because every document of a type is
forced into the same structure.

Field naming rules:
  - percentages as numbers (2.7 not "2.7%"), amounts in Rs crore
  - null when the document doesn't state it — NEVER guessed
  - lists sorted logic-free; diff handles set comparison
"""

RATING_RATIONALE = {
    "doc_type": "rating_rationale",
    "fields": {
        "agency": "string — which CRA issued this",
        "entity_name": "string — company as stated in the PR",
        "rating_date": "YYYY-MM-DD",
        "instruments": [{
            "instrument": "string, e.g. Long-term bank facilities / NCD / CP",
            "amount_cr": "number|null",
            "rating": "string, e.g. CARE A",
            "outlook": "Stable|Positive|Negative|null",
            "watch": "string|null — watch with developing/negative implications",
            "action": "Assigned|Reaffirmed|Upgraded|Downgraded|Withdrawn|Revised",
        }],
        "key_rating_drivers_strengths": ["string — each driver as one bullet"],
        "key_rating_drivers_weaknesses": ["string"],
        "rating_sensitivities_positive": ["string"],
        "rating_sensitivities_negative": ["string"],
        "liquidity_assessment": "Strong|Adequate|Stretched|Poor|null",
        "liquidity_commentary": "string|null — 1-2 lines",
        "key_metrics": {
            "aum_cr": "number|null", "networth_cr": "number|null",
            "pat_cr": "number|null", "total_income_cr": "number|null",
            "gnpa_pct": "number|null", "nnpa_pct": "number|null",
            "car_pct": "number|null", "gearing_x": "number|null",
            "roa_pct": "number|null", "metrics_asof": "string|null e.g. FY26/Q4FY26",
        },
        "analysts": ["string — analyst names if stated"],
    },
}

EXCHANGE_FILING = {
    "doc_type": "exchange_filing",
    "fields": {
        "entity_name": "string",
        "filing_date": "YYYY-MM-DD",
        "category": ("results|credit_rating|fund_raise|board_meeting|"
                     "management_change|scheme|pledge|other"),
        "headline": "string — one line, what happened",
        "detail": "string — 2-3 lines of substance, numbers included",
        "amounts_cr": "number|null — any principal amount involved",
        "credit_relevance": "high|medium|low",
    },
}

QUARTERLY_RESULTS = {
    "doc_type": "quarterly_results",
    "fields": {
        "entity_name": "string",
        "financial_statements": [{
            "basis": ("standalone|consolidated — which statement this set of "
                      "figures is from. If the filing presents BOTH standalone "
                      "and consolidated statements (common when there are "
                      "subsidiaries), output ONE ENTRY PER BASIS — never merge "
                      "them into one set or silently pick just one."),
            "period": ("string, ONE reporting period only — e.g. 'Q1FY27' or "
                       "'FY26', never 'Q4FY26 and FY26' or any other combined "
                       "label. If the filing shows figures for multiple periods "
                       "(a quarter, the full year, a prior-year comparative), "
                       "each period is its OWN separate entry in this list — "
                       "never blend two periods' figures into one entry."),
            "aum_cr": "number|null", "disbursements_cr": "number|null",
            "total_income_cr": "number|null", "nii_cr": "number|null",
            "ppop_cr": "number|null", "provisions_cr": "number|null",
            "pat_cr": "number|null", "gnpa_pct": "number|null",
            "nnpa_pct": "number|null", "car_pct": "number|null",
            "networth_cr": "number|null", "borrowings_cr": "number|null",
            "cost_of_funds_pct": "number|null", "collection_efficiency_pct": "number|null",
        }],
        "management_commentary_points": ["string — only if present"],
        "one_offs": ["string — exceptional items, if any"],
    },
}

SF_RATIONALE = {
    "doc_type": "sf_rationale",
    "fields": {
        "agency": "string — which CRA issued this",
        "originator": "string — entity that originated/sold the securitised pool",
        "transaction_name": "string — deal/trust/pool name, e.g. 'Olive 05 2026'",
        "rating_date": "YYYY-MM-DD",
        "pool_type": ("microfinance|vehicle_loans|mortgage_loans|"
                      "personal_loans|gold_loans|mixed|other"),
        "instrument_tranches": [{
            "tranche": "string, e.g. PTC Series A1(a) / Series A2",
            "amount_cr": "number|null",
            "rating": ("string — copy verbatim, including any prefix "
                       "(e.g. 'Provisional', 'Interim') and suffix (e.g. "
                       "'(SO)', '(CE)'). Never drop or simplify these — "
                       "e.g. 'Provisional [ICRA]AA+(SO)', not 'AA+'."),
            "outlook": "Stable|Positive|Negative|null",
            "credit_enhancement_pct": "number|null — CE cover for this tranche, as % of pool principal",
            "action": "Assigned|Reaffirmed|Upgraded|Downgraded|Withdrawn|Revised",
        }],
        "pool_characteristics": {
            "pool_amount_cr": "number|null",
            "number_of_contracts": "number|null",
            "weighted_avg_seasoning_months": "number|null",
            "weighted_avg_maturity_months": "number|null",
            "average_ticket_size_lakh": "number|null",
            "top_state_concentration_pct": "number|null",
            "pool_asof": "string|null — pool cut-off date/period",
        },
        "pool_characteristics_notes": [
            "string — other notable pool features not captured above"],
        "credit_enhancement_structure": (
            "string|null — 2-3 lines describing the CE mechanism (cash "
            "collateral, overcollateralisation, guarantee, excess interest "
            "spread, subordination, etc.) and its coverage"),
        "key_rating_drivers_strengths": ["string"],
        "key_rating_drivers_weaknesses": ["string"],
        "rating_sensitivities_positive": ["string"],
        "rating_sensitivities_negative": ["string"],
        "analysts": ["string — analyst names if stated"],
    },
}

CREDIT_UPDATE = {
    "doc_type": "credit_update",
    "fields": {
        "entity_name": "string",
        "date": "YYYY-MM-DD",
        "subject": ("string — one line, what this note is actually about "
                    "(e.g. 'Delayed debenture payment due to bank detail "
                    "mismatch'). This is an informational note, not a "
                    "rating action."),
        "summary": "string — 2-4 lines, the substance of the update",
        "referenced_current_rating": (
            "string|null — the rating cited as ALREADY IN EFFECT, exactly "
            "as stated (e.g. 'CARE A; Stable'), ONLY if the document "
            "mentions one. This field exists purely for context — "
            "mentioning an existing rating is NEVER itself a rating "
            "action, so never infer or record an action from it."),
    },
}

NEWS = {
    "doc_type": "news",
    "fields": {
        "entity_name": "string",
        "event_type": ("fund_raise|rating_action|management_change|regulatory|"
                       "results|expansion|litigation|fraud|partnership|other"),
        "headline": "string", "summary": "string — 2 lines max",
        "sentiment": "positive|neutral|negative",
        "credit_relevance": "high|medium|low",
    },
}

SCHEMAS = {
    "rating_rationale": RATING_RATIONALE,
    "exchange_filing": EXCHANGE_FILING,
    "quarterly_results": QUARTERLY_RESULTS,
    "news": NEWS,
    "sf_rationale": SF_RATIONALE,
    "credit_update": CREDIT_UPDATE,
}

# Documents whose title/doc_type mentions these are securitisation/PTC/pool
# rationales, not plain corporate rating rationales — different structure
# (tranches + pool characteristics instead of a single entity's financials).
_SF_KEYWORDS = ("securiti", "ptc", "pass-through", "pass through", "pool")

# CareEdge tags every securitisation-originator PR with a CompanyName of
# "<Legal Name>-Securitisation" (confirmed in scrapers/careedge.py) — but
# the deal itself is filed under an arbitrary codename (e.g. "Jaguar IDSP
# 05 2023", "Nirman Trust-I") that never contains an _SF_KEYWORDS hit in
# its own title. Checking title/doc_type alone therefore missed every one
# of these (found via a real backlog of 72 mismatched CareEdge PRs, all
# routed to rating_rationale and flagged because a trust/pool document
# has no single "entity_name" to extract). company_name_raw is agency
# listing metadata, not document content, so this is a separate marker
# from _SF_KEYWORDS, checked against a different string.
_SF_COMPANY_MARKERS = ("-securitisation", "-securitization")

# Beyond BSE/NSE's literal "Result" category name — see route()'s comment
# on why this still can't be fully automatic.
_RESULT_KEYWORDS = ("result", "audited", "annual account", "financial statement")

# CRA informational notes (e.g. CareEdge's "Credit Update") mention an
# existing rating for reference but don't take any rating action — found
# a real case where extraction fabricated a "Reaffirmed" instrument entry
# for one of these, since nothing in the listing metadata distinguishes
# them from a real rationale (CareEdge's own API gives the same generic
# doc_type/title for both). Only the document's own header text reveals
# it, so this is checked against the extracted text, not the listing.
_INFO_NOTE_KEYWORDS = ("credit update", "clarification", "payment status",
                       "payment update")


def is_info_note(text: str) -> bool:
    """True if the document's own header (not just anywhere in the body,
    to avoid a real rationale that happens to discuss a payment
    elsewhere) identifies it as an informational note rather than a
    rating-action document."""
    header = text[:200].lower()
    return any(kw in header for kw in _INFO_NOTE_KEYWORDS)


# raw_items.doc_type / agency / title / company_name_raw  →  schema routing
def route(agency: str, doc_type: str, title: str = "",
          company_name_raw: str = "") -> str:
    if agency in {"careedge", "crisil", "icra", "indiaratings",
                  "acuite", "infomerics", "brickwork"}:
        text = f"{doc_type or ''} {title or ''}".lower()
        if any(kw in text for kw in _SF_KEYWORDS):
            return "sf_rationale"
        if any(m in (company_name_raw or "").lower() for m in _SF_COMPANY_MARKERS):
            return "sf_rationale"
        return "rating_rationale"
    if agency == "news":
        return "news"
    if agency in {"bse", "nse"}:
        # Broadened beyond the literal "Result" category: annual audited
        # results are sometimes filed under "Board Meeting" instead, with
        # a generic "Outcome of Board Meeting" headline that doesn't say
        # "result" anywhere — caught a real case of this during the
        # Muthoot FY26 backfill. Title/category keywords alone can't
        # perfectly disambiguate a results-carrying board meeting from
        # a dividend/M&A one, so this still needs a human (or a wider
        # announcement-clustering heuristic, not implemented here) to
        # confirm before tagging a "Board Meeting" item this way.
        text = f"{doc_type or ''} {title or ''}".lower()
        if any(kw in text for kw in _RESULT_KEYWORDS):
            return "quarterly_results"
        return "exchange_filing"
    return "exchange_filing"
