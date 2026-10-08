# %% [markdown]
# # Backtest: Pinnacles målscorer-odds ("X To Score")
# Hvor godt har Pinnacles anytime-priser ramt, og hvad havde det givet at
# spille dem ved åbning vs. lukning? Kør `python update.py` først.

# %%
import numpy as np
import pandas as pd

from goalmodel.db import connect

con = connect()

# One row per prop: Yes/No price at open (first posted) and close, plus result.
props = con.sql("""
    WITH c AS (
        SELECT s.event_id, s.special_id,
               regexp_replace(s.special_name, '\\s*To Score.*$', '') AS player,
               max(CASE WHEN contestant_name = 'Yes' THEN contestant_id END) AS yes_id,
               max(CASE WHEN contestant_name = 'No'  THEN contestant_id END) AS no_id,
               max(CASE WHEN contestant_name = 'Yes' THEN odds END)  AS close_yes,
               max(CASE WHEN contestant_name = 'No'  THEN odds END)  AS close_no,
               max(CASE WHEN contestant_name = 'Yes' THEN todds END) AS fair_close_yes,
               max(CASE WHEN contestant_name = 'No'  THEN todds END) AS fair_close_no,
               max(CASE WHEN contestant_name = 'Yes' THEN outcome END) AS outcome,
               max(max_win) AS limit_close
        FROM specials_closing s
        WHERE category = 'Player Props' AND special_name ILIKE '%To Score%'
        GROUP BY 1, 2, 3
    ),
    o AS (
        SELECT special_id, contestant_id,
               arg_min(odds, ts) AS open_odds, arg_min(todds, ts) AS open_fair, min(ts) AS open_ts
        FROM specials_history GROUP BY 1, 2
    )
    SELECT m.starts, m.home, m.away, c.player, c.outcome,
           oy.open_odds AS open_yes, onn.open_odds AS open_no,
           oy.open_fair AS fair_open_yes, oy.open_ts,
           c.close_yes, c.close_no, c.fair_close_yes, c.fair_close_no, c.limit_close,
           x.xg_home, x.xg_away
    FROM c
    JOIN matches m ON m.event_id = c.event_id
    LEFT JOIN o oy  ON oy.special_id = c.special_id AND oy.contestant_id = c.yes_id
    LEFT JOIN o onn ON onn.special_id = c.special_id AND onn.contestant_id = c.no_id
    LEFT JOIN match_xg x ON x.event_id = c.event_id AND x.source = 'closing'
    ORDER BY m.starts
""").df()

props = props[props.outcome.isin(["W", "L"])].copy()  # drop voids / non-starters
props["scored"] = (props.outcome == "W").astype(int)
props["p_close"] = 1 / props.fair_close_yes        # Pinnacle's fair P(score) at close
props["p_open"] = 1 / props.fair_open_yes
print(f"{len(props)} afregnede props, {props.player.nunique()} spillere, "
      f"{props.starts.min():%Y-%m-%d} → {props.starts.max():%Y-%m-%d}")

# %% 1. Kalibrering: forventede mål-scorere (sum af fair sandsynlighed) vs. faktiske
def calib(df, p="p_close"):
    n = len(df)
    exp, hit = df[p].sum(), df.scored.sum()
    brier = ((df[p] - df.scored) ** 2).mean()
    base = ((df.scored.mean() - df.scored) ** 2).mean()
    # z-score of hits vs expectation (Bernoulli sum)
    z = (hit - exp) / np.sqrt((df[p] * (1 - df[p])).sum())
    return pd.Series({"n": n, "forventet": exp, "faktisk": hit,
                      "faktisk/forventet": hit / exp, "z": z,
                      "brier": brier, "brier_naiv": base})

print(calib(props).round(3))
props["bucket"] = pd.cut(props.p_close, [0, .3, .4, .5, .6, .7, 1])
props.groupby("bucket", observed=True).apply(calib, include_groups=False).round(3)

# %% 2. ROI: flad 1 enhed pr. bet på Ja / Nej, ved åbning og lukning
def roi(df, side, when):
    odds = df[f"{when}_{side}"]
    win = df.scored if side == "yes" else 1 - df.scored
    d = pd.DataFrame({"odds": odds, "win": win}).dropna()
    pnl = d.win * (d.odds - 1) - (1 - d.win)
    se = pnl.std(ddof=1) / np.sqrt(len(d)) if len(d) > 1 else np.nan
    return pd.Series({"bets": len(d), "profit": pnl.sum(), "roi": pnl.mean(), "roi_±1se": se})

pd.DataFrame({f"{s} @ {w}": roi(props, s, w)
              for w in ("open", "close") for s in ("yes", "no")}).T.round(3)

# %% 3. Linjebevægelse: åbning → lukning (CLV = åbningspris / fair lukkepris − 1)
props["clv_yes"] = props.open_yes / props.fair_close_yes - 1
props["clv_no"] = props.open_no / props.fair_close_no - 1
print(props[["clv_yes", "clv_no"]].describe().round(3))
# Did the market move the right way? Scorers' price should shorten.
props["move_yes"] = props.p_close - props.p_open
props.groupby("scored")["move_yes"].mean().round(4)

# %% 4. Spillerens andel af holdets xG (inverse Poisson) — til målscorer-modellen
props["player_xg"] = -np.log(1 - props.p_close)
# Which team? Use whichever team xG makes the share plausible (player listed for one side).
props["share_home"] = props.player_xg / props.xg_home
props["share_away"] = props.player_xg / props.xg_away
(props.groupby("player")
      .agg(kampe=("scored", "size"), mål_kampe=("scored", "sum"),
           p_snit=("p_close", "mean"), xg_snit=("player_xg", "mean"))
      .sort_values("kampe", ascending=False).round(3))

# %% Alle props
props[["starts", "home", "away", "player", "open_yes", "close_yes", "fair_close_yes",
       "close_no", "outcome", "limit_close"]]
