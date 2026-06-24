"""
cli.py
======

Interface de linha de comando da caphtb, construida com Typer.

Grupos de comandos:
  login / whoami / config   -> autenticacao e perfil
  machines / machine        -> listagem e detalhe de maquinas
  spawn / stop / reset      -> ciclo de vida da VM
  bloods / watch            -> first bloods e acompanhamento ao vivo
  submit                    -> envio de flag
  challenges / challenge    -> challenges (inclui DFIR, Forensics, etc.)
  categories                -> categorias de challenge
  ranking                   -> ranking mundial / pais / time / universidade

Rode `caphtb --help` ou `caphtb <comando> --help` para ver tudo.
"""

from __future__ import annotations

import time
from typing import Optional

import typer
from rich.live import Live

from . import __version__, ui
from .api import HTBClient, HTBError
from .config import Config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="caphtb - CLI bonita para a API do Hack The Box.",
    rich_markup_mode="rich",
)


# ---------------------------------------------------------------------- #
# Infra: obter cliente autenticado
# ---------------------------------------------------------------------- #
def get_client() -> HTBClient:
    cfg = Config.load()
    try:
        client = HTBClient(cfg)
    except HTBError as exc:
        ui.err(str(exc))
        raise typer.Exit(code=1)
    # Aviso preventivo se o token estiver perto de expirar.
    days = cfg.token_expires_in_days()
    if days is not None and days < 7:
        ui.warn(f"Seu token expira em {days:.1f} dias. Gere outro em app.hackthebox.com.")
    return client


def guard(fn):
    """Executa uma funcao tratando HTBError de forma amigavel."""
    try:
        return fn()
    except HTBError as exc:
        ui.err(str(exc))
        raise typer.Exit(code=1)


def resolve_machine_id(client: HTBClient, ident: str) -> tuple[int, dict]:
    """Aceita id numerico ou nome e devolve (id, perfil)."""
    prof = guard(lambda: client.machine_profile(ident))
    return int(prof.get("id")), prof


# ---------------------------------------------------------------------- #
# AUTENTICACAO / PERFIL
# ---------------------------------------------------------------------- #
@app.command()
def login(
    token: Optional[str] = typer.Option(None, "--token", "-t", help="App Token do HTB."),
):
    """Salva seu App Token (gerado em app.hackthebox.com/profile/settings)."""
    cfg = Config.load()
    if not token:
        token = typer.prompt("Cole seu HTB App Token", hide_input=True)
    cfg.token = token.strip()
    cfg.save()

    # Valida buscando o proprio perfil.
    try:
        client = HTBClient(cfg)
        prof = client.self_profile()
        ui.ok(f"Autenticado como [head]{prof.get('name', '?')}[/head] (id {cfg.user_id}).")
    except HTBError as exc:
        ui.err(f"Token salvo, mas a validacao falhou: {exc}")
        raise typer.Exit(code=1)


@app.command()
def whoami():
    """Mostra o seu perfil: rank, pontos, owns e time."""
    client = get_client()
    prof = guard(client.self_profile)
    ui.banner()
    ui.console.print(_self_panel(prof))


def _self_panel(p: dict):
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append(f"{p.get('name', '-')}\n", style="head")
    body.append("Rank global:   ", style="muted"); body.append(f"#{p.get('ranking', '-')}\n")
    body.append("Rank/Nivel:    ", style="muted"); body.append(f"{p.get('rank', '-')}\n")
    body.append("Pontos:        ", style="muted"); body.append(f"{p.get('points', '-')}\n")
    body.append("User owns:     ", style="muted"); body.append(f"{p.get('user_owns', '-')}\n")
    body.append("System owns:   ", style="muted"); body.append(f"{p.get('system_owns', '-')}\n")
    team = p.get("team") or {}
    body.append("Time:          ", style="muted"); body.append(f"{team.get('name', '-')}\n")
    country = p.get("country_name") or p.get("country") or "-"
    body.append("Pais:          ", style="muted"); body.append(f"{country}")
    return Panel(body, border_style=ui.HTB_GREEN, title="Perfil", title_align="left")


@app.command()
def config():
    """Mostra a configuracao atual (sem revelar o token)."""
    cfg = Config.load()
    ui.info(f"Base URL:  {cfg.base_url}")
    ui.info(f"Pais:      {cfg.country}")
    ui.info(f"Time id:   {cfg.team_id or '-'}")
    ui.info(f"Token:     {'configurado' if cfg.has_token else 'AUSENTE'}")
    days = cfg.token_expires_in_days()
    if days is not None:
        ui.info(f"Expira em: {days:.1f} dias")


