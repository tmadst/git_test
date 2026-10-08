# %% [markdown]
# # La Liga målscorer-model
# Kør cellerne én ad gangen i Positron (Ctrl/Cmd+Enter). Kør `python update.py`
# først for at hente nye data. Databasen kan også åbnes i Connections-panelet.

# %%
import pandas as pd

from goalmodel.db import connect
from goalmodel.goalscorer import back_ev, lay_ev, price_match

con = connect()

# %% Kommende kampe med markeds-xG (fra seneste Pinnacle-snapshot)
upcoming = con.sql("""
    SELECT m.event_id, m.starts, m.home, m.away,
           round(x.xg_home, 2) AS xg_home, round(x.xg_away, 2) AS xg_away,
           round(x.xg_home + x.xg_away, 2) AS xg_total, x.odds_ts
    FROM matches m JOIN match_xg x ON x.event_id = m.event_id AND x.source = 'snapshot'
    WHERE m.starts > now()
    ORDER BY m.starts
""").df()
upcoming

# %% Spillede kampe: lukke-xG mod resultat (kalibrering)
played = con.sql("""
    SELECT m.starts, m.home, m.away, x.xg_home, x.xg_away, m.score_home, m.score_away
    FROM matches m JOIN match_xg x ON x.event_id = m.event_id AND x.source = 'closing'
    WHERE m.score_home IS NOT NULL
    ORDER BY m.starts
""").df()
print(played[["xg_home", "xg_away", "score_home", "score_away"]].mean().round(2))
played.tail(10)

# %% Hold-xG over sæsonen (markedets syn på angreb / forsvar)
con.sql("""
    WITH t AS (
        SELECT home AS team, xg_home AS xg_for, xg_away AS xg_against, score_home AS gf, score_away AS ga
        FROM matches JOIN match_xg USING (event_id) WHERE source = 'closing'
        UNION ALL
        SELECT away, xg_away, xg_home, score_away, score_home
        FROM matches JOIN match_xg USING (event_id) WHERE source = 'closing'
    )
    SELECT team, count(*) AS games,
           round(avg(xg_for), 2) AS xg_for, round(avg(xg_against), 2) AS xg_against,
           round(avg(gf), 2) AS goals_for, round(avg(ga), 2) AS goals_against
    FROM t GROUP BY team ORDER BY xg_for DESC
""").df()

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
