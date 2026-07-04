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
        "entity_name": "string", "period": "string e.g. Q1FY27",
        "metrics": {
            "aum_cr": "number|null", "disbursements_cr": "number|null",
            "total_income_cr": "number|null", "nii_cr": "number|null",
            "ppop_cr": "number|null", "provisions_cr": "number|null",
            "pat_cr": "number|null", "gnpa_pct": "number|null",
            "nnpa_pct": "number|null", "car_pct": "number|null",
            "networth_cr": "number|null", "borrowings_cr": "number|null",
            "cost_of_funds_pct": "number|null", "collection_efficiency_pct": "number|null",
        },
        "management_commentary_points": ["string — only if present"],
        "one_offs": ["string — exceptional items, if any"],
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
}

# raw_items.doc_type / agency  →  schema routing
def route(agency: str, doc_type: str) -> str:
    if agency in {"careedge", "crisil", "icra", "indiaratings",
                  "acuite", "infomerics", "brickwork"}:
        return "rating_rationale"
    if agency == "news":
        return "news"
    if agency in {"bse", "nse"}:
        if "result" in (doc_type or "").lower():
            return "quarterly_results"
        return "exchange_filing"
    return "exchange_filing"
