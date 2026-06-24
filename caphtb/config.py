"""
config.py
=========

Gerencia a configuracao persistente da ferramenta:

  - token da API do HTB (App Token)
  - URL base da API (caso o HTB mude o dominio)
  - pais padrao para ranking (ex.: BR)
  - id do time padrao para ranking de time

A configuracao fica em ~/.config/caphtb/config.json com permissao 0600
(somente o dono le/escreve), porque o token e um segredo.

Tambem da pra sobrescrever o token via variavel de ambiente HTB_TOKEN,
util para CI ou para nao gravar nada em disco.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Diretorio e arquivo de configuracao seguindo o padrao XDG.
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "caphtb"
CONFIG_FILE = CONFIG_DIR / "config.json"

# URL base padrao da API v4 do Hack The Box.
DEFAULT_BASE_URL = "https://labs.hackthebox.com/api/v4"


@dataclass
class Config:
    """Estrutura tipada da configuracao da ferramenta."""

    token: str = ""
    base_url: str = DEFAULT_BASE_URL
    country: str = "BR"          # codigo ISO usado no ranking por pais
    team_id: Optional[int] = None  # id do time para o ranking de time
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Carregamento / gravacao
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls) -> "Config":
        """Le a config do disco (se existir) e aplica overrides de ambiente."""
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

        # A variavel de ambiente sempre vence o que esta gravado em disco.
        env_token = os.environ.get("HTB_TOKEN")
        if env_token:
            cfg.token = env_token.strip()

        return cfg

    def save(self) -> None:
        """Grava a config no disco com permissao restrita (0600)."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        CONFIG_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except OSError:
            # Em alguns sistemas de arquivos chmod pode falhar; nao e fatal.
            pass

    # ------------------------------------------------------------------ #
    # Utilidades de token
    # ------------------------------------------------------------------ #
    @property
    def has_token(self) -> bool:
        return bool(self.token)

    def jwt_claims(self) -> dict[str, Any]:
        """
        Decodifica (sem validar assinatura) o payload do JWT para extrair
        claims uteis como `sub` (id do usuario) e `exp` (expiracao).

        Nao verificamos a assinatura porque nao temos a chave publica e
        so queremos ler metadados do nosso proprio token.
        """
        try:
            payload_b64 = self.token.split(".")[1]
            # base64url precisa de padding multiplo de 4.
            payload_b64 += "=" * (-len(payload_b64) % 4)
            raw = base64.urlsafe_b64decode(payload_b64)
            return json.loads(raw)
        except (IndexError, ValueError, json.JSONDecodeError):
            return {}

    @property
    def user_id(self) -> Optional[int]:
        """Id do usuario dono do token, lido do claim `sub`."""
        claims = self.jwt_claims()
        sub = claims.get("sub")
        try:
            return int(sub) if sub is not None else None
        except (TypeError, ValueError):
            return None

    def token_expires_in_days(self) -> Optional[float]:
        """Quantos dias faltam para o token expirar (None se nao der pra ler)."""
        claims = self.jwt_claims()
        exp = claims.get("exp")
        if not exp:
            return None
        return (float(exp) - time.time()) / 86400.0
