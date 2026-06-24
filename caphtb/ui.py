"""
ui.py
=====

Camada de apresentacao construida sobre a biblioteca `rich`.

Concentra TODO o visual da ferramenta aqui para manter o cli.py limpo:
  - tema de cores (verde HTB #9FEF00 sobre fundo escuro);
  - banner ASCII;
  - tabelas de maquinas / challenges / ranking;
  - paineis de detalhe e de bloods.

Sem emojis (preferencia do projeto): usamos cor, negrito e caracteres de
caixa do proprio rich para o visual "industrial".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Paleta inspirada no Hack The Box.
HTB_GREEN = "#9FEF00"
HTB_DIM = "#5c6c0a"
HTB_BG = "#111927"

THEME = Theme(
    {
        "htb": HTB_GREEN,
        "ok": "bold green",
        "err": "bold red",
        "warn": "bold yellow",
        "muted": "grey58",
        "head": f"bold {HTB_GREEN}",
        "easy": "bright_green",
        "medium": "yellow",
        "hard": "red",
        "insane": "magenta",
        "blood": "bold red",
    }
)

console = Console(theme=THEME, highlight=False)

# Logo ASCII (industrial, sem emoji).
BANNER = r"""
  ___ __ _ _ __ | |__ | |_| |__
 / __/ _` | '_ \| '_ \| __| '_ \
| (_| (_| | |_) | | | | |_| |_) |
 \___\__,_| .__/|_| |_|\__|_.__/
          |_|   hack the box cli
"""


# ---------------------------------------------------------------------- #
# Helpers de saida simples
# ---------------------------------------------------------------------- #
def banner() -> None:
    console.print(Text(BANNER, style="head"))


def ok(msg: str) -> None:
    console.print(f"[ok][+][/ok] {msg}")


def err(msg: str) -> None:
    console.print(f"[err][!][/err] {msg}")


def warn(msg: str) -> None:
    console.print(f"[warn][~][/warn] {msg}")


def info(msg: str) -> None:
    console.print(f"[htb][*][/htb] {msg}")


# ---------------------------------------------------------------------- #
# Formatadores
# ---------------------------------------------------------------------- #
def difficulty_style(text: Optional[str]) -> str:
    """Mapeia o texto de dificuldade para um estilo de cor."""
    t = (text or "").lower()
    if "easy" in t:
        return "easy"
    if "medium" in t:
        return "medium"
    if "insane" in t:
        return "insane"
    if "hard" in t:
        return "hard"
    return "muted"


def diff_cell(text: Optional[str]) -> Text:
    return Text(text or "-", style=difficulty_style(text))


def os_short(os_name: Optional[str]) -> str:
    o = (os_name or "").lower()
    if "linux" in o:
        return "Linux"
    if "windows" in o:
        return "Windows"
    if "freebsd" in o:
        return "FreeBSD"
    if "android" in o:
        return "Android"
    return os_name or "-"


def yesno(value: Any) -> Text:
    return Text("sim", style="ok") if value else Text("nao", style="muted")


def fmt_dt(value: Optional[str]) -> str:
    """Formata uma data ISO do HTB para algo curto e legivel."""
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(value)[:16]


def ago(value: Optional[str]) -> str:
    """Tempo decorrido desde uma data ISO (ex.: '2h 13m')."""
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 0:
            return "0m"
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        if d:
            return f"{d}d {h}h"
        if h:
            return f"{h}h {m}m"
        return f"{m}m"
    except (ValueError, TypeError):
        return "-"


# ---------------------------------------------------------------------- #
# Tabelas
# ---------------------------------------------------------------------- #
def _base_table(title: str) -> Table:
    table = Table(
        title=title,
        title_style="head",
        header_style="head",
        border_style=HTB_DIM,
        expand=False,
        pad_edge=False,
    )
    return table


def machines_table(machines: list[dict], title: str = "Maquinas") -> Table:
    table = _base_table(title)
    table.add_column("ID", justify="right", style="muted")
    table.add_column("Nome", style="bold")
    table.add_column("OS")
    table.add_column("Dificuldade")
    table.add_column("Pts", justify="right")
    table.add_column("User", justify="right", style="muted")
    table.add_column("Root", justify="right", style="muted")
    table.add_column("Feito", justify="center")

    for m in machines:
        done = m.get("authUserInRootOwns") or m.get("authUserInUserOwns")
        table.add_row(
            str(m.get("id", "-")),
            m.get("name", "-"),
            os_short(m.get("os")),
            diff_cell(m.get("difficultyText") or m.get("difficulty")),
            str(m.get("points", m.get("static_points", "-"))),
            str(m.get("user_owns_count", "-")),
            str(m.get("root_owns_count", "-")),
            "x" if done else "",
        )
    return table


def challenges_table(challenges: list[dict], title: str = "Challenges") -> Table:
    table = _base_table(title)
    table.add_column("ID", justify="right", style="muted")
    table.add_column("Nome", style="bold")
    table.add_column("Categoria")
    table.add_column("Dificuldade")
    table.add_column("Pts", justify="right")
    table.add_column("Solves", justify="right", style="muted")
    table.add_column("Feito", justify="center")

    for c in challenges:
        cat = c.get("category_name") or c.get("category") or "-"
        done = c.get("authUserSolve") or c.get("isCompleted") or c.get("solved")
        table.add_row(
            str(c.get("id", "-")),
            c.get("name", "-"),
            str(cat),
            diff_cell(c.get("difficulty")),
            str(c.get("points", "-")),
            str(c.get("solves", "-")),
            "x" if done else "",
        )
    return table


def ranking_table(rows: list[dict], title: str) -> Table:
    table = _base_table(title)
    table.add_column("#", justify="right", style="head")
    table.add_column("Nome", style="bold")
    table.add_column("Rank", style="muted")
    table.add_column("Pontos", justify="right")
    table.add_column("Pais/Time", style="muted")

    for i, r in enumerate(rows, start=1):
        rank_pos = r.get("rank") or r.get("ranking") or i
        name = r.get("name") or r.get("username") or r.get("user_name") or "-"
        rank_name = r.get("level") or r.get("rank_name") or r.get("rankText") or ""
        points = r.get("points") or r.get("rankingPoints") or r.get("rank_points") or "-"
        extra = (
            (r.get("country") or {}).get("name")
            if isinstance(r.get("country"), dict)
            else r.get("country")
        ) or r.get("team") or ""
        table.add_row(str(rank_pos), str(name), str(rank_name), str(points), str(extra))
    return table


def sherlocks_table(items: list[dict], title: str = "Sherlocks (DFIR)") -> Table:
    table = _base_table(title)
    table.add_column("ID", justify="right", style="muted")
    table.add_column("Nome", style="bold")
    table.add_column("Categoria")
    table.add_column("Dificuldade")
    table.add_column("Solves", justify="right", style="muted")
    table.add_column("Rating", justify="right", style="muted")
    table.add_column("Feito", justify="center")

    for s in items:
        done = s.get("is_owned")
        table.add_row(
            str(s.get("id", "-")),
            s.get("name", "-"),
            str(s.get("category_name", "-")),
            diff_cell(s.get("difficulty")),
            str(s.get("solves", "-")),
            str(s.get("rating", "-")),
            "x" if done else "",
        )
    return table


# ---------------------------------------------------------------------- #
# Paineis de detalhe
# ---------------------------------------------------------------------- #
def machine_panel(m: dict) -> Panel:
    ub = m.get("userBlood") or m.get("user_blood") or {}
    rb = m.get("rootBlood") or m.get("root_blood") or {}
    blood_user = (ub.get("user") or {}).get("name") if ub else None
    blood_root = (rb.get("user") or {}).get("name") if rb else None

    body = Text()
    body.append(f"{m.get('name', '-')}", style="head")
    body.append(f"   #{m.get('id', '-')}\n", style="muted")
    body.append("OS:           ", style="muted"); body.append(f"{os_short(m.get('os'))}\n")
    body.append("Dificuldade:  ", style="muted"); body.append_text(diff_cell(m.get("difficultyText"))); body.append("\n")
    body.append("Pontos:       ", style="muted"); body.append(f"{m.get('points', '-')}\n")
    body.append("Rating:       ", style="muted"); body.append(f"{m.get('stars', '-')} estrelas\n")
    body.append("IP:           ", style="muted"); body.append(f"{m.get('ip') or 'nao spawnada'}\n")
    body.append("Lancamento:   ", style="muted"); body.append(f"{fmt_dt(m.get('release'))}\n")
    body.append("User owns:    ", style="muted"); body.append(f"{m.get('user_owns_count', '-')}\n")
    body.append("Root owns:    ", style="muted"); body.append(f"{m.get('root_owns_count', '-')}\n")
    body.append("User blood:   ", style="muted"); body.append(f"{blood_user or '-'}\n", style="blood" if blood_user else "muted")
    body.append("Root blood:   ", style="muted"); body.append(f"{blood_root or '-'}", style="blood" if blood_root else "muted")

    return Panel(body, border_style=HTB_GREEN, title="Maquina", title_align="left")


def bloods_panel(m: dict) -> Panel:
    """Painel com os first bloods (user/root) e contadores de owns."""
    ub = m.get("userBlood") or m.get("user_blood") or {}
    rb = m.get("rootBlood") or m.get("root_blood") or {}

    body = Text()
    body.append(f"{m.get('name', '-')}", style="head")
    body.append(f"   #{m.get('id', '-')}   ", style="muted")
    body.append(f"{m.get('difficultyText', '')}\n\n", style=difficulty_style(m.get("difficultyText")))

    body.append("FIRST BLOOD\n", style="blood")
    u_name = (ub.get("user") or {}).get("name")
    body.append("  User: ", style="muted")
    if u_name:
        body.append(f"{u_name} ", style="blood")
        body.append(f"em {ub.get('blood_difference', '?')}  ({fmt_dt(ub.get('created_at'))})\n", style="muted")
    else:
        body.append("ainda nao capturado\n", style="warn")

    r_name = (rb.get("user") or {}).get("name")
    body.append("  Root: ", style="muted")
    if r_name:
        body.append(f"{r_name} ", style="blood")
        body.append(f"em {rb.get('blood_difference', '?')}  ({fmt_dt(rb.get('created_at'))})\n", style="muted")
    else:
        body.append("ainda nao capturado\n", style="warn")

    body.append("\nOWNS\n", style="head")
    body.append("  User owns: ", style="muted"); body.append(f"{m.get('user_owns_count', '-')}\n")
    body.append("  Root owns: ", style="muted"); body.append(f"{m.get('root_owns_count', '-')}\n")
    body.append("  Voce:      ", style="muted")
    you_u = "user" if m.get("authUserInUserOwns") else None
    you_r = "root" if m.get("authUserInRootOwns") else None
    owned = " + ".join([x for x in (you_u, you_r) if x]) or "nenhum"
    body.append(f"{owned}\n", style="ok" if (you_u or you_r) else "muted")
    body.append("  Lancamento: ", style="muted"); body.append(f"{fmt_dt(m.get('release'))} ({ago(m.get('release'))} atras)")

    return Panel(body, border_style=HTB_GREEN, title="Bloods", title_align="left")
