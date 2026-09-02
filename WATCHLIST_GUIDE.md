# How to update the portfolio watchlist

The watchlist is the file [`portfolios.csv`](portfolios.csv) in the repository
root. The news job reads this file from the selected branch every time it runs.

## Edit it on GitHub

1. Open the repository on GitHub.
2. In the repository's main file list, select **`portfolios.csv`**. It is beside
   `config.json` and `README.md`, not inside the `data` directory.
3. Select the pencil icon labelled **Edit this file**.
4. Make one or more of the changes described below.
5. Select **Commit changes...**.
6. Enter a short message, such as `Update Rahul portfolio`.
7. Commit to the branch used by the **Daily portfolio news** workflow, or open a
   pull request and merge it into that branch.

No Python change or deployment step is necessary. The next workflow run uses
the committed CSV contents.

## CSV format

Keep this header as the first line:

```csv
company,analyst_name,analyst_email
```

Each following line assigns one company to one analyst:

```csv
ESAF Small Finance Bank Limited,Rahul,rahul@company.com
```

Use the company's recognizable full name. The system uses the first two words
for feed searches and matching. All three cells are required, and the email
must contain `@`. Invalid lines are skipped with a warning rather than stopping
the entire run.

If a value itself contains a comma, enclose that value in double quotes:

```csv
"Example Finance, India Limited",Rahul,rahul@company.com
```

## Common changes

### Add a company

Add a new line at the end of the file:

```csv
New Finance Limited,Priya,priya@company.com
```

### Remove a company

Delete the entire line for that company. If the company occurs more than once,
delete every assignment that should no longer receive its news.

### Reassign a company

Change both analyst fields on the existing line:

```diff
-Aavas Financiers Limited,Rahul,rahul@company.com
+Aavas Financiers Limited,Priya,priya@company.com
```

### Send the same company to two analysts

Repeat the company on two lines, with a different analyst on each line:

```csv
Aavas Financiers Limited,Rahul,rahul@company.com
Aavas Financiers Limited,Priya,priya@company.com
```

### Change an email address

Replace the old address in every row belonging to that analyst:

```diff
-ESAF Small Finance Bank Limited,Rahul,rahul@company.com
+ESAF Small Finance Bank Limited,Rahul,rahul.sharma@company.com
```

## Verify the change

1. Reopen `portfolios.csv` after committing and confirm the rendered table has
   exactly three columns with no shifted values.
2. Open the repository's **Actions** tab.
3. Select **Daily portfolio news**, then **Run workflow**.
4. Review the run log for `ANALYST_COUNT` lines. Each line reports the analyst,
   destination email, and number of matched items.

The workflow normally prevents a second send on the same IST date. A maintainer
can use the application's `--force` option for controlled testing, but should
avoid doing so with production recipient addresses unless another email is
intended.

## Do not edit these for portfolio changes

- `config.json` controls delivery behavior and sources, not company ownership.
- `data/seen_headlines.json` is the automatic 30-day deduplication history.
- `data/last_sent.json` is the automatic same-day delivery marker.
- Files under `watchlist_news/` contain application code.
