# BFSI Intelligence Platform — Pipeline (Pilot: 3 entities)

Pilot entities: **Spandana Sphoorty** (listed MFI), **Muthoot Finance**
(listed gold-loan NBFC), **IKF Home Finance** (unlisted HFC).
Scaling later = add rows to `data/entity_master.csv`. No code changes.

## View the website (simple instructions)

### Public page on GitHub — best for mobile

1. Merge the latest pull request into **`master`**.
2. Open the repository and go to **Settings → Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select **`master`**, select **`/docs`**, and press **Save**.
5. Wait 2–5 minutes and refresh the Pages screen.
6. Open the link next to **Your site is live at**.

The address will look like:
`https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/`.

If `/docs` is not listed, the latest pull request has not yet been merged into
`master`. If **Settings** is hidden on mobile, enable **Desktop site** in the
browser menu.

### On the computer containing this project

Run:

```bash
python run_webapp.py
```

Then open <http://127.0.0.1:8000/dashboard> on that same computer. This local
address will not open directly on a different phone or computer.

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

## Entity master and watchlist

The supplied BFSI watchlist is stored one name per line in
`data/entity_watchlist.txt`. Merge it into the entity master with:

```bash
python scripts/import_entity_watchlist.py
```

The importer is idempotent, keeps the original submitted names as aliases,
merges source labels such as `(BLR)`/`(CQR)`, and preserves the three pilot
entity IDs. Newly imported names default to priority tier 2 and blank exchange/
corporate identifiers so they can be enriched later.


## Web app access

Local-only access:
```bash
python run_webapp.py
# open http://127.0.0.1:8000/dashboard
```

Same Wi-Fi / LAN access from another PC or mobile:
```bash
python run_webapp.py --host 0.0.0.0 --no-browser
# find this computer's LAN IP, then open:
# http://<LAN-IP>:8000/dashboard
```

Notes:
- `127.0.0.1` only works on the same computer.
- `0.0.0.0` listens on all network interfaces, so use it only on a trusted network.
- If another device cannot connect, allow Python/port 8000 through the OS firewall.


## Static demo export for GitHub Pages

For demo/feedback sharing without running Python on the viewer's machine:
```bash
python scripts/export_static_site.py
```

### Public website URL

The repository includes `.github/workflows/pages.yml`, which publishes the
read-only `docs/` website whenever changes reach the repository's default
`master` branch.

#### If “Publish website” is not visible under Actions

GitHub only shows the manual **Run workflow** button after the workflow file is
present on the repository's **default branch**. This GitHub repository uses
`master`, not `main`. If **Publish website** is absent, the pull request that
adds `.github/workflows/pages.yml` has not yet been merged into `master` (or
GitHub Actions is disabled). Merge the pull request first, then refresh Actions.

Then follow these exact steps:

1. Open the repository's **Actions** tab. If GitHub asks to enable Actions,
   select **I understand my workflows, go ahead and enable them**.
2. Refresh the page and select **Publish website** in the left-hand workflow
   list.
3. Select the **Run workflow** drop-down on the right, leave `master` selected,
   and press the green **Run workflow** button.
4. If the run reports that Pages is not configured, open **Settings → Pages**
   and set **Build and deployment → Source** to **GitHub Actions**, then run the
   workflow again.
5. Open the completed deployment and select its URL. The same URL also appears
   under **Settings → Pages** and normally has this format:
   `https://<github-user-or-organisation>.github.io/<repository>/`.

On a narrow mobile screen, the workflow list may be behind GitHub's menu. If
the **Run workflow** drop-down is still missing, use the browser's **Desktop
site** option. Also confirm that you are signed in with repository write access.

As a no-workflow alternative, select **Settings → Pages → Deploy from a
branch**, choose `master` and `/docs`, and save. The `/docs` option appears only
after the website changes have been merged into `master`. GitHub will then
publish the same read-only website directly from that folder.

The public export is intentionally read-only. Analyst approvals, document
ingestion, and other actions that modify SQLite remain available only in the
FastAPI application.

This writes a read-only site to `docs/`:
```text
docs/index.html
docs/entities.html
docs/entities/<entity_id>.html
docs/review.html
docs/static/style.css
```

You can publish `docs/` with GitHub Pages. This static version is read-only: it cannot approve review items, run scrapers, process AI extraction, ingest PDFs, or update SQLite. Use `python run_webapp.py` for the full interactive app.

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
