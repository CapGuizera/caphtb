"""
api.py
======

HTTP client for the Hack The Box v4 API (https://labs.hackthebox.com/api/v4).

Every call uses the `Authorization: Bearer <App Token>` header. The App Token
is generated at https://app.hackthebox.com/profile/settings (the "App Tokens"
tab).

The client is intentionally defensive:
  - it normalizes different response envelopes (`data`, `info`, `message`...);
  - some challenge endpoints were renamed across versions, so we try the new
    endpoint and fall back to the old one;
  - HTTP errors become an HTBError with a friendly message.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from .config import Config


class HTBError(Exception):
    """Communication error with the HTB API (already user-friendly)."""


class HTBClient:
    """Thin, typed wrapper over the Hack The Box v4 API."""

    # A "browser-like" User-Agent because the HTB WAF rejects empty/generic UAs.
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 caphtb/1.0"
    )

    def __init__(self, config: Config, timeout: int = 30):
        if not config.has_token:
            raise HTBError("Token not configured. Run: caphtb login")
        self.cfg = config
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.token}",
                "User-Agent": self.USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------ #
    # Transport layer
    # ------------------------------------------------------------------ #
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.cfg.base_url}{path}"
        try:
            resp = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise HTBError(f"Network failure calling {path}: {exc}") from exc

        if resp.status_code == 401:
            raise HTBError("Invalid or expired token (401). Run: caphtb login")
        if resp.status_code == 403:
            raise HTBError("Access denied (403). This resource may require VIP/permission.")
        if resp.status_code == 404:
            raise HTBError(f"Resource not found (404): {path}")
        if resp.status_code == 429:
            raise HTBError("Rate limit reached (429). Wait a few seconds.")
        if resp.status_code >= 500:
            raise HTBError(f"HTB server error ({resp.status_code}).")

        # Try to parse JSON; some endpoints return plain text.
        try:
            data = resp.json()
        except ValueError:
            if resp.ok:
                return {"message": resp.text.strip()}
            raise HTBError(f"Unexpected response ({resp.status_code}) at {path}.")

        if not resp.ok:
            msg = ""
            if isinstance(data, dict):
                msg = data.get("message") or data.get("error") or ""
            raise HTBError(msg or f"Error {resp.status_code} at {path}.")

        return data

    def _get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", path, params=clean or None)

    def _post(self, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        return self._request("POST", path, json_body=body)

    @staticmethod
    def _unwrap(data: Any, *keys: str) -> Any:
        """Unwrap the first known envelope (`data`, `info`, ...)."""
        if isinstance(data, dict):
            for key in keys:
                if key in data:
                    return data[key]
        return data

    # ================================================================== #
    # USER / PROFILE
    # ================================================================== #
    def self_profile(self) -> dict[str, Any]:
        """Basic profile of the token owner (id comes from the JWT `sub` claim)."""
        uid = self.cfg.user_id
        if not uid:
            raise HTBError("Could not read the user id from the token.")
        data = self._get(f"/user/profile/basic/{uid}")
        return self._unwrap(data, "profile", "info")

    def user_profile(self, user_id: int) -> dict[str, Any]:
        data = self._get(f"/user/profile/basic/{user_id}")
        return self._unwrap(data, "profile", "info")

    # ================================================================== #
    # MACHINES
    # ================================================================== #
    def _paginate(self, path: str, per_page: int = 100, max_pages: int = 50) -> list[dict]:
        """Walk paginated endpoints (shape {data, meta, links})."""
        out: list[dict] = []
        page = 1
        while page <= max_pages:
            data = self._get(path, page=page, per_page=per_page)
            chunk = self._unwrap(data, "data", "info")
            if isinstance(chunk, dict):  # some return a dict of dicts
                chunk = list(chunk.values())
            if not chunk:
                break
            out.extend(chunk)
            # Figure out whether there is a next page from meta/links.
            meta = data.get("meta") if isinstance(data, dict) else None
            if meta and meta.get("current_page") and meta.get("last_page"):
                if meta["current_page"] >= meta["last_page"]:
                    break
            elif len(chunk) < per_page:
                break
            page += 1
        return out

    def machines_active(self) -> list[dict]:
        """Active machines (currently playable, not retired)."""
        return self._paginate("/machine/paginated")

    def machines_retired(self) -> list[dict]:
        """Retired machines."""
        return self._paginate("/machine/list/retired/paginated")

    def machines_unreleased(self) -> list[dict]:
        data = self._get("/machine/unreleased")
        return self._unwrap(data, "data", "info") or []

    def starting_point(self, tier: int) -> list[dict]:
        data = self._get(f"/sp/tier/{tier}")
        info = self._unwrap(data, "data", "info")
        if isinstance(info, dict):
            return info.get("machines", [])
        return info or []

    def machine_profile(self, ident: str | int) -> dict[str, Any]:
        data = self._get(f"/machine/profile/{ident}")
        return self._unwrap(data, "info", "data")

    def machine_active(self) -> Optional[dict[str, Any]]:
        """The machine the user currently has spawned (or None)."""
        data = self._get("/machine/active")
        info = self._unwrap(data, "info")
        return info if info else None

    def machine_owns_top(self, machine_id: int) -> list[dict]:
        """
        Top owners of the machine. This endpoint was removed by the API in
        some regions; if it does not exist, it degrades to an empty list
        (first bloods are still available in the machine profile itself).
        """
        try:
            data = self._get(f"/machine/owns/top/{machine_id}")
            return self._unwrap(data, "info", "data") or []
        except HTBError:
            return []

    # --- VM actions -------------------------------------------------- #
    def spawn(self, machine_id: int) -> dict[str, Any]:
        return self._post("/vm/spawn", {"machine_id": machine_id})

    def terminate(self, machine_id: int) -> dict[str, Any]:
        return self._post("/vm/terminate", {"machine_id": machine_id})

    def reset(self, machine_id: int) -> dict[str, Any]:
        return self._post("/vm/reset", {"machine_id": machine_id})

    def submit_machine_flag(self, machine_id: int, flag: str, difficulty: int) -> dict[str, Any]:
        # difficulty: 1..10 (10 = very hard), required by the API.
        return self._post(
            "/machine/own",
            {"flag": flag, "id": machine_id, "difficulty": difficulty},
        )

    def todo_machines(self) -> list[dict]:
        data = self._get("/machine/todo")
        return self._unwrap(data, "data", "info") or []

    # ================================================================== #
    # CHALLENGES  (includes categories such as Forensics, Pwn, etc.)
    # ================================================================== #
    def challenge_categories(self) -> list[dict]:
        data = self._get("/challenge/categories/list")
        return self._unwrap(data, "info", "data") or []

    def challenges(self, retired: bool = False) -> list[dict]:
        """
        List challenges. HTB has renamed this endpoint over time, so we try
        the new path and fall back to the old one.
        """
        state = "retired" if retired else "active"
        # New (paginated) path.
        try:
            items = self._paginate(f"/challenges?state={state}")
            if items:
                return items
        except HTBError:
            pass
        # Fallback: legacy endpoint.
        legacy = "/challenge/list/retired" if retired else "/challenge/list"
        data = self._get(legacy)
        return self._unwrap(data, "challenges", "info", "data") or []

    def challenge_info(self, challenge_id: int) -> dict[str, Any]:
        data = self._get(f"/challenge/info/{challenge_id}")
        return self._unwrap(data, "challenge", "info", "data")

    def challenge_start(self, challenge_id: int) -> dict[str, Any]:
        """Start a challenge container (when applicable)."""
        return self._post("/challenge/start", {"challenge_id": challenge_id})

    def challenge_stop(self, challenge_id: int) -> dict[str, Any]:
        return self._post("/challenge/stop", {"challenge_id": challenge_id})

    def submit_challenge_flag(self, challenge_id: int, flag: str, difficulty: int) -> dict[str, Any]:
        return self._post(
            "/challenge/own",
            {"flag": flag, "challenge_id": challenge_id, "difficulty": difficulty},
        )

    # ================================================================== #
    # RANKINGS
    # ================================================================== #
    def ranking_world(self) -> list[dict]:
        """Worldwide Hall of Fame (top 100 users)."""
        data = self._get("/rankings/users")
        return self._unwrap(data, "data", "info") or []

    def ranking_country(self, country_code: str) -> list[dict]:
        data = self._get(f"/rankings/country/{country_code.upper()}/members")
        # Shape: {"data": {"country_name": ..., "rankings": [...]}}
        inner = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(inner, dict):
            return inner.get("rankings", []) or []
        return inner or []

    def ranking_teams(self) -> list[dict]:
        data = self._get("/rankings/teams")
        return self._unwrap(data, "data", "info") or []

    def ranking_universities(self) -> list[dict]:
        data = self._get("/rankings/universities")
        return self._unwrap(data, "data", "info") or []

    # ================================================================== #
    # SHERLOCKS  (DFIR / blue team investigations)
    # ================================================================== #
    def sherlocks(self) -> list[dict]:
        """List the Sherlocks - HTB's DFIR challenges."""
        return self._paginate("/sherlocks")

    def sherlock_info(self, sherlock_id: int) -> dict[str, Any]:
        data = self._get(f"/sherlocks/{sherlock_id}/info")
        return self._unwrap(data, "data", "info")

    def sherlock_download(self, sherlock_id: int) -> dict[str, Any]:
        """Return the download link for the Sherlock artifacts."""
        data = self._get(f"/sherlocks/{sherlock_id}/download_link")
        return self._unwrap(data, "data", "info") or data
