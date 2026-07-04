# inbox/

Drop any rating rationale, press release, or other credit document here
that the scrapers can't reach on their own — a paywalled agency (e.g.
India Ratings' full rationale, which needs a login we don't have),
Acuité/Infomerics/Brickwork before their scrapers are built, a PDF
someone emailed you, or a report grabbed by hand from a site that
isn't supported yet.

## Usage

1. Find the entity's id in [`data/entity_master.csv`](../data/entity_master.csv)
   (currently: `1` = Spandana Sphoorty, `2` = Muthoot Finance,
   `3` = IKF Home Finance).
2. Drop the file(s) here — PDF or HTML, both are detected automatically.
3. Run:

   ```
   python -m pipeline.ingest inbox/ <entity_id> <agency>

   # a single file also works, instead of the whole folder:
   python -m pipeline.ingest inbox/some_report.pdf 2 careedge
   ```

`<agency>` should be the real source name (`careedge`, `crisil`,
`icra`, `indiaratings`, `bse`) if the document genuinely came from one
of them — that way it gets diffed against that agency's other
documents for the same entity, same as a scraped one would be.
Otherwise, any short label works (e.g. `manual`).

## What this does

Registers each document and immediately runs it through the normal
extraction + delta pipeline — the same code path scraped documents go
through, not a separate one. Needs `ANTHROPIC_API_KEY` set (same as
`python -m pipeline.process`).

Files already ingested (same content + same agency) are skipped
automatically on repeat runs, so it's safe to leave files here and
re-run the command later — nothing gets processed twice.
