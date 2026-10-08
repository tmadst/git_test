# %% [markdown]
# # Kalibrering af målscorer-modellen på Pinnacles props
# Spillerens andel af holdets xG = (xG fra Pinnacles "To Score"-pris) / (holdets markeds-xG).
# Kør `python update.py` først — den opdaterer også tabellen player_shares.

# %%
import numpy as np
import pandas as pd

from goalmodel import calibrate
from goalmodel.db import connect

con = connect()
p = calibrate.prop_table(con)
print(f"{len(p)} props, {p.player.nunique()} spillere med mindst 2 kampe")

# %% 1. Følger spillerens xG holdets xG? (hældning 1 = proportionalt, som videoen antager)
g = p.groupby("player")
dx = np.log(p.team_xg) - g.team_xg.transform(lambda s: np.log(s).mean())
dy = np.log(p.player_xg) - g.player_xg.transform(lambda s: np.log(s).mean())
print("elasticitet:", round(np.polyfit(dx, dy, 1)[0], 3))
print("variation fra kamp til kamp (CV): andel %.2f vs. spiller-xG %.2f" % (
    (g.share.std() / g.share.mean()).mean(), (g.player_xg.std() / g.player_xg.mean()).mean()))

# %% 2. Leave-one-out: pris hver prop kun ud fra spillerens ANDRE kampe
calibrate.evaluate(p).round(4)

# %% 3. Valg af shrinkage k (hvor meget trækkes mod liga-medianen)
pd.DataFrame({k: calibrate.evaluate(p, k).iloc[1] for k in (0, 0.5, 1, 2, 4, 8)}).T.round(4)

# %% 4. Spillernes kalibrerede andel af holdets xG
con.sql("""
    SELECT player, team, n, round(share, 3) AS share, round(share_raw, 3) AS share_raw,
           round(p_avg, 3) AS p_avg, last_seen::date AS last_seen
    FROM player_shares ORDER BY share DESC
""").df()

# %% 5. Andel pr. hold: hvor meget af holdets xG ligger hos de kendte stjerner?
con.sql("""
    SELECT team, count(*) AS spillere, round(sum(share), 3) AS sum_share, list(player ORDER BY share DESC) AS hvem
    FROM player_shares GROUP BY team ORDER BY sum_share DESC
""").df()
