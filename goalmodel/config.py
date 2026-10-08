from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "goalmodel.duckdb"

API_BASE = "https://api.bettingiscool.com"
SOCCER = 29

# Pinnacle league ids (GET /api/leagues?sport_id=29)
LEAGUES = {
    "laliga": 2196,  # Spain - La Liga
    "epl": 1980,  # England - Premier League
}

# 2026/27 season window
SEASON_START = "2026-08-01T00:00:00Z"
