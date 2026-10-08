"""Thin client for the bettingiscool Pinnacle Data API.

Every call costs 1 + (rows returned) tokens, so each call is logged to the
api_log table with its row count — check it with `SELECT * FROM api_log`.
"""
import os
import time

import requests

from .config import API_BASE, ROOT


def _load_env():
    """Read KEY=value lines from .env (or .env.txt, which Notepad tends to
    create) into os.environ. No python-dotenv needed; tolerates Notepad's BOM."""
    for name in (".env", ".env.txt"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return path
    return None


_ENV_FILE = _load_env()


class ApiClient:
    def __init__(self, con=None, api_key=None):
        self.con = con
        self.session = requests.Session()
        key = api_key or os.environ.get("BETTINGISCOOL_API_KEY")
        if key and key != "your-key-here":
            self.session.headers["X-API-Key"] = key
        elif not os.environ.get("HTTPS_PROXY"):  # (cloud sandbox injects the key)
            where = _ENV_FILE or ROOT / ".env"
            raise RuntimeError(
                f"Ingen API-nøgle fundet. Skriv BETTINGISCOOL_API_KEY=<din nøgle> i {where}"
            )

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(5):
            res = self.session.get(API_BASE + path, params=params, timeout=60)
            if res.status_code != 429:
                break
            time.sleep(0.5 * 2**attempt)
        if res.status_code in (401, 403):
            raise RuntimeError(f"API-nøglen blev afvist ({res.status_code}) — tjek BETTINGISCOOL_API_KEY i .env")
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

    def specials_closing(self, event_id):
        """Closing price + W/L outcome for every special on a match."""
        return self.get("/api/specials/closing", event_id=event_id)

    def special_history(self, special_id):
        return self.get("/api/specials/odds", special_id=special_id, full_history=1)

    def results(self, event_id):
        return self.get("/api/results", event_id=event_id)
