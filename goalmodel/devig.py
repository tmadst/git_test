"""Remove the bookmaker margin with the power (logarithmic) method — the same
method the API's `todds` use: find k so that sum((1/odds)^k) = 1."""
import numpy as np
from scipy.optimize import brentq


def power_devig(odds):
    q = 1 / np.asarray(odds, dtype=float)
    k = brentq(lambda k: (q**k).sum() - 1, 0.2, 5)
    return 1 / q**k  # fair decimal odds


def fair_row(market, line, *odds):
    """Pinnacle-style row (odds1 = home/over, odds0 = draw, odds2 = away/under)
    with power-devigged todds, ready for xg_fit.fit_match."""
    fair = power_devig(odds)
    if len(odds) == 3:
        return {"market": market, "line": line, "todds1": fair[0], "todds0": fair[1], "todds2": fair[2]}
    return {"market": market, "line": line, "todds1": fair[0], "todds0": None, "todds2": fair[1]}
