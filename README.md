# Portfolio-Wise Watchlist News

This repository contains an automated daily email digest that fetches news only
for companies in `portfolios.csv`, matches shared-feed stories to those
companies, and sends each analyst one company-grouped report. The watchlist is
the single source of truth: edit a row to add, remove, or reassign coverage;
Python changes are not required.

## Where to update the portfolio watchlist

Update **[`portfolios.csv`](portfolios.csv) in the repository root**. On
GitHub, open that file, click the pencil icon (**Edit this file**), make the
change, and commit it. The next pipeline run reads the file again automatically.
For screenshots-independent, step-by-step instructions and examples, see the
**[Portfolio Watchlist Guide](WATCHLIST_GUIDE.md)**.

| Change needed | Edit in `portfolios.csv` |
|---|---|
| Add a company | Add a row with its company, analyst name, and analyst email. |
| Remove a company | Delete its row. |
| Reassign a company | Change `analyst_name` and `analyst_email` on its row. |
| Send one company's news to two analysts | Add two rows for the company, one for each analyst. |
| Change an analyst's email | Update `analyst_email` on every applicable row. |

Keep the header exactly as `company,analyst_name,analyst_email`. Do not update
`data/seen_headlines.json`, `data/last_sent.json`, or Python source files to
change portfolio coverage.

## Other configuration

1. Edit [`config.json`](config.json) for source toggles, delivery time, empty
   reports, all-mail CC recipients, Claude mode/model, source URLs, and the
   GitHub edit link. Replace `OWNER/REPOSITORY` in `repository_edit_url`.
2. Add GitHub Actions secrets `GMAIL_USER` and `GMAIL_APP_PASSWORD` (a Gmail App
   Password). Add `ANTHROPIC_API_KEY` only when `claude_mode` is enabled.
3. Run **Daily portfolio news** with `workflow_dispatch` to verify delivery.

The scheduled workflow has eight staggered ticks, an IST delivery-window gate,
serialized concurrency, and a same-day marker. A tick refreshes state from the
remote after waiting, so a delayed checkout cannot send twice. State is only
written after all required SMTP sends succeed; a later tick can retry failures.

## Run and test locally

```bash
pip install -r requirements.txt
python -m watchlist_news.app --dry-run --force
pytest -q
```

Dry-run mode fetches and routes live feeds, but neither sends mail nor changes
the deduplication/last-sent state. Logs include counts for every enabled source
and analyst, plus an explicit warning for every zero-result source.

`data/seen_headlines.json` retains a rolling 30-day history. Both filtering and
saving call the same `dedup_key` implementation. `data/last_sent.json` prevents
repeat delivery for an IST calendar day. Do not edit either file manually.

Plain mode creates the HTML report without an API key. Claude mode streams a
formatted report with takeaways and credit implications; any Claude error,
including insufficient credits, produces a clearly labelled plain report
instead of an empty email.

## Legacy platform

The pre-existing BFSI intelligence pipeline remains available below.

# BFSI Intelligence Platform — Pipeline (Pilot: 3 entities)

Pilot entities: **Spandana Sphoorty** (listed MFI), **Muthoot Finance**
(listed gold-loan NBFC), **IKF Home Finance** (unlisted HFC).
Scaling later = add rows to `data/entity_master.csv`. No code changes.

## Live-verified status (04-Jul-2026, real data fetched)
All 9 sources working via plain `requests` (no Playwright needed in
production for any of them — where recon expected bot protection or a
JS-only SPA, the actual data turned out reachable a different way each
time; see each scraper's module docstring for what was actually found).
| Source | Status | Notes |
|---|---|---|
| CareEdge | ✅ WORKING | JSON endpoint `/rrcompany` |
| BSE filings | ✅ WORKING | `api.bseindia.com` announcements API |
| Google News | ✅ WORKING | RSS per alias |
| CRISIL | ✅ WORKING | Internal JSON API found via probe; single-page limitation (see docstring) |
| ICRA | ✅ WORKING | No bot protection found live (contra recon) — server-rendered HTML |
| India Ratings | ✅ WORKING | Homepage JSON widgets; full rationale text is login-gated, headline only |
| Acuité | ✅ WORKING | No bot protection found live on `connect.acuite.in` (contra recon) — real pagination |
| Infomerics | ✅ WORKING | Homepage's Next.js RSC payload (`RSC: 1` header), not a page URL |
| Brickwork | ✅ WORKING | SEBI restrictions lifted Mar-2024, actively publishing; two mixed link styles on one listing page |

## Run
```bash
pip install -r requirements.txt
python run.py all --days 3           # everything
python run.py careedge --days 7      # one source
python run.py bse --days 21 --no-pdfs
```
Data → `db/tracker.sqlite` (`raw_items`, `processed=0` = delta-engine queue).
PDFs → `db/pdfs/<agency>/`. Health log → `scraper_health`.

## Implementing the remaining CRAs (Claude Code sessions)
Each stub's docstring carries site reconnaissance from live probes.
Recipe: `python tools/probe.py <listing_url>` captures the site's internal
JSON API via Playwright; replicate that call in `fetch_new_items()`.
Playwright needed: `pip install playwright && playwright install chromium`.

## Architecture reminders
- New scrapers implement ONLY `fetch_new_items()`; base class does
  dedupe, entity match, PDF download, health logging.
- `Storage` (SQLite) swaps to Supabase via same 3-method interface.
- GitHub Actions workflow runs 07:00 & 14:00 IST once pushed.

## Delta Engine (pipeline/)
| Module | Role |
|---|---|
| `pipeline/schemas.py` | Extraction schemas per doc type + routing |
| `pipeline/extract.py` | PDF text (pdfplumber) → Claude Sonnet → snapshot JSON + confidence |
| `pipeline/delta.py` | Deterministic JSON diff → Claude grades materiality + writes delta note |
| `pipeline/process.py` | Queue drainer: `python -m pipeline.process` (`--dry-run` to preview) |

Tested: real Spandana rationale text-extracted cleanly (29.5k chars);
diff engine verified on a simulated downgrade (8 exact changes detected);
processor dry-run routes the live queue correctly.
**Needs `ANTHROPIC_API_KEY` env var for the two LLM steps** — set it as a
GitHub Actions secret and locally. Everything else runs without it.
