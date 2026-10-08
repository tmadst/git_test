"""Thin client for the bettingiscool Pinnacle Data API.

Every call costs 1 + (rows returned) tokens, so each call is logged to the
api_log table with its row count — check it with `SELECT * FROM api_log`.
"""
import os
import time

import requests

from .config import API_BASE

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class ApiClient:
    def __init__(self, con=None, api_key=None):
        self.con = con
        self.session = requests.Session()
        key = api_key or os.environ.get("BETTINGISCOOL_API_KEY")
        if key:
            self.session.headers["X-API-Key"] = key

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(5):
            res = self.session.get(API_BASE + path, params=params, timeout=60)
            if res.status_code != 429:
                break
            time.sleep(0.5 * 2**attempt)
        if res.status_code == 403:
            raise RuntimeError("API key rejected (403) — check BETTINGISCOOL_API_KEY in .env")
        res.raise_for_status()
        data = res.json()
        rows = len(data) if isinstance(data, list) else 0
        if self.con is not None:
            self.con.execute(
                "INSERT INTO api_log VALUES (now(), ?, ?, ?)",
                [path, str(params), 1 + rows],
            )
        return data

    def leagues(self, sport_id):
        return self.get("/api/leagues", sport_id=sport_id)

    def fixtures(self, league_id, starts_from=None, starts_to=None):
        return self.get(
            "/api/fixtures",
            league_id=league_id,
            starts_from=starts_from,
            starts_to=starts_to,
            limit=1000,
        )

    def odds(self, event_id, period=0):
        """Latest snapshot: one row per (market, line). Pre-match / live."""
        return self.get("/api/odds", event_id=event_id, period=period)

    def closing(self, event_id):
        """Closing line for every market + final score. Only after kickoff."""
        return self.get("/api/closing", event_id=event_id)

    def results(self, event_id):
        return self.get("/api/results", event_id=event_id)
