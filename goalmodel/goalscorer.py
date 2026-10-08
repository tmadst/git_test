"""Player goalscorer prices from team xG (the Bookie Bashing method).

1. Team xG comes from the market (goalmodel.xg_fit).
2. Remove the share of goals scored by substitutes and own goals — neither
   pays out on a starting player's bet.
3. Share the rest between the STARTERS by weight. Only the ratios matter:
   weights are rescaled to sum to the team's remaining xG, so an unexpected
   three-striker lineup dilutes every striker.
   Weight = position share × player multiplier, or the player xG implied by a
   market anytime price (inverse Poisson: xg = -ln(1 - p)).
4. Poisson forward: anytime = P(>=1), 2+ and 3+; first goalscorer =
   player xG / match xG × P(match has a goal).
"""
import numpy as np
import pandas as pd
from scipy.stats import poisson

# Default share of a team's starter goals by position, before normalising.
# Calibrate these on your own La Liga data (lineups table) over the season.
POSITION_WEIGHT = {"GK": 0.1, "DEF": 4.0, "MID": 9.0, "FWD": 24.0}

# La Liga-ish defaults; calibrate from your own data.
SUB_SHARE = 0.14       # share of goals scored by substitutes
OWN_GOAL_SHARE = 0.03  # share of goals that are own goals


def xg_from_anytime_odds(odds, margin=0.0):
    """Inverse Poisson: player xG implied by a decimal anytime price.
    `margin` strips a proportional overround first (0.08 = 8 %)."""
    p = min(1 / odds / (1 + margin), 0.999999)
    return -np.log(1 - p)


def price_team(team_xg, match_xg, players, sub_share=SUB_SHARE, og_share=OWN_GOAL_SHARE):
    """players: DataFrame/list of dicts with `player` and either `weight`, or
    `position` (+ optional `multiplier`), or `anytime_odds`."""
    df = pd.DataFrame(players).copy()
    if "weight" not in df:
        if "anytime_odds" in df:
            df["weight"] = df["anytime_odds"].map(xg_from_anytime_odds)
        else:
            mult = df["multiplier"].fillna(1.0) if "multiplier" in df else 1.0
            df["weight"] = df["position"].map(POSITION_WEIGHT) * mult
    df["weight"] = df["weight"].clip(lower=0).fillna(0)

    starters_xg = team_xg * max(0.0, 1 - sub_share - og_share)
    total = df["weight"].sum()
    df["xg"] = starters_xg * df["weight"] / total if total > 0 else 0.0
    p_goal = 1 - np.exp(-match_xg)

    df["p_anytime"] = poisson.sf(0, df["xg"])
    df["p_2plus"] = poisson.sf(1, df["xg"])
    df["p_3plus"] = poisson.sf(2, df["xg"])
    df["p_first"] = df["xg"] / match_xg * p_goal
    for m in ("anytime", "2plus", "3plus", "first"):
        df[f"fair_{m}"] = 1 / df[f"p_{m}"]
    return df.drop(columns="weight")


def price_match(xg_home, xg_away, home_players, away_players, **kw):
    match_xg = xg_home + xg_away
    home = price_team(xg_home, match_xg, home_players, **kw).assign(side="home")
    away = price_team(xg_away, match_xg, away_players, **kw).assign(side="away")
    return pd.concat([home, away], ignore_index=True)


def back_ev(p, odds, commission=0.0):
    """EV per unit staked, backing."""
    return p * (odds - 1) * (1 - commission) - (1 - p)


def lay_ev(p, odds, commission=0.0):
    """EV per unit of backer's stake, laying (liability = odds - 1)."""
    return (1 - p) * (1 - commission) - p * (odds - 1)
