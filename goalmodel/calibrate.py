"""Calibrate player weights on Pinnacle's "X To Score" props.

Pinnacle's fair anytime price → player xG (inverse Poisson). Divided by the
team's market xG for that match it gives the player's SHARE of team xG. The
share is far more stable from match to match than the player's xG (the xG
moves 1:1 with team xG), so the model prices a player as
    player xG = share × team xG
with the share shrunk towards the league prior: (n·mean + k·prior)/(n + k).
Pinnacle's props are "must start" (void if he doesn't), so shares are
conditional on starting — exactly what the model needs for a starting XI.
"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SHRINK_K = 1.0  # best leave-one-out value on 2025/26–2026/27 EPL + La Liga


def prop_table(con):
    """One row per priced prop with the player's team, team xG and implied share.
    Players seen only once can't be tied to a team (home or away?) and are left out."""
    p = con.sql("""
        WITH y AS (
            SELECT event_id, regexp_replace(special_name, '\\s*To Score.*$', '') AS player,
                   max(CASE WHEN contestant_name = 'Yes' THEN todds END) AS fair_yes,
                   max(CASE WHEN contestant_name = 'Yes' THEN outcome END) AS outcome
            FROM specials_closing
            WHERE category = 'Player Props' AND special_name ILIKE '%To Score%'
            GROUP BY 1, 2
        )
        SELECT m.league_id, m.event_id, m.starts, m.home, m.away, y.player, y.fair_yes, y.outcome,
               x.xg_home, x.xg_away
        FROM y
        JOIN matches m ON m.event_id = y.event_id
        JOIN match_xg x ON x.event_id = y.event_id AND x.source = 'closing'
        WHERE y.fair_yes > 1.01
        ORDER BY m.starts
    """).df()
    p = p[p.groupby("player").player.transform("size") >= 2].copy()
    # The player's team is the one present in (most of) his matches.
    team = p.groupby("player").apply(
        lambda g: pd.concat([g.home, g.away]).value_counts().index[0], include_groups=False
    )
    p["team"] = p.player.map(team)
    p = p[(p.team == p.home) | (p.team == p.away)].copy()
    p["team_xg"] = np.where(p.team == p.home, p.xg_home, p.xg_away)
    p["p"] = 1 / p.fair_yes
    p["player_xg"] = -np.log(1 - p.p)
    p["share"] = p.player_xg / p.team_xg
    return p


def shrink(shares, prior, k=SHRINK_K):
    return (len(shares) * np.mean(shares) + k * prior) / (len(shares) + k)


def evaluate(p, k=SHRINK_K):
    """Leave-one-out: price each prop from the player's OTHER matches only.
    Compares 'constant player xG' (last-N-games thinking) with share × team xG."""
    prior = p.share.median()
    rows = []
    for i, r in p.iterrows():
        o = p[(p.player == r.player) & (p.index != i)]
        rows.append({
            "const": 1 - np.exp(-o.player_xg.mean()),
            "share": 1 - np.exp(-shrink(o.share, prior, k) * r.team_xg),
        })
    q = pd.DataFrame(rows, index=p.index)
    settled = p.outcome.isin(["W", "L"])
    y = (p.outcome == "W").astype(int)[settled]

    def logloss(pr):
        pr = np.asarray(pr)[settled.values]
        return float(-np.mean(y * np.log(pr) + (1 - y) * np.log(1 - pr)))

    return pd.DataFrame({
        "afvigelse fra Pinnacle (pp)": [np.mean(np.abs(q[c] - p.p)) * 100 for c in ("const", "share")] + [0.0],
        "log loss mod udfald": [logloss(q.const), logloss(q.share), logloss(p.p)],
    }, index=["konstant spiller-xG", "andel × hold-xG", "Pinnacle"])


def update_shares(con, k=SHRINK_K):
    """Write each player's shrunk share of team xG to the player_shares table."""
    p = prop_table(con)
    prior = p.share.median()
    g = p.groupby(["player", "team", "league_id"])
    out = g.agg(n=("share", "size"), share_raw=("share", "mean"),
                p_avg=("p", "mean"), last_seen=("starts", "max")).reset_index()
    out["share"] = [shrink(grp.share, prior, k) for _, grp in g]
    out["updated_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    con.execute("DELETE FROM player_shares")
    con.register("_shares", out[["player", "team", "league_id", "n", "share", "share_raw",
                                 "p_avg", "last_seen", "updated_at"]])
    con.execute("INSERT INTO player_shares SELECT * FROM _shares")
    con.unregister("_shares")
    return out.sort_values("share", ascending=False)
