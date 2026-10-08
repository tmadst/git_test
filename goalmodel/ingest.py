"""Pull Pinnacle data into the local DB, spending as few API tokens as possible.

- fixtures: one call per league for the whole season window.
- closing odds + final score: once per finished match, never re-fetched.
- snapshots: latest pre-match odds for matches kicking off in the next N days
  (appended, so you build your own line-movement history by running often).
"""
from datetime import datetime, timedelta, timezone

from .config import SEASON_START

ODDS_COLS = ["odds1", "odds0", "odds2", "todds1", "todds0", "todds2", "max_win"]


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _line(v):
    # Moneyline has no line; store 0 so it can sit in the primary key.
    return 0.0 if v is None else float(v)


def update_fixtures(con, api, league_id, days_ahead=21):
    rows = api.fixtures(league_id, SEASON_START, _iso(_utcnow() + timedelta(days=days_ahead)))
    now = _utcnow()
    for r in rows:
        if r.get("resulting_unit") not in (None, "Regular") or r.get("parent_id"):
            continue  # corners / bookings / live child events
        con.execute(
            "INSERT OR REPLACE INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?)",
            [r["event_id"], r["league_id"], r["league_name"], r["starts"],
             r["runner_home"], r["runner_away"], now],
        )
    return len(rows)


def update_closing(con, api, league_id):
    """Closing odds + score for kicked-off matches we don't have yet."""
    todo = con.execute(
        """
        SELECT f.event_id FROM fixtures f
        WHERE f.league_id = ? AND f.starts < now() - INTERVAL 2 HOUR
          AND NOT EXISTS (SELECT 1 FROM odds_closing c WHERE c.event_id = f.event_id)
          AND NOT EXISTS (SELECT 1 FROM results r WHERE r.event_id = f.event_id)
        ORDER BY f.starts
        """,
        [league_id],
    ).fetchall()
    fetched = 0
    for (event_id,) in todo:
        rows = api.closing(event_id)
        for r in rows:
            con.execute(
                "INSERT OR REPLACE INTO odds_closing VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [event_id, r["period"], r["market"], _line(r["line"]),
                 *[r.get(c) for c in ODDS_COLS], r["timestamp"]],
            )
        # The closing rows carry the score of their own period; full time = period 0.
        scored = [r for r in rows if r["period"] == 0 and r.get("score_home") is not None]
        if scored:
            r = scored[0]
            con.execute(
                "INSERT OR REPLACE INTO results VALUES (?, 0, ?, ?, ?)",
                [event_id, r.get("result_status"), r["score_home"], r["score_away"]],
            )
        else:
            # Duplicate / never-priced event id: mark as seen so we don't pay again.
            con.execute("INSERT OR REPLACE INTO results VALUES (?, 0, NULL, NULL, NULL)", [event_id])
        fetched += 1
    return fetched


def update_snapshots(con, api, league_id, days_ahead=7):
    todo = con.execute(
        """
        SELECT event_id FROM fixtures
        WHERE league_id = ? AND starts > now() AND starts < now() + to_days(?)
        ORDER BY starts
        """,
        [league_id, days_ahead],
    ).fetchall()
    now = _utcnow()
    n = 0
    for (event_id,) in todo:
        rows = api.odds(event_id, period=0)
        for r in rows:
            con.execute(
                "INSERT INTO odds_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [now, event_id, r["period"], r["market"], _line(r["line"]),
                 *[r.get(c) for c in ODDS_COLS], r["timestamp"]],
            )
        n += bool(rows)
    return n
