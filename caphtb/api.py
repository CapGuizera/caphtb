"""
api.py
======

Cliente HTTP para a API v4 do Hack The Box (https://labs.hackthebox.com/api/v4).

Toda chamada usa o header `Authorization: Bearer <App Token>`. O App Token
e gerado em https://app.hackthebox.com/profile/settings (aba "App Tokens").

O cliente e proposital e defensivamente escrito:
  - normaliza diferentes formatos de resposta (`data`, `info`, `message`...);
  - alguns endpoints de challenge mudaram de nome entre versoes, entao
    tentamos o endpoint novo e caimos para o antigo (fallback);
  - erros HTTP viram excecao HTBError com mensagem amigavel.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from .config import Config


class HTBError(Exception):
    """Erro de comunicacao com a API do HTB (com mensagem ja tratada)."""


class HTBClient:
    """Wrapper fino e tipado sobre a API v4 do Hack The Box."""

    # User-Agent "de navegador" porque o WAF do HTB rejeita UAs vazios/genericos.
    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 caphtb/1.0"
    )

    def __init__(self, config: Config, timeout: int = 30):
        if not config.has_token:
            raise HTBError("Token nao configurado. Rode: caphtb login")
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
    # Camada de transporte
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
            raise HTBError(f"Falha de rede ao chamar {path}: {exc}") from exc

        if resp.status_code == 401:
            raise HTBError("Token invalido ou expirado (401). Rode: caphtb login")
        if resp.status_code == 403:
            raise HTBError("Acesso negado (403). Esse recurso pode exigir VIP/permissao.")
        if resp.status_code == 404:
            raise HTBError(f"Recurso nao encontrado (404): {path}")
        if resp.status_code == 429:
            raise HTBError("Rate limit atingido (429). Aguarde alguns segundos.")
        if resp.status_code >= 500:
            raise HTBError(f"Erro no servidor do HTB ({resp.status_code}).")

        # Tenta extrair JSON; alguns endpoints retornam texto puro.
        try:
            data = resp.json()
        except ValueError:
            if resp.ok:
                return {"message": resp.text.strip()}
            raise HTBError(f"Resposta inesperada ({resp.status_code}) em {path}.")

        if not resp.ok:
            msg = ""
            if isinstance(data, dict):
                msg = data.get("message") or data.get("error") or ""
            raise HTBError(msg or f"Erro {resp.status_code} em {path}.")

        return data

    def _get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", path, params=clean or None)

    def _post(self, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        return self._request("POST", path, json_body=body)

    @staticmethod
    def _unwrap(data: Any, *keys: str) -> Any:
        """Desembrulha o primeiro envelope conhecido (`data`, `info`, ...)."""
        if isinstance(data, dict):
            for key in keys:
                if key in data:
                    return data[key]
        return data

    # ================================================================== #
    # USUARIO / PERFIL
    # ================================================================== #
    def self_profile(self) -> dict[str, Any]:
        """Perfil basico do dono do token (id vem do claim `sub` do JWT)."""
        uid = self.cfg.user_id
        if not uid:
            raise HTBError("Nao foi possivel ler o id do usuario do token.")
        data = self._get(f"/user/profile/basic/{uid}")
        return self._unwrap(data, "profile", "info")

    def user_profile(self, user_id: int) -> dict[str, Any]:
        data = self._get(f"/user/profile/basic/{user_id}")
        return self._unwrap(data, "profile", "info")

    # ================================================================== #
    # MAQUINAS
    # ================================================================== #
    def _paginate(self, path: str, per_page: int = 100, max_pages: int = 50) -> list[dict]:
        """Percorre endpoints paginados (formato {data, meta, links})."""
        out: list[dict] = []
        page = 1
        while page <= max_pages:
            data = self._get(path, page=page, per_page=per_page)
            chunk = self._unwrap(data, "data", "info")
            if isinstance(chunk, dict):  # alguns retornam dict de dicts
                chunk = list(chunk.values())
            if not chunk:
                break
            out.extend(chunk)
            # Descobre se ha proxima pagina pelo meta/links.
            meta = data.get("meta") if isinstance(data, dict) else None
            if meta and meta.get("current_page") and meta.get("last_page"):
                if meta["current_page"] >= meta["last_page"]:
                    break
            elif len(chunk) < per_page:
                break
            page += 1
        return out

    def machines_active(self) -> list[dict]:
        """Maquinas ativas (em jogo no momento, nao aposentadas)."""
        return self._paginate("/machine/paginated")

    def machines_retired(self) -> list[dict]:
        """Maquinas aposentadas (retired)."""
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
        """Maquina atualmente spawnada pelo usuario (ou None)."""
        data = self._get("/machine/active")
        info = self._unwrap(data, "info")
        return info if info else None

    def machine_owns_top(self, machine_id: int) -> list[dict]:
        """
        Top donos da maquina. Esse endpoint foi removido pela API em algumas
        regioes; se nao existir, degrada para lista vazia (os first bloods
        continuam disponiveis no proprio profile da maquina).
        """
        try:
            data = self._get(f"/machine/owns/top/{machine_id}")
            return self._unwrap(data, "info", "data") or []
        except HTBError:
            return []

    # --- Acoes de VM ------------------------------------------------- #
    def spawn(self, machine_id: int) -> dict[str, Any]:
        return self._post("/vm/spawn", {"machine_id": machine_id})

    def terminate(self, machine_id: int) -> dict[str, Any]:
        return self._post("/vm/terminate", {"machine_id": machine_id})

    def reset(self, machine_id: int) -> dict[str, Any]:
        return self._post("/vm/reset", {"machine_id": machine_id})

    def submit_machine_flag(self, machine_id: int, flag: str, difficulty: int) -> dict[str, Any]:
        # difficulty: 1..10 (10 = muito dificil), exigido pela API.
        return self._post(
            "/machine/own",
            {"flag": flag, "id": machine_id, "difficulty": difficulty},
        )

    def todo_machines(self) -> list[dict]:
        data = self._get("/machine/todo")
        return self._unwrap(data, "data", "info") or []

    # ================================================================== #
    # CHALLENGES  (inclui categorias como DFIR, Forensics, Pwn, etc.)
    # ================================================================== #
    def challenge_categories(self) -> list[dict]:
        data = self._get("/challenge/categories/list")
        return self._unwrap(data, "info", "data") or []

    def challenges(self, retired: bool = False) -> list[dict]:
        """
        Lista challenges. O HTB renomeou esse endpoint ao longo do tempo,
        entao tentamos o caminho novo e caimos para o antigo.
        """
        state = "retired" if retired else "active"
        # Caminho novo (paginado).
        try:
            items = self._paginate(f"/challenges?state={state}")
            if items:
                return items
        except HTBError:
            pass
        # Fallback: endpoint legado.
        legacy = "/challenge/list/retired" if retired else "/challenge/list"
        data = self._get(legacy)
        return self._unwrap(data, "challenges", "info", "data") or []

    def challenge_info(self, challenge_id: int) -> dict[str, Any]:
        data = self._get(f"/challenge/info/{challenge_id}")
        return self._unwrap(data, "challenge", "info", "data")

    def challenge_start(self, challenge_id: int) -> dict[str, Any]:
        """Sobe o container de um challenge (quando aplicavel)."""
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
        """Hall of Fame mundial (top 100 usuarios)."""
        data = self._get("/rankings/users")
        return self._unwrap(data, "data", "info") or []

    def ranking_country(self, country_code: str) -> list[dict]:
        data = self._get(f"/rankings/country/{country_code.upper()}/members")
        # Formato: {"data": {"country_name": ..., "rankings": [...]}}
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
    # SHERLOCKS  (DFIR / investigacoes blue team)
    # ================================================================== #
    def sherlocks(self) -> list[dict]:
        """Lista as Sherlocks - os desafios de DFIR do HTB."""
        return self._paginate("/sherlocks")

    def sherlock_info(self, sherlock_id: int) -> dict[str, Any]:
        data = self._get(f"/sherlocks/{sherlock_id}/info")
        return self._unwrap(data, "data", "info")

    def sherlock_download(self, sherlock_id: int) -> dict[str, Any]:
        """Retorna o link de download dos artefatos da Sherlock."""
        data = self._get(f"/sherlocks/{sherlock_id}/download_link")
        return self._unwrap(data, "data", "info") or data
