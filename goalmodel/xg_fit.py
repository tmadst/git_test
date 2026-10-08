"""Market-implied match xG.

Find the home/away goal expectancies (independent Poisson) whose fair prices
best match Pinnacle's fair (vig-free, `todds`) prices across every line
offered: 1X2, all totals (incl. Asian quarter lines), Asian handicaps and team
totals. Using the whole ladder is far more stable than a single O/U 2.5 price.
"""
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 12
_G = np.arange(MAX_GOALS + 1)
_H, _A = np.meshgrid(_G, _G, indexing="ij")


def score_matrix(lh, la):
    return np.outer(poisson.pmf(_G, lh), poisson.pmf(_G, la))


def _components(line):
    # Quarter lines (2.25, -0.75, ...) are half stake on each neighbouring line.
    if round(line * 4) % 2:
        return [line - 0.25, line + 0.25]
    return [line]


def _asian_odds(m, stat, line, side):
    """Fair decimal odds of an Asian bet. side=+1 wins when stat + c > 0
    (handicap) / stat > c (over); side=-1 the opposite."""
    win = lose = 0.0
    for c in _components(line):
        x = stat - c if side in ("over", "under") else stat + c
        if side in ("over", "home"):
            win += m[x > 0].sum()
            lose += m[x < 0].sum()
        else:
            win += m[x < 0].sum()
            lose += m[x > 0].sum()
    return 1 + lose / win if win > 0 else np.inf


def model_odds(m, market, line):
    """(model odds side 1, side 0, side 2) for one Pinnacle market row."""
    if market == "moneyline":
        ph = np.tril(m, -1).sum()
        pa = np.triu(m, 1).sum()
        pd = np.trace(m)
        return 1 / ph, 1 / pd, 1 / pa
    if market == "totals":
        stat = _H + _A
    elif market == "home_totals":
        stat = _H
    elif market == "away_totals":
        stat = _A
    elif market == "spread":
        stat = _H - _A
        return _asian_odds(m, stat, line, "home"), None, _asian_odds(m, stat, line, "away")
    else:
        return None, None, None
    return _asian_odds(m, stat, line, "over"), None, _asian_odds(m, stat, line, "under")


def fit_match(rows):
    """rows: iterable of dicts with market, line, todds1, todds0, todds2.
    Returns (xg_home, xg_away, rmse_log_odds, n_prices) or None."""
    prices = []
    for r in rows:
        for key, idx in (("todds1", 0), ("todds0", 1), ("todds2", 2)):
            v = r.get(key)
            if v is not None and v > 1 and np.isfinite(v):
                prices.append((r["market"], r["line"], idx, np.log(v)))
    if not any(p[0] in ("totals", "home_totals", "away_totals") for p in prices):
        return None

    def loss(theta):
        m = score_matrix(*np.exp(theta))
        cache = {}
        err = 0.0
        for market, line, idx, target in prices:
            k = (market, line)
            if k not in cache:
                cache[k] = model_odds(m, market, line)
            o = cache[k][idx]
            err += (np.log(o) - target) ** 2 if o and np.isfinite(o) else 25.0
        return err / len(prices)

    res = minimize(loss, x0=np.log([1.4, 1.1]), method="Nelder-Mead",
                   options={"xatol": 1e-5, "fatol": 1e-9})
    lh, la = np.exp(res.x)
    return float(lh), float(la), float(np.sqrt(res.fun)), len(prices)


def _rows(con, sql, params):
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def fit_closing(con, refit=False):
    ids = con.execute(
        "SELECT DISTINCT event_id FROM odds_closing WHERE period = 0"
        + ("" if refit else
           " AND event_id NOT IN (SELECT event_id FROM match_xg WHERE source = 'closing')")
    ).fetchall()
    n = 0
    for (eid,) in ids:
        rows = _rows(con, "SELECT * FROM odds_closing WHERE event_id = ? AND period = 0", [eid])
        _store(con, eid, "closing", rows)
        n += 1
    return n


def fit_snapshots(con):
    """Fit the latest snapshot of every upcoming match."""
    ids = con.execute(
        """SELECT event_id, max(fetched_at) FROM odds_snapshots
           WHERE event_id IN (SELECT event_id FROM fixtures WHERE starts > now())
           GROUP BY event_id"""
    ).fetchall()
    for eid, fetched_at in ids:
        rows = _rows(
            con,
            "SELECT * FROM odds_snapshots WHERE event_id = ? AND fetched_at = ? AND period = 0",
            [eid, fetched_at],
        )
        _store(con, eid, "snapshot", rows)
    return len(ids)


def _store(con, eid, source, rows):
    fit = fit_match(rows)
    if fit is None:
        return
    lh, la, rmse, n = fit
    odds_ts = max((r["ts"] for r in rows if r.get("ts")), default=None)
    con.execute(
        "INSERT OR REPLACE INTO match_xg VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [eid, source, datetime.now(timezone.utc).replace(tzinfo=None), odds_ts, lh, la, rmse, n],
    )
