"""Pull new Pinnacle data into data/goalmodel.duckdb and refit match xG.

    python update.py              # all leagues (La Liga + Premier League)
    python update.py --league epl # only one league
    python update.py --days 3     # snapshots only for games within 3 days

Cheap to run often: finished matches are fetched once, fixtures once per run,
and only upcoming games get a fresh odds snapshot.
"""
import argparse

from goalmodel import calibrate, ingest, xg_fit
from goalmodel.api import ApiClient
from goalmodel.config import LEAGUES, SEASON_START
from goalmodel.db import connect


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="all", choices=["all", *sorted(LEAGUES)])
    ap.add_argument("--days", type=int, default=7, help="snapshot games within N days")
    ap.add_argument("--since", default=SEASON_START,
                    help="fixtures from this date, e.g. 2025-08-01T00:00:00Z for last season too")
    args = ap.parse_args()

    con = connect()
    api = ApiClient(con)
    leagues = LEAGUES if args.league == "all" else {args.league: LEAGUES[args.league]}
    start = con.execute("SELECT coalesce(sum(tokens), 0) FROM api_log").fetchone()[0]

    for name, league_id in leagues.items():
        print(f"== {name}")
        print("fixtures:", ingest.update_fixtures(con, api, league_id, since=args.since))
        print("closing fetched:", ingest.update_closing(con, api, league_id))
        print("snapshots with odds:", ingest.update_snapshots(con, api, league_id, args.days))
        print("specials (matches, player props):", ingest.update_specials(con, api, league_id))
    print("== xG")
    print("closing xG fitted:", xg_fit.fit_closing(con))
    print("upcoming xG fitted:", xg_fit.fit_snapshots(con))
    print("player shares calibrated:", len(calibrate.update_shares(con)))

    used = con.execute("SELECT coalesce(sum(tokens), 0) FROM api_log").fetchone()[0] - start
    print(f"API tokens used this run: {used}")
    con.close()


if __name__ == "__main__":
    main()
