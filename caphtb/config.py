"""
config.py
=========

Manages the persistent configuration of the tool:

  - HTB API token (App Token)
  - API base URL (in case HTB changes the domain)
  - default country for rankings (e.g. BR)
  - default team id for team rankings

The configuration lives in ~/.config/caphtb/config.json with permission 0600
(owner read/write only), because the token is a secret.

You can also override the token via the HTB_TOKEN environment variable, which
is handy for CI or when you do not want to write anything to disk.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Config directory and file following the XDG standard.
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "caphtb"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Default base URL of the Hack The Box v4 API.
DEFAULT_BASE_URL = "https://labs.hackthebox.com/api/v4"


@dataclass
class Config:
    """Typed representation of the tool configuration."""

    token: str = ""
    base_url: str = DEFAULT_BASE_URL
    country: str = "BR"          # ISO code used by the country ranking
    team_id: Optional[int] = None  # team id used by the team ranking
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Loading / saving
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls) -> "Config":
        """Read the config from disk (if any) and apply environment overrides."""
        data: dict[str, Any] = {}
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        cfg = cls(
            token=data.get("token", ""),
            base_url=data.get("base_url", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            country=data.get("country", "BR") or "BR",
            team_id=data.get("team_id"),
            extra=data.get("extra", {}) or {},
        )

        # The environment variable always wins over what is stored on disk.
        env_token = os.environ.get("HTB_TOKEN")
        if env_token:
            cfg.token = env_token.strip()

        return cfg

    def save(self) -> None:
        """Write the config to disk with restricted permission (0600)."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        CONFIG_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            # On some filesystems chmod may fail; this is not fatal.
            pass

    # ------------------------------------------------------------------ #
    # Token helpers
    # ------------------------------------------------------------------ #
    @property
    def has_token(self) -> bool:
        return bool(self.token)

    def jwt_claims(self) -> dict[str, Any]:
        """
        Decode (without verifying the signature) the JWT payload to extract
        useful claims such as `sub` (user id) and `exp` (expiry).

        We do not verify the signature because we do not have the public key
        and we only want to read metadata from our own token.
        """
        try:
            payload_b64 = self.token.split(".")[1]
            # base64url needs padding to a multiple of 4.
            payload_b64 += "=" * (-len(payload_b64) % 4)
            raw = base64.urlsafe_b64decode(payload_b64)
            return json.loads(raw)
        except (IndexError, ValueError, json.JSONDecodeError):
            return {}

    @property
    def user_id(self) -> Optional[int]:
        """Id of the user who owns the token, read from the `sub` claim."""
        claims = self.jwt_claims()
        sub = claims.get("sub")
        try:
            return int(sub) if sub is not None else None
        except (TypeError, ValueError):
            return None

    def token_expires_in_days(self) -> Optional[float]:
        """Days left before the token expires (None if it cannot be read)."""
        claims = self.jwt_claims()
        exp = claims.get("exp")
        if not exp:
            return None
        return (float(exp) - time.time()) / 86400.0
