import json
from datetime import UTC, datetime, timedelta

import watchlist_news.app as app
from watchlist_news.app import NewsItem, dedup_key, load_portfolios, load_seen


def test_dedup_key_uses_source_and_title_before_separator():
    assert dedup_key("Reuters", "Big Event - Reuters") == dedup_key("reuters", "  BIG   EVENT — Updated")
    assert dedup_key("Another", "Big Event") != dedup_key("Reuters", "Big Event")


def test_load_portfolios_skips_bad_rows(tmp_path, caplog):
    path = tmp_path / "portfolios.csv"
    path.write_text("company,analyst_name,analyst_email\nGood Co,Ana,a@example.com\nBad Co,Ana,nope\n")
    assert [row.company for row in load_portfolios(path)] == ["Good Co"]
    assert "Skipping malformed" in caplog.text


def test_seen_rolls_at_30_days(tmp_path):
    now = datetime(2026, 7, 28, tzinfo=UTC)
    path = tmp_path / "seen.json"
    path.write_text(json.dumps({"fresh": (now - timedelta(days=2)).isoformat(), "old": (now - timedelta(days=31)).isoformat()}))
    assert load_seen(path, now) == {"fresh": (now - timedelta(days=2)).isoformat()}


def test_run_routes_by_portfolio_and_second_run_is_blocked(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/seen_headlines.json").write_text("{}")
    (tmp_path / "data/last_sent.json").write_text("{}")
    (tmp_path / "portfolios.csv").write_text(
        "company,analyst_name,analyst_email\nAlpha Finance,Ana,ana@example.com\nBeta Bank,Bob,bob@example.com\n"
    )
    (tmp_path / "config.json").write_text(json.dumps({
        "sources": {}, "send_empty_portfolio_email": True, "cc_all": [],
        "claude_mode": False, "repository_edit_url": "https://example.test/edit",
    }))
    items = [
        NewsItem("Alpha Finance", "Alpha raises funds", "https://a", "News", datetime.now(UTC), "Alpha summary"),
        NewsItem("Beta Bank", "Beta changes CFO", "https://b", "News", datetime.now(UTC), "Beta summary"),
    ]
    monkeypatch.setattr(app.Fetcher, "all", lambda self: items)
    sent = []
    monkeypatch.setattr(app, "send_email", lambda to, cc, subject, body: sent.append((to, subject, body)))

    assert app.run(tmp_path) == 0
    assert [message[0] for message in sent] == ["ana@example.com", "bob@example.com"]
    assert "Alpha raises funds" in sent[0][2] and "Beta changes CFO" not in sent[0][2]
    assert "Beta changes CFO" in sent[1][2] and "Alpha raises funds" not in sent[1][2]
    assert app.run(tmp_path) == 0
    assert len(sent) == 2
