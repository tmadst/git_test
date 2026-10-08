"""Local DuckDB database. Open data/goalmodel.duckdb in Positron's Connections pane."""
import duckdb

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_log (
    called_at TIMESTAMP, path VARCHAR, params VARCHAR, tokens INTEGER
);

-- Pinnacle fixtures. Pinnacle sometimes lists the same match under two
-- event_ids; only one carries odds. Views below keep the one with odds.
CREATE TABLE IF NOT EXISTS fixtures (
    event_id BIGINT PRIMARY KEY,
    league_id INTEGER,
    league_name VARCHAR,
    starts TIMESTAMP,
    home VARCHAR,
    away VARCHAR,
    updated_at TIMESTAMP
);

-- Closing line: every market/line Pinnacle offered, last price before kickoff.
-- odds* = offered, todds* = Pinnacle's fair (vig-free) odds.
-- odds1/todds1 = home / over, odds0 = draw, odds2 = away / under.
CREATE TABLE IF NOT EXISTS odds_closing (
    event_id BIGINT,
    period INTEGER,
    market VARCHAR,
    line DOUBLE,
    odds1 DOUBLE, odds0 DOUBLE, odds2 DOUBLE,
    todds1 DOUBLE, todds0 DOUBLE, todds2 DOUBLE,
    max_win DOUBLE,
    ts TIMESTAMP,
    PRIMARY KEY (event_id, period, market, line)
);

-- Pre-match snapshots, appended every time you run update for upcoming games.
CREATE TABLE IF NOT EXISTS odds_snapshots (
    fetched_at TIMESTAMP,
    event_id BIGINT,
    period INTEGER,
    market VARCHAR,
    line DOUBLE,
    odds1 DOUBLE, odds0 DOUBLE, odds2 DOUBLE,
    todds1 DOUBLE, todds0 DOUBLE, todds2 DOUBLE,
    max_win DOUBLE,
    ts TIMESTAMP
);

CREATE TABLE IF NOT EXISTS results (
    event_id BIGINT,
    period INTEGER,
    status INTEGER,
    score_home INTEGER,
    score_away INTEGER,
    PRIMARY KEY (event_id, period)
);

-- Market-implied expected goals per match, fitted by goalmodel.xg_fit.
-- source = 'closing' or 'snapshot'.
CREATE TABLE IF NOT EXISTS match_xg (
    event_id BIGINT,
    source VARCHAR,
    fitted_at TIMESTAMP,
    odds_ts TIMESTAMP,
    xg_home DOUBLE,
    xg_away DOUBLE,
    rmse DOUBLE,
    n_prices INTEGER,
    PRIMARY KEY (event_id, source)
);

-- Player goals (enter yourself, or import). Used to calibrate position shares
-- and multipliers and to settle goalscorer bets.
CREATE TABLE IF NOT EXISTS players (
    player VARCHAR,
    team VARCHAR,
    position VARCHAR,          -- GK / DEF / MID / FWD
    multiplier DOUBLE DEFAULT 1.0,
    PRIMARY KEY (player, team)
);

-- Player share of team xG, calibrated on Pinnacle props (goalmodel.calibrate).
CREATE TABLE IF NOT EXISTS player_shares (
    player VARCHAR,
    team VARCHAR,
    league_id INTEGER,
    n INTEGER,              -- props used
    share DOUBLE,           -- shrunk share of team xG (use this)
    share_raw DOUBLE,
    p_avg DOUBLE,
    last_seen TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (player, team)
);

CREATE TABLE IF NOT EXISTS lineups (
    event_id BIGINT,
    team VARCHAR,
    player VARCHAR,
    started BOOLEAN,
    goals INTEGER DEFAULT 0,
    own_goals INTEGER DEFAULT 0,
    PRIMARY KEY (event_id, player)
);

-- Closing price + settlement of every Pinnacle special (team & player props).
-- outcome: W / L (others = refund/void).
CREATE TABLE IF NOT EXISTS specials_closing (
    event_id BIGINT,
    special_id BIGINT,
    special_name VARCHAR,
    category VARCHAR,
    bet_type VARCHAR,
    contestant_id BIGINT,
    contestant_name VARCHAR,
    handicap DOUBLE,
    odds DOUBLE,
    todds DOUBLE,
    max_win DOUBLE,
    ts TIMESTAMP,
    outcome VARCHAR,
    PRIMARY KEY (event_id, contestant_id)
);

-- Which events we already asked for specials (so empty ones aren't re-paid).
CREATE TABLE IF NOT EXISTS specials_fetched (
    event_id BIGINT PRIMARY KEY, fetched_at TIMESTAMP, n_rows INTEGER
);

-- Full pre-match price history of player props (cheap: per special_id).
CREATE TABLE IF NOT EXISTS specials_history (
    special_id BIGINT,
    contestant_id BIGINT,
    odds DOUBLE,
    todds DOUBLE,
    max_win DOUBLE,
    ts TIMESTAMP,
    PRIMARY KEY (special_id, contestant_id, ts)
);

-- Matches with the duplicate (odds-less) event ids removed.
CREATE OR REPLACE VIEW matches AS
SELECT f.*, r.score_home, r.score_away
FROM fixtures f
LEFT JOIN results r ON r.event_id = f.event_id AND r.period = 0
QUALIFY row_number() OVER (
    PARTITION BY f.league_id, f.starts, f.home, f.away
    ORDER BY (EXISTS (SELECT 1 FROM odds_closing c WHERE c.event_id = f.event_id)
              OR EXISTS (SELECT 1 FROM odds_snapshots s WHERE s.event_id = f.event_id)) DESC,
             f.updated_at DESC
) = 1;

-- Main total line per match at close (the line with fair prices closest to 50/50).
CREATE OR REPLACE VIEW closing_main_total AS
SELECT event_id, line, odds1 AS over_odds, odds2 AS under_odds,
       todds1 AS over_fair, todds2 AS under_fair
FROM odds_closing
WHERE period = 0 AND market = 'totals' AND todds1 IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY event_id ORDER BY abs(todds1 - todds2)) = 1;
"""


def connect(path=DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(SCHEMA)
    return con
