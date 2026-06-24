"""
cli.py
======

Command-line interface of caphtb, built with Typer.

Command groups:
  login / whoami / config   -> authentication and profile
  machines / machine        -> machine listing and detail
  spawn / stop / reset      -> VM lifecycle
  bloods / watch            -> first bloods and live tracking
  submit                    -> flag submission
  challenges / challenge    -> challenges (Forensics, Pwn, etc.)
  categories                -> challenge categories
  dfir / sherlock           -> Sherlocks (HTB DFIR investigations)
  ranking                   -> world / country / team / university ranking

Run `caphtb --help` or `caphtb <command> --help` to see everything.
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
    help="caphtb - a pretty CLI for the Hack The Box API.",
    rich_markup_mode="rich",
)


# ---------------------------------------------------------------------- #
# Infra: get an authenticated client
# ---------------------------------------------------------------------- #
def get_client() -> HTBClient:
    cfg = Config.load()
    try:
        client = HTBClient(cfg)
    except HTBError as exc:
        ui.err(str(exc))
        raise typer.Exit(code=1)
    # Preemptive warning if the token is close to expiring.
    days = cfg.token_expires_in_days()
    if days is not None and days < 7:
        ui.warn(f"Your token expires in {days:.1f} days. Generate a new one at app.hackthebox.com.")
    return client


def guard(fn):
    """Run a function handling HTBError gracefully."""
    try:
        return fn()
    except HTBError as exc:
        ui.err(str(exc))
        raise typer.Exit(code=1)


def resolve_machine_id(client: HTBClient, ident: str) -> tuple[int, dict]:
    """Accept a numeric id or a name and return (id, profile)."""
    prof = guard(lambda: client.machine_profile(ident))
    return int(prof.get("id")), prof


# ---------------------------------------------------------------------- #
# AUTHENTICATION / PROFILE
# ---------------------------------------------------------------------- #
@app.command()
def login(
    token: Optional[str] = typer.Option(None, "--token", "-t", help="HTB App Token."),
):
    """Save your App Token (generated at app.hackthebox.com/profile/settings)."""
    cfg = Config.load()
    if not token:
        token = typer.prompt("Paste your HTB App Token", hide_input=True)
    cfg.token = token.strip()
    cfg.save()

    # Validate by fetching the own profile.
    try:
        client = HTBClient(cfg)
        prof = client.self_profile()
        ui.ok(f"Authenticated as [head]{prof.get('name', '?')}[/head] (id {cfg.user_id}).")
    except HTBError as exc:
        ui.err(f"Token saved, but validation failed: {exc}")
        raise typer.Exit(code=1)


@app.command()
def whoami():
    """Show your profile: rank, points, owns and team."""
    client = get_client()
    prof = guard(client.self_profile)
    ui.banner()
    ui.console.print(_self_panel(prof))


def _self_panel(p: dict):
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append(f"{p.get('name', '-')}\n", style="head")
    body.append("Global rank:   ", style="muted"); body.append(f"#{p.get('ranking', '-')}\n")
    body.append("Rank/Level:    ", style="muted"); body.append(f"{p.get('rank', '-')}\n")
    body.append("Points:        ", style="muted"); body.append(f"{p.get('points', '-')}\n")
    body.append("User owns:     ", style="muted"); body.append(f"{p.get('user_owns', '-')}\n")
    body.append("System owns:   ", style="muted"); body.append(f"{p.get('system_owns', '-')}\n")
    team = p.get("team") or {}
    body.append("Team:          ", style="muted"); body.append(f"{team.get('name', '-')}\n")
    country = p.get("country_name") or p.get("country") or "-"
    body.append("Country:       ", style="muted"); body.append(f"{country}")
    return Panel(body, border_style=ui.HTB_GREEN, title="Profile", title_align="left")


@app.command()
def config():
    """Show the current configuration (without revealing the token)."""
    cfg = Config.load()
    ui.info(f"Base URL:   {cfg.base_url}")
    ui.info(f"Country:    {cfg.country}")
    ui.info(f"Team id:    {cfg.team_id or '-'}")
    ui.info(f"Token:      {'configured' if cfg.has_token else 'MISSING'}")
    days = cfg.token_expires_in_days()
    if days is not None:
        ui.info(f"Expires in: {days:.1f} days")


# ---------------------------------------------------------------------- #
# MACHINES
# ---------------------------------------------------------------------- #
@app.command()
def machines(
    retired: bool = typer.Option(False, "--retired", "-r", help="List retired machines."),
    os_filter: Optional[str] = typer.Option(None, "--os", help="Filter by OS (linux/windows)."),
    difficulty: Optional[str] = typer.Option(None, "--difficulty", "-d", help="easy/medium/hard/insane."),
    todo: bool = typer.Option(False, "--todo", help="Only the ones in your to-do list."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Filter by name."),
    limit: int = typer.Option(40, "--limit", "-n", help="Maximum number shown."),
):
    """List active machines (or retired with --retired), with filters."""
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

    title = f"{'Retired' if retired else 'Active'} machines ({len(data)})"
    ui.console.print(ui.machines_table(data[:limit], title))


@app.command()
def machine(ident: str = typer.Argument(..., help="Machine ID or name.")):
    """Full details of a machine."""
    client = get_client()
    prof = guard(lambda: client.machine_profile(ident))
    ui.console.print(ui.machine_panel(prof))


@app.command(name="active")
def active_machine():
    """Show the machine you currently have spawned."""
    client = get_client()
    info = guard(client.machine_active)
    if not info:
        ui.warn("No machine spawned at the moment.")
        raise typer.Exit()
    ui.ok(f"Spawned: [head]{info.get('name')}[/head]  IP: [head]{info.get('ip', '-')}[/head]")


@app.command()
def startingpoint(tier: int = typer.Argument(1, help="Starting Point tier (1, 2 or 3).")):
    """List the Starting Point machines by tier."""
    client = get_client()
    data = guard(lambda: client.starting_point(tier))
    ui.console.print(ui.machines_table(data, f"Starting Point - Tier {tier}"))


# ---------------------------------------------------------------------- #
# VM LIFECYCLE
# ---------------------------------------------------------------------- #
@app.command()
def spawn(ident: str = typer.Argument(..., help="ID or name of the machine to start.")):
    """Start (spawn) a machine."""
    client = get_client()
    mid, prof = resolve_machine_id(client, ident)
    res = guard(lambda: client.spawn(mid))
    ui.ok(res.get("message", f"Machine {prof.get('name')} started."))
    ui.info("Wait a few seconds and run 'caphtb active' to see the IP.")


@app.command()
def stop(ident: Optional[str] = typer.Argument(None, help="ID/name. Empty = the active machine.")):
    """Stop (terminate) a machine. With no argument, stops the active one."""
    client = get_client()
    if ident:
        mid, _ = resolve_machine_id(client, ident)
    else:
        info = guard(client.machine_active)
        if not info:
            ui.warn("No active machine to stop.")
            raise typer.Exit()
        mid = int(info.get("id"))
    res = guard(lambda: client.terminate(mid))
    ui.ok(res.get("message", "Machine stopped."))


@app.command()
def reset(ident: str = typer.Argument(..., help="Machine ID or name.")):
    """Reset a machine instance."""
    client = get_client()
    mid, _ = resolve_machine_id(client, ident)
    res = guard(lambda: client.reset(mid))
    ui.ok(res.get("message", "Machine reset."))


@app.command()
def submit(
    ident: str = typer.Argument(..., help="Machine ID or name."),
    flag: str = typer.Argument(..., help="The flag (user or root)."),
    difficulty: int = typer.Option(5, "--difficulty", "-d", min=1, max=10, help="Difficulty 1-10."),
):
    """Submit a machine flag."""
    client = get_client()
    mid, _ = resolve_machine_id(client, ident)
    res = guard(lambda: client.submit_machine_flag(mid, flag, difficulty))
    ui.ok(res.get("message", "Flag submitted."))


# ---------------------------------------------------------------------- #
# BLOODS / LIVE WATCH
# ---------------------------------------------------------------------- #
@app.command()
def bloods(ident: str = typer.Argument(..., help="Machine ID or name.")):
    """Show the first bloods (user/root) and own counters."""
    client = get_client()
    prof = guard(lambda: client.machine_profile(ident))
    ui.console.print(ui.bloods_panel(prof))


@app.command()
def watch(
    ident: str = typer.Argument(..., help="ID or name of an active machine."),
    interval: int = typer.Option(20, "--interval", "-i", min=5, help="Seconds between refreshes."),
):
    """
    Track the owns/bloods of an active machine LIVE.

    Ideal for freshly released machines: the screen refreshes on its own and
    alerts you in the terminal the moment the first blood (user/root) is taken.
    """
    client = get_client()
    mid, _ = resolve_machine_id(client, ident)

    last_user_blood = None
    last_root_blood = None
    ui.info(f"Monitoring every {interval}s. Ctrl+C to quit.")
    try:
        with Live(console=ui.console, refresh_per_second=4, screen=False) as live:
            while True:
                prof = client.machine_profile(mid)

                ub = (prof.get("userBlood") or {}).get("user", {}).get("name")
                rb = (prof.get("rootBlood") or {}).get("user", {}).get("name")

                # Notify blood changes (once).
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
        ui.info("Monitoring stopped.")


# ---------------------------------------------------------------------- #
# CHALLENGES
# ---------------------------------------------------------------------- #
@app.command()
def challenges(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Category (e.g. Pwn, Web)."),
    difficulty: Optional[str] = typer.Option(None, "--difficulty", "-d", help="easy/medium/hard/insane."),
    retired: bool = typer.Option(False, "--retired", "-r", help="List retired challenges."),
    todo: bool = typer.Option(False, "--todo", help="Only the unsolved ones."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Filter by name."),
    limit: int = typer.Option(40, "--limit", "-n", help="Maximum number shown."),
):
    """List challenges with filters (category, difficulty, etc.)."""
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
    todo: bool = typer.Option(False, "--todo", help="Only the unsolved ones."),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Filter by name."),
    limit: int = typer.Option(40, "--limit", "-n"),
):
    """List the Sherlocks (HTB's DFIR / blue team challenges)."""
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
def sherlock(sid: int = typer.Argument(..., help="Sherlock ID.")):
    """Details of a Sherlock (DFIR)."""
    client = get_client()
    s = guard(lambda: client.sherlock_info(sid))
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append(f"{s.get('name', '-')}\n", style="head")
    body.append("Category:     ", style="muted"); body.append(f"{s.get('category_name', 'DFIR')}\n")
    body.append("Difficulty:   ", style="muted"); body.append_text(ui.diff_cell(s.get("difficulty"))); body.append("\n")
    body.append("Solves:       ", style="muted"); body.append(f"{s.get('solves', '-')}\n")
    body.append("Rating:       ", style="muted"); body.append(f"{s.get('rating', '-')}\n")
    body.append("Solved:       ", style="muted"); body.append_text(ui.yesno(s.get("is_owned"))); body.append("\n")
    desc = s.get("description") or s.get("scenario") or ""
    if desc:
        body.append("\n"); body.append(desc, style="muted")
    ui.console.print(Panel(body, border_style=ui.HTB_GREEN, title="Sherlock", title_align="left"))


@app.command()
def categories():
    """List the available challenge categories (Forensics, Pwn, Web, etc.)."""
    client = get_client()
    cats = guard(client.challenge_categories)
    from rich.columns import Columns

    items = [f"[head]{c.get('id')}[/head] {c.get('name')}" for c in cats]
    ui.console.print(Columns(items, equal=True, expand=False, title="Categories"))


@app.command()
def challenge(cid: int = typer.Argument(..., help="Challenge ID.")):
    """Details of a challenge."""
    client = get_client()
    c = guard(lambda: client.challenge_info(cid))
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append(f"{c.get('name', '-')}\n", style="head")
    body.append("Category:     ", style="muted"); body.append(f"{c.get('category_name', c.get('category', '-'))}\n")
    body.append("Difficulty:   ", style="muted"); body.append_text(ui.diff_cell(c.get("difficulty"))); body.append("\n")
    body.append("Points:       ", style="muted"); body.append(f"{c.get('points', '-')}\n")
    body.append("Solves:       ", style="muted"); body.append(f"{c.get('solves', '-')}\n")
    body.append("Solved:       ", style="muted"); body.append_text(ui.yesno(c.get("authUserSolve") or c.get("solved"))); body.append("\n")
    desc = c.get("description") or ""
    if desc:
        body.append("\n", style="muted"); body.append(desc, style="muted")
    ui.console.print(Panel(body, border_style=ui.HTB_GREEN, title="Challenge", title_align="left"))


@app.command(name="challenge-submit")
def challenge_submit(
    cid: int = typer.Argument(..., help="Challenge ID."),
    flag: str = typer.Argument(..., help="The flag."),
    difficulty: int = typer.Option(5, "--difficulty", "-d", min=1, max=10),
):
    """Submit a challenge flag."""
    client = get_client()
    res = guard(lambda: client.submit_challenge_flag(cid, flag, difficulty))
    ui.ok(res.get("message", "Flag submitted."))


# ---------------------------------------------------------------------- #
# RANKING
# ---------------------------------------------------------------------- #
@app.command()
def ranking(
    scope: str = typer.Argument("world", help="world | country | team | uni"),
    country: Optional[str] = typer.Option(None, "--country", help="Country code (e.g. BR)."),
    limit: int = typer.Option(25, "--limit", "-n", help="How many to show."),
):
    """
    Show ranking: worldwide (world), by country (country), teams (team)
    or universities (uni).
    """
    client = get_client()
    cfg = Config.load()

    # Passing --country implies the country scope, so `ranking --country BR`
    # works without having to also type the positional "country" argument.
    if country and scope == "world":
        scope = "country"

    if scope == "world":
        rows = guard(client.ranking_world)
        title = "World Ranking"
    elif scope == "country":
        code = (country or cfg.country or "BR").upper()
        rows = guard(lambda: client.ranking_country(code))
        title = f"Ranking - {code}"
    elif scope == "team":
        rows = guard(client.ranking_teams)
        title = "Team Ranking"
    elif scope in ("uni", "university", "universities"):
        rows = guard(client.ranking_universities)
        title = "University Ranking"
    else:
        ui.err("invalid scope. Use: world | country | team | uni")
        raise typer.Exit(code=1)

    ui.console.print(ui.ranking_table(rows[:limit], title))


# ---------------------------------------------------------------------- #
# VERSION
# ---------------------------------------------------------------------- #
@app.command()
def version():
    """Show the caphtb version."""
    ui.console.print(f"caphtb [head]v{__version__}[/head]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
