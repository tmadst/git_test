# %% [markdown]
# # La Liga målscorer-model
# Kør cellerne én ad gangen i Positron (Ctrl/Cmd+Enter). Kør `python update.py`
# først for at hente nye data. Databasen kan også åbnes i Connections-panelet.

# %%
import pandas as pd

from goalmodel.config import LEAGUES
from goalmodel.db import connect
from goalmodel.goalscorer import back_ev, lay_ev, price_match

con = connect()
LEAGUE = "laliga"  # "laliga" eller "epl"
LEAGUE_ID = LEAGUES[LEAGUE]

# %% Kommende kampe med markeds-xG (fra seneste Pinnacle-snapshot)
upcoming = con.sql("""
    SELECT m.event_id, m.starts, m.home, m.away,
           round(x.xg_home, 2) AS xg_home, round(x.xg_away, 2) AS xg_away,
           round(x.xg_home + x.xg_away, 2) AS xg_total, x.odds_ts
    FROM matches m JOIN match_xg x ON x.event_id = m.event_id AND x.source = 'snapshot'
    WHERE m.starts > now() AND m.league_id = $lg
    ORDER BY m.starts
""", params={"lg": LEAGUE_ID}).df()
upcoming

# %% Spillede kampe: lukke-xG mod resultat (kalibrering)
played = con.sql("""
    SELECT m.starts, m.home, m.away, x.xg_home, x.xg_away, m.score_home, m.score_away
    FROM matches m JOIN match_xg x ON x.event_id = m.event_id AND x.source = 'closing'
    WHERE m.score_home IS NOT NULL AND m.league_id = $lg
    ORDER BY m.starts
""", params={"lg": LEAGUE_ID}).df()
print(played[["xg_home", "xg_away", "score_home", "score_away"]].mean().round(2))
played.tail(10)

# %% Hold-xG over sæsonen (markedets syn på angreb / forsvar)
con.sql("""
    WITH t AS (
        SELECT home AS team, xg_home AS xg_for, xg_away AS xg_against, score_home AS gf, score_away AS ga
        FROM matches JOIN match_xg USING (event_id)
        WHERE source = 'closing' AND league_id = $lg AND starts >= '2026-08-01'
        UNION ALL
        SELECT away, xg_away, xg_home, score_away, score_home
        FROM matches JOIN match_xg USING (event_id)
        WHERE source = 'closing' AND league_id = $lg AND starts >= '2026-08-01'
    )
    SELECT team, count(*) AS games,
           round(avg(xg_for), 2) AS xg_for, round(avg(xg_against), 2) AS xg_against,
           round(avg(gf), 2) AS goals_for, round(avg(ga), 2) AS goals_against
    FROM t GROUP BY team ORDER BY xg_for DESC
""", params={"lg": LEAGUE_ID}).df()

# %% Målscorer-priser for én kamp
# Udfyld startopstillingerne (10 markspillere + evt. målmand) når holdene er ude.
# Vægt pr. spiller: position (+ multiplier for fx en topscorer), ELLER
# 'anytime_odds' = markedets anytime-pris (så bruges inverse Poisson).
match = upcoming.iloc[0]
home_xi = [
    {"player": "Angriber A", "position": "FWD", "multiplier": 1.3},
    {"player": "Angriber B", "position": "FWD"},
    {"player": "Midtbane 1", "position": "MID"},
    {"player": "Midtbane 2", "position": "MID"},
    {"player": "Midtbane 3", "position": "MID"},
    {"player": "Midtbane 4", "position": "MID"},
    {"player": "Forsvar 1", "position": "DEF"},
    {"player": "Forsvar 2", "position": "DEF", "multiplier": 1.5},  # stærk i luften
    {"player": "Forsvar 3", "position": "DEF"},
    {"player": "Forsvar 4", "position": "DEF"},
]
away_xi = [{"player": f"Ude {p}{i}", "position": p} for i, p in enumerate(["FWD"] * 2 + ["MID"] * 4 + ["DEF"] * 4)]

prices = price_match(match.xg_home, match.xg_away, home_xi, away_xi)
print(f"{match.home} – {match.away}: xG {match.xg_home} – {match.xg_away}")
prices[["side", "player", "xg", "fair_anytime", "fair_first", "fair_2plus", "fair_3plus"]].round(3)

# %% Sammenlign med exchange-priser (back og lay, 2 % kommission)
offered = {"Angriber A": {"back": 2.9, "lay": 3.05}}  # anytime-priser fra exchangen
for name, o in offered.items():
    p = prices.loc[prices.player == name, "p_anytime"].iloc[0]
    print(name, f"fair {1/p:.2f}",
          f"back EV {back_ev(p, o['back'], 0.02):+.1%}",
          f"lay EV {lay_ev(p, o['lay'], 0.02):+.1%}")

# %% Tokenforbrug
con.sql("SELECT date_trunc('day', called_at) AS day, count(*) AS calls, sum(tokens) AS tokens FROM api_log GROUP BY 1 ORDER BY 1").df()

# %% Manuel indtastning: odds fra en skærm (fx Barcelona – Getafe)
# fair_row(marked, linje, odds1, [odds0,] odds2): linje = hjemmeholdets handicap
# for 'spread', total for 'totals'/'home_totals'/'away_totals'. Kvartlinjer: "2.5-3" = -2.75.
from goalmodel.devig import fair_row
from goalmodel.xg_fit import fit_match

rows = [fair_row("moneyline", 0, 1.077, 14.970, 22.380)]
for l, a, b in [(-3.0, 2.200, 1.699), (-2.75, 1.934, 1.934), (-2.5, 1.740, 2.140)]:
    rows.append(fair_row("spread", l, a, b))
for l, a, b in [(4.0, 2.090, 1.757), (3.75, 1.847, 2.020), (3.5, 1.666, 2.230)]:
    rows.append(fair_row("totals", l, a, b))
rows.append(fair_row("home_totals", 3.5, 2.120, 1.724))
rows.append(fair_row("away_totals", 0.5, 2.250, 1.645))
xg_h, xg_a, rmse, n = fit_match(rows)
print(f"xG {xg_h:.2f} – {xg_a:.2f}")
price_match(xg_h, xg_a, home_xi, away_xi)[["side", "player", "xg", "fair_anytime", "fair_first", "fair_2plus"]].round(2)
