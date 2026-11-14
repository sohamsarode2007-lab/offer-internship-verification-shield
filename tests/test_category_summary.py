"""Category summary (one row per category) and the weekly CSV export."""
import csv
import io

from app.services import institution_dashboard as dash

WEEKS = [f"2026-W{n:02d}" for n in range(35, 47)]


def _counts(per_category: dict[str, list[int]]) -> dict:
    return {(week, cat): n for cat, values in per_category.items() for week, n in zip(WEEKS, values)}


def _row(rows, category):
    return next(r for r in rows if r["category"] == category)


def test_one_row_per_category_with_totals_and_trend():
    rows = dash.category_summary(WEEKS, _counts({
        "registration_fee":  [1, 1, 1, 1, 1, 1, 1, 1, 4, 5, 5, 6],   # 8 earlier, 20 recent: Rising
        "no_red_flags":      [6, 6, 6, 6, 6, 6, 6, 6, 2, 2, 2, 2],   # 48 earlier, 8 recent (56): Falling
        "other":             [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5],   # flat: Steady
        "sender_spoofing":   [0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0],   # total 3: suppressed, no trend
    }))
    assert [r["category"] for r in rows][:3] == ["other", "no_red_flags", "registration_fee"]   # 60, 56, 28
    assert {r["category"] for r in rows} == set(dash.CATEGORIES)
    reg = _row(rows, "registration_fee")
    assert (reg["total"], reg["last_4_weeks"], reg["previous_8_weeks"], reg["trend"]) == (28, 20, 8, "Rising")
    assert _row(rows, "no_red_flags")["trend"] == "Falling"
    assert _row(rows, "other")["trend"] == "Steady"
    spoof = _row(rows, "sender_spoofing")
    assert (spoof["total"], spoof["last_4_weeks"], spoof["previous_8_weeks"], spoof["trend"]) == ("<5", "<5", "<5", None)
    # Suppressed categories sort after the visible ones, alphabetically (no hidden ordering).
    hidden = [r["category"] for r in rows if r["total"] == "<5"]
    assert hidden == sorted(hidden) and rows[-len(hidden):] == [r for r in rows if r["total"] == "<5"]


def test_each_count_is_suppressed_independently():
    rows = dash.category_summary(WEEKS, _counts({"lookalike_domain": [1, 1, 1, 1, 1, 1, 1, 1, 0, 1, 0, 1]}))
    row = _row(rows, "lookalike_domain")
    assert (row["total"], row["last_4_weeks"], row["previous_8_weeks"]) == (10, "<5", 8)


def test_trend_word_rule():
    assert dash.trend_word(10, 20) == "Steady"      # 2.5/week vs 2.5/week
    assert dash.trend_word(13, 20) == "Rising"      # +30%
    assert dash.trend_word(7, 20) == "Falling"      # -30%
    assert dash.trend_word(5, 0) == "Rising"
    assert dash.trend_word(0, 0) == "Steady"


def test_dashboard_api_has_summary_and_weekly_csv(api_client):
    body = api_client.get("/placement-cell/dashboard").json()
    assert len(body["category_summary"]) == len(dash.CATEGORIES)
    assert len(body["by_week_category"]) == 12 * len(dash.CATEGORIES)      # full weekly data kept in the API
    response = api_client.get("/placement-cell/weekly.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="vit-pune-weekly-data.csv"' in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == list(dash.WEEKLY_CSV_COLUMNS)
    assert len(rows) - 1 == 12 * (len(dash.BANDS) + len(dash.CATEGORIES))
    assert {r[1] for r in rows[1:]} == {"band", "category"}
    assert all(r[3] == "<5" or int(r[3]) >= 5 for r in rows[1:])            # '<5' rule applied
