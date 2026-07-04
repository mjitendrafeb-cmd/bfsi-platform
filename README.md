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