# ---------------------------------------------------------------------- #
# MAQUINAS
# ---------------------------------------------------------------------- #
@app.command()
def machines(
    retired: bool = typer.Option(False, "--retired", "-r", help="Lista maquinas aposentadas."),
    os_filter: Optional[str] = typer.Option(None, "--os", help="Filtra por OS (linux/windows)."),
    difficulty: Optional[str] = typer.Option(None, "--difficulty", "-d", help="easy/medium/hard/insane."),
    todo: bool = typer.Option(False, "--todo", help="So as da sua lista de to-do."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Filtra pelo nome."),
    limit: int = typer.Option(40, "--limit", "-n", help="Quantidade maxima exibida."),
):
    """Lista maquinas ativas (ou aposentadas com --retired), com filtros."""
    client = get_client()
    data = guard(client.machines_retired if retired else client.machines_active)

    if todo:
        data = [m for m in data if m.get("isTodo")]
    if os_filter:
        data = [m for m in data if os_filter.lower() in (m.get("os") or "").lower()]
    if difficulty:
        data = [m for m in data if difficulty.lower() in (m.get("difficultyText") or "").lower()]
    if search:
        data = [m for m in data if search.lower() in (m.get("name") or "").lower()]

    title = f"Maquinas {'aposentadas' if retired else 'ativas'} ({len(data)})"
    ui.console.print(ui.machines_table(data[:limit], title))


@app.command()
def machine(ident: str = typer.Argument(..., help="ID ou nome da maquina.")):
    """Detalhes completos de uma maquina."""
    client = get_client()
    prof = guard(lambda: client.machine_profile(ident))
    ui.console.print(ui.machine_panel(prof))


@app.command(name="active")
def active_machine():
    """Mostra a maquina que voce tem spawnada agora."""
    client = get_client()
    info = guard(client.machine_active)
    if not info:
        ui.warn("Nenhuma maquina spawnada no momento.")
        raise typer.Exit()
    ui.ok(f"Spawnada: [head]{info.get('name')}[/head]  IP: [head]{info.get('ip', '-')}[/head]")


@app.command()
def startingpoint(tier: int = typer.Argument(1, help="Tier do Starting Point (1, 2 ou 3).")):
    """Lista as maquinas do Starting Point por tier."""
    client = get_client()
    data = guard(lambda: client.starting_point(tier))
    ui.console.print(ui.machines_table(data, f"Starting Point - Tier {tier}"))


# ---------------------------------------------------------------------- #
# CICLO DE VIDA DA VM
# ---------------------------------------------------------------------- #
@app.command()
def spawn(ident: str = typer.Argument(..., help="ID ou nome da maquina a iniciar.")):
    """Inicia (spawn) uma maquina."""
    client = get_client()
    mid, prof = resolve_machine_id(client, ident)
    res = guard(lambda: client.spawn(mid))
    ui.ok(res.get("message", f"Maquina {prof.get('name')} iniciada."))
    ui.info("Aguarde alguns segundos e rode 'caphtb active' para ver o IP.")


@app.command()
def stop(ident: Optional[str] = typer.Argument(None, help="ID/nome. Vazio = maquina ativa.")):
    """Desativa (termina) uma maquina. Sem argumento, termina a ativa."""
    client = get_client()
    if ident:
        mid, _ = resolve_machine_id(client, ident)
    else:
        info = guard(client.machine_active)
        if not info:
            ui.warn("Nenhuma maquina ativa para desativar.")
            raise typer.Exit()
        mid = int(info.get("id"))
    res = guard(lambda: client.terminate(mid))
    ui.ok(res.get("message", "Maquina desativada."))


@app.command()
def reset(ident: str = typer.Argument(..., help="ID ou nome da maquina.")):
    """Reseta a instancia de uma maquina."""
    client = get_client()
    mid, _ = resolve_machine_id(client, ident)
    res = guard(lambda: client.reset(mid))
    ui.ok(res.get("message", "Maquina resetada."))


@app.command()
def submit(
    ident: str = typer.Argument(..., help="ID ou nome da maquina."),
    flag: str = typer.Argument(..., help="A flag (user ou root)."),
    difficulty: int = typer.Option(5, "--difficulty", "-d", min=1, max=10, help="Dificuldade 1-10."),
):
    """Envia uma flag de maquina."""
    client = get_client()
    mid, _ = resolve_machine_id(client, ident)
    res = guard(lambda: client.submit_machine_flag(mid, flag, difficulty))
    ui.ok(res.get("message", "Flag enviada."))


# ---------------------------------------------------------------------- #
# BLOODS / WATCH AO VIVO
# ---------------------------------------------------------------------- #
@app.command()
def bloods(ident: str = typer.Argument(..., help="ID ou nome da maquina.")):
    """Mostra os first bloods (user/root) e contadores de owns."""
    client = get_client()
    prof = guard(lambda: client.machine_profile(ident))
    ui.console.print(ui.bloods_panel(prof))


@app.command()
def watch(
    ident: str = typer.Argument(..., help="ID ou nome da maquina ativa."),
    interval: int = typer.Option(20, "--interval", "-i", min=5, help="Segundos entre atualizacoes."),
):
    """
    Acompanha AO VIVO os owns/bloods de uma maquina ativa.

    Ideal para maquinas recem-lancadas: a tela atualiza sozinha e avisa
    no terminal assim que o first blood (user/root) e capturado.
    """
    client = get_client()
    mid, _ = resolve_machine_id(client, ident)

    last_user_blood = None
    last_root_blood = None
    ui.info(f"Monitorando a cada {interval}s. Ctrl+C para sair.")
    try:
        with Live(console=ui.console, refresh_per_second=4, screen=False) as live:
            while True:
                prof = client.machine_profile(mid)

                ub = (prof.get("userBlood") or {}).get("user", {}).get("name")
                rb = (prof.get("rootBlood") or {}).get("user", {}).get("name")

                # Notifica mudancas de blood (uma vez).
                if ub and ub != last_user_blood:
                    last_user_blood = ub
                    ui.console.bell()
                    ui.console.print(f"[blood]>>> USER BLOOD: {ub}[/blood]")
                if rb and rb != last_root_blood:
                    last_root_blood = rb
                    ui.console.bell()
                    ui.console.print(f"[blood]>>> ROOT BLOOD: {rb}[/blood]")

                live.update(ui.bloods_panel(prof))
                time.sleep(interval)
    except KeyboardInterrupt:
        ui.info("Monitoramento encerrado.")


# ---------------------------------------------------------------------- #
# CHALLENGES
# ---------------------------------------------------------------------- #
@app.command()
def challenges(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Categoria (ex.: DFIR, Pwn)."),
    difficulty: Optional[str] = typer.Option(None, "--difficulty", "-d", help="easy/medium/hard/insane."),
    retired: bool = typer.Option(False, "--retired", "-r", help="Lista challenges aposentados."),
    todo: bool = typer.Option(False, "--todo", help="So os ainda nao resolvidos."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Filtra pelo nome."),
    limit: int = typer.Option(40, "--limit", "-n", help="Quantidade maxima exibida."),
):
    """Lista challenges com filtros (categoria, dificuldade, etc.)."""
    client = get_client()
    data = guard(lambda: client.challenges(retired=retired))

    if category:
        data = [c for c in data if category.lower() in str(c.get("category_name") or c.get("category") or "").lower()]
    if difficulty:
        data = [c for c in data if difficulty.lower() in (c.get("difficulty") or "").lower()]
    if todo:
        data = [c for c in data if not (c.get("authUserSolve") or c.get("isCompleted") or c.get("solved"))]
    if search:
        data = [c for c in data if search.lower() in (c.get("name") or "").lower()]

    ui.console.print(ui.challenges_table(data[:limit], f"Challenges ({len(data)})"))


@app.command()
def dfir(
    difficulty: Optional[str] = typer.Option(None, "--difficulty", "-d", help="easy/medium/hard/insane."),
    todo: bool = typer.Option(False, "--todo", help="So as ainda nao resolvidas."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Filtra pelo nome."),
    limit: int = typer.Option(40, "--limit", "-n"),
):
    """Lista as Sherlocks (os desafios de DFIR / blue team do HTB)."""
    client = get_client()
    data = guard(client.sherlocks)
    if difficulty:
        data = [s for s in data if difficulty.lower() in (s.get("difficulty") or "").lower()]
    if todo:
        data = [s for s in data if not s.get("is_owned")]
    if search:
        data = [s for s in data if search.lower() in (s.get("name") or "").lower()]
    ui.console.print(ui.sherlocks_table(data[:limit], f"Sherlocks - DFIR ({len(data)})"))


@app.command()
def sherlock(sid: int = typer.Argument(..., help="ID da Sherlock.")):
    """Detalhes de uma Sherlock (DFIR)."""
    client = get_client()
    s = guard(lambda: client.sherlock_info(sid))
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append(f"{s.get('name', '-')}\n", style="head")
    body.append("Categoria:    ", style="muted"); body.append(f"{s.get('category_name', 'DFIR')}\n")
    body.append("Dificuldade:  ", style="muted"); body.append_text(ui.diff_cell(s.get("difficulty"))); body.append("\n")
    body.append("Solves:       ", style="muted"); body.append(f"{s.get('solves', '-')}\n")
    body.append("Rating:       ", style="muted"); body.append(f"{s.get('rating', '-')}\n")
    body.append("Resolvida:    ", style="muted"); body.append_text(ui.yesno(s.get("is_owned"))); body.append("\n")
    desc = s.get("description") or s.get("scenario") or ""
    if desc:
        body.append("\n"); body.append(desc, style="muted")
    ui.console.print(Panel(body, border_style=ui.HTB_GREEN, title="Sherlock", title_align="left"))


@app.command()
def categories():
    """Lista as categorias de challenge disponiveis (DFIR, Pwn, Web, etc.)."""
    client = get_client()
    cats = guard(client.challenge_categories)
    from rich.columns import Columns

    items = [f"[head]{c.get('id')}[/head] {c.get('name')}" for c in cats]
    ui.console.print(Columns(items, equal=True, expand=False, title="Categorias"))


@app.command()
def challenge(cid: int = typer.Argument(..., help="ID do challenge.")):
    """Detalhes de um challenge."""
    client = get_client()
    c = guard(lambda: client.challenge_info(cid))
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append(f"{c.get('name', '-')}\n", style="head")
    body.append("Categoria:    ", style="muted"); body.append(f"{c.get('category_name', c.get('category', '-'))}\n")
    body.append("Dificuldade:  ", style="muted"); body.append_text(ui.diff_cell(c.get("difficulty"))); body.append("\n")
    body.append("Pontos:       ", style="muted"); body.append(f"{c.get('points', '-')}\n")
    body.append("Solves:       ", style="muted"); body.append(f"{c.get('solves', '-')}\n")
    body.append("Resolvido:    ", style="muted"); body.append_text(ui.yesno(c.get("authUserSolve") or c.get("solved"))); body.append("\n")
    desc = c.get("description") or ""
    if desc:
        body.append("\n", style="muted"); body.append(desc, style="muted")
    ui.console.print(Panel(body, border_style=ui.HTB_GREEN, title="Challenge", title_align="left"))


@app.command(name="challenge-submit")
def challenge_submit(
    cid: int = typer.Argument(..., help="ID do challenge."),
    flag: str = typer.Argument(..., help="A flag."),
    difficulty: int = typer.Option(5, "--difficulty", "-d", min=1, max=10),
):
    """Envia a flag de um challenge."""
    client = get_client()
    res = guard(lambda: client.submit_challenge_flag(cid, flag, difficulty))
    ui.ok(res.get("message", "Flag enviada."))


# ---------------------------------------------------------------------- #
# RANKING
# ---------------------------------------------------------------------- #
@app.command()
def ranking(
    scope: str = typer.Argument("world", help="world | country | team | uni"),
    country: Optional[str] = typer.Option(None, "--country", help="Codigo do pais (ex.: BR)."),
    limit: int = typer.Option(25, "--limit", "-n", help="Quantos exibir."),
):
    """
    Mostra ranking: mundial (world), por pais (country), times (team)
    ou universidades (uni).
    """
    client = get_client()
    cfg = Config.load()

    if scope == "world":
        rows = guard(client.ranking_world)
        title = "Ranking Mundial"
    elif scope == "country":
        code = (country or cfg.country or "BR").upper()
        rows = guard(lambda: client.ranking_country(code))
        title = f"Ranking - {code}"
    elif scope == "team":
        rows = guard(client.ranking_teams)
        title = "Ranking de Times"
    elif scope in ("uni", "university", "universities"):
        rows = guard(client.ranking_universities)
        title = "Ranking de Universidades"
    else:
        ui.err("scope invalido. Use: world | country | team | uni")
        raise typer.Exit(code=1)

    ui.console.print(ui.ranking_table(rows[:limit], title))


# ---------------------------------------------------------------------- #
# VERSAO
# ---------------------------------------------------------------------- #
@app.command()
def version():
    """Mostra a versao da caphtb."""
    ui.console.print(f"caphtb [head]v{__version__}[/head]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
