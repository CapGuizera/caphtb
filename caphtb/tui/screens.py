"""Screens and interaction logic for caphtb Textual TUI."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from rich.text import Text
from textual import events, on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Input, ListView, Static

from ..api import HTBClient, HTBError
from ..config import Config
from .widgets import ContextHelp, DetailPane, FilterEntry, FilterPanel, Sidebar

# Same difficulty palette as the Rich CLI (caphtb/ui.py), reused here so
# machines/challenges/sherlocks read consistently in both interfaces.
_DIFFICULTY_STYLES = {
    "easy": "bright_green",
    "medium": "yellow",
    "hard": "red",
    "insane": "magenta",
}


def _diff_cell(text: Any) -> Text:
    style = _DIFFICULTY_STYLES.get(str(text).strip().lower())
    return Text(str(text), style=style or "")


def _done_cell(done: bool, accent: str) -> Text:
    return Text("yes", style=f"bold {accent}") if done else Text("-", style="dim")


def _rating_cell(value: Any) -> Text:
    text = str(value) if value not in (None, "", "-") else None
    if text is None:
        return Text("-", style="dim")
    return Text(f"★ {text}", style="#E3B341")


def _rank_cell(value: Any, is_self: bool, accent: str) -> Text:
    return Text(str(value), style=f"bold {accent}" if is_self else "")


class ShutdownInProgress(Exception):
    """Internal sentinel used to abort background work on app exit."""


@dataclass
class FilterSpec:
    key: str
    label: str
    options: list[str]


class SearchModal(ModalScreen[Optional[str]]):
    """Small modal to capture '/' search text."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar")]

    def __init__(self, initial: str = "") -> None:
        super().__init__()
        self.initial = initial

    def compose(self):
        with Vertical(id="search-modal"):
            yield Static("Filtro de busca (vazio limpa):", classes="search-title")
            yield Input(value=self.initial, placeholder="Digite para filtrar...", id="search-input")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#search-input")
    def _submit_search(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())


class ConfirmModal(ModalScreen[bool]):
    """Simple yes/no modal for destructive actions."""

    BINDINGS = [
        Binding("y,enter", "confirm", "Confirmar"),
        Binding("n,escape", "cancel", "Cancelar"),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title = title
        self.body = body

    def compose(self):
        with Vertical(id="confirm-modal"):
            yield Static(self.title, classes="search-title")
            yield Static(self.body)
            yield Static("Y/Enter confirma | N/Esc cancela", id="modal-help")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class FlagSubmitModal(ModalScreen[Optional[tuple[str, int]]]):
    """Modal for flag + difficulty collection."""

    BINDINGS = [Binding("escape", "cancel", "Cancelar"), Binding("enter", "submit", "Enviar")]

    def __init__(self, target_kind: str, target_name: str) -> None:
        super().__init__()
        self.target_kind = target_kind
        self.target_name = target_name

    def compose(self):
        with Vertical(id="flag-modal"):
            yield Static(f"Submit {self.target_kind}: {self.target_name}", classes="search-title")
            yield Input(placeholder="Flag (ex: HTB{...})", id="flag-input")
            yield Input(value="5", placeholder="Difficulty 1-10", id="difficulty-input")
            yield Static("Enter envia | Esc cancela", id="modal-help")
            yield Static("", id="modal-error")

    def on_mount(self) -> None:
        self.query_one("#flag-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#flag-input")
    def _on_flag_submitted(self, _event: Input.Submitted) -> None:
        self.query_one("#difficulty-input", Input).focus()

    @on(Input.Submitted, "#difficulty-input")
    def _on_diff_submitted(self, _event: Input.Submitted) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        flag = self.query_one("#flag-input", Input).value.strip()
        difficulty_raw = self.query_one("#difficulty-input", Input).value.strip()
        if not flag:
            self.query_one("#modal-error", Static).update("Flag não pode ser vazia.")
            return
        try:
            difficulty = int(difficulty_raw)
        except ValueError:
            self.query_one("#modal-error", Static).update("Dificuldade deve ser número de 1 a 10.")
            return
        if difficulty < 1 or difficulty > 10:
            self.query_one("#modal-error", Static).update("Dificuldade deve ficar entre 1 e 10.")
            return
        self.dismiss((flag, difficulty))


class DashboardScreen(Screen):
    """Main full-screen dashboard with sidebar, table and details."""

    BINDINGS = [
        Binding("q", "quit", "Sair"),
        Binding("tab", "focus_next", "Próximo painel"),
        Binding("shift+tab", "focus_previous", "Painel anterior"),
        Binding("/", "search", "Busca"),
        Binding("enter", "open_detail", "Detalhe"),
        Binding("escape", "close_detail", "Fechar detalhe"),
        Binding("s", "spawn_machine", "Spawn"),
        Binding("x", "stop_machine", "Stop"),
        Binding("r", "reset_machine", "Reset"),
        Binding("f", "submit_flag", "Submit flag"),
        Binding("t", "cycle_theme", "Tema"),
        Binding("up,k", "move_up", show=False),
        Binding("down,j", "move_down", show=False),
        Binding("left,h", "move_left", show=False),
        Binding("right,l", "move_right", show=False),
    ]

    def __init__(self, client: HTBClient, cfg: Config) -> None:
        super().__init__()
        self.client = client
        self.cfg = cfg
        self.current_section = "machines"
        self.raw_data: dict[str, Any] = {}
        self.table_rows: list[dict[str, Any]] = []
        self.search_text: dict[str, str] = {
            "machines": "",
            "challenges": "",
            "sherlocks": "",
        }
        self.filters: dict[str, dict[str, str]] = {
            "machines": {
                "retired": "all",
                "os": "all",
                "difficulty": "all",
                "status": "all",
                "sort": "default",
            },
            "challenges": {
                "retired": "active",
                "difficulty": "all",
                "status": "all",
                "category": "all",
            },
            "sherlocks": {
                "state": "all",
                "difficulty": "all",
                "status": "all",
            },
            "ranking": {
                "scope": "world",
            },
        }
        self.last_blood_user: str | None = None
        self.last_blood_root: str | None = None
        self.watch_loop_enabled = False
        self.is_closing = False
        self.detail_locked = False
        self.loading_active = False
        self.loading_target = "boot"
        self.loading_frame = 0
        self.loading_timer = None

    def compose(self):
        with Horizontal(id="app-header"):
            yield Static("caphtb", id="header-title")
            yield Static("", id="header-user")
        with Horizontal(id="body"):
            yield Sidebar(id="sidebar")
            with Vertical(id="main"):
                yield FilterPanel(id="filters")
                yield Static("", id="loading-panel", classes="hidden")
                yield DataTable(id="data-table")
                yield Static("", id="status-line")
            yield DetailPane(id="detail-pane")
        yield ContextHelp(id="context-help")

    def on_mount(self) -> None:
        table = self.query_one("#data-table", DataTable)
        table.cursor_type = "row"
        table.cell_padding = 2
        self._configure_table_columns()
        self.query_one(Sidebar).set_section("machines")
        self._show_status("Carregando dados iniciais...")
        self._set_loading(True, "boot")
        self.loading_timer = self.set_interval(0.15, self._tick_loading)
        self.load_profile_header()
        self.load_section_data("machines")
        self.focus_on_sidebar()

    def on_unmount(self) -> None:
        self._begin_shutdown()
        if self.loading_timer is not None:
            self.loading_timer.stop()

    # ------------------------------------------------------------------ #
    # Focus helpers / navigation bindings
    # ------------------------------------------------------------------ #
    def focus_on_sidebar(self) -> None:
        self.query_one("#sections-list", ListView).focus()
        self.query_one(ContextHelp).set_context("Selecione seção | Enter/Setas/hjkl para navegar | Tab alterna painéis")

    def action_focus_next(self) -> None:
        self.focus_next()
        self._update_context_for_focus()

    def action_focus_previous(self) -> None:
        self.focus_previous()
        self._update_context_for_focus()

    def action_move_up(self) -> None:
        self._dispatch_move("up")

    def action_move_down(self) -> None:
        self._dispatch_move("down")

    def action_move_left(self) -> None:
        self._dispatch_move("left")

    def action_move_right(self) -> None:
        self._dispatch_move("right")

    def _dispatch_move(self, direction: str) -> None:
        focused = self.app.focused
        if isinstance(focused, DataTable):
            if direction == "up":
                focused.action_cursor_up()
            elif direction == "down":
                focused.action_cursor_down()
            elif direction == "left":
                focused.action_cursor_left()
            elif direction == "right":
                focused.action_cursor_right()
            self._preview_selected_row_detail()
            return
        if isinstance(focused, ListView):
            if direction in {"up", "left"}:
                focused.action_cursor_up()
            else:
                focused.action_cursor_down()
            return
        if direction == "left":
            self.focus_previous()
        elif direction == "right":
            self.focus_next()
        self._update_context_for_focus()

    def action_quit(self) -> None:
        self._begin_shutdown()
        self.app.exit()

    def action_cycle_theme(self) -> None:
        name = self.app.cycle_theme()
        # theme_variables refreshes after the theme watcher runs, so re-render
        # the table (accent-colored cells) on the next screen refresh.
        self.app.call_after_refresh(self._render_table)
        self._show_status(f"Tema: {name}")

    def _accent(self) -> str:
        color = getattr(self.app, "theme_variables", {}).get("primary")
        return str(color) if color else "#9FEF00"

    def action_spawn_machine(self) -> None:
        if self.current_section != "machines":
            return
        row = self._selected_row_data()
        if not row:
            self._show_status("Selecione uma máquina para spawn.")
            return
        machine_id = self._row_int(row, "id")
        if machine_id is None:
            self._show_status("ID da máquina inválido.")
            return
        self._run_machine_action("spawn", machine_id, str(row.get("name", "-")))

    def action_stop_machine(self) -> None:
        if self.current_section != "machines":
            return
        row = self._selected_row_data()
        if not row:
            self._show_status("Selecione uma máquina para stop.")
            return
        machine_id = self._row_int(row, "id")
        if machine_id is None:
            self._show_status("ID da máquina inválido.")
            return
        name = str(row.get("name", "-"))

        def _after(confirm: bool) -> None:
            if confirm:
                self._run_machine_action("stop", machine_id, name)
            else:
                self._show_status("Stop cancelado.")

        self.app.push_screen(
            ConfirmModal("Confirmar stop", f"Deseja parar a máquina {name}?"),
            callback=_after,
        )

    def action_reset_machine(self) -> None:
        if self.current_section != "machines":
            return
        row = self._selected_row_data()
        if not row:
            self._show_status("Selecione uma máquina para reset.")
            return
        machine_id = self._row_int(row, "id")
        if machine_id is None:
            self._show_status("ID da máquina inválido.")
            return
        name = str(row.get("name", "-"))

        def _after(confirm: bool) -> None:
            if confirm:
                self._run_machine_action("reset", machine_id, name)
            else:
                self._show_status("Reset cancelado.")

        self.app.push_screen(
            ConfirmModal("Confirmar reset", f"Deseja resetar a máquina {name}?"),
            callback=_after,
        )

    def action_submit_flag(self) -> None:
        row = self._selected_row_data()
        if not row:
            self._show_status("Selecione um item para enviar flag.")
            return
        section = self.current_section
        if section == "machines":
            machine_id = self._row_int(row, "id")
            if machine_id is None:
                self._show_status("ID da máquina inválido.")
                return
            name = str(row.get("name", "-"))

            def _after_submit(data: Optional[tuple[str, int]]) -> None:
                if not data:
                    self._show_status("Submit cancelado.")
                    return
                flag, difficulty = data
                self._run_submit_machine_flag(machine_id, name, flag, difficulty)

            self.app.push_screen(FlagSubmitModal("machine", name), callback=_after_submit)
            return

        if section == "challenges":
            challenge_id = self._row_int(row, "id")
            if challenge_id is None:
                self._show_status("ID do challenge inválido.")
                return
            name = str(row.get("name", "-"))

            def _after_submit(data: Optional[tuple[str, int]]) -> None:
                if not data:
                    self._show_status("Submit cancelado.")
                    return
                flag, difficulty = data
                self._run_submit_challenge_flag(challenge_id, name, flag, difficulty)

            self.app.push_screen(FlagSubmitModal("challenge", name), callback=_after_submit)
            return

        self._show_status("Submit de flag disponível em Machines e Challenges.")

    # ------------------------------------------------------------------ #
    # Section switching and filters
    # ------------------------------------------------------------------ #
    @on(ListView.Highlighted, "#sections-list")
    def _sidebar_changed(self, event: ListView.Highlighted) -> None:
        section = self.query_one(Sidebar).section_from_index(event.list_view.index)
        if section != self.current_section:
            self.current_section = section
            self._show_status(f"Seção ativa: {section}")
            self.query_one(ContextHelp).set_context(None)
            self._refresh_filters()
            self._configure_table_columns()
            self._render_table()
            # Preserve in-memory data when changing menus; fetch only if empty.
            self._ensure_section_data(section)
            if section == "watch":
                self.start_watch_loop()
            else:
                self.watch_loop_enabled = False

    @on(ListView.Selected, "#filters-list")
    def _filter_selected(self, event: ListView.Selected) -> None:
        panel = self.query_one(FilterPanel)
        idx = event.list_view.index
        if idx is None or idx < 0 or idx >= len(panel.entries):
            return
        key = panel.entries[idx].key
        self._cycle_filter_value(key)

    @on(DataTable.RowHighlighted, "#data-table")
    def _table_row_highlighted(self, _event: DataTable.RowHighlighted) -> None:
        self._preview_selected_row_detail()

    @on(DataTable.RowSelected, "#data-table")
    def _table_row_selected(self, _event: DataTable.RowSelected) -> None:
        # DataTable geralmente consome Enter; esse evento garante abertura do detalhe.
        self._open_detail_from_table()

    def _section_filter_specs(self) -> list[FilterSpec]:
        if self.current_section == "machines":
            return [
                FilterSpec("retired", "Retired", ["all", "active", "retired"]),
                FilterSpec("os", "OS", ["all", "linux", "windows"]),
                FilterSpec("difficulty", "Dificuldade", ["all", "easy", "medium", "hard", "insane"]),
                FilterSpec("status", "Status", ["all", "done", "undone"]),
                FilterSpec("sort", "Sort", ["default", "rating", "points", "difficulty", "name", "user", "root"]),
                FilterSpec("search", "Busca", [self.search_text.get("machines", "") or "-"]),
            ]
        if self.current_section == "challenges":
            categories = ["all"]
            for c in self.raw_data.get("challenge_categories", []):
                name = str(c.get("name", "")).strip()
                if name and name not in categories:
                    categories.append(name)
            return [
                FilterSpec("retired", "Retired", ["active", "retired", "all"]),
                FilterSpec("difficulty", "Dificuldade", ["all", "easy", "medium", "hard", "insane"]),
                FilterSpec("status", "Status", ["all", "done", "undone"]),
                FilterSpec("category", "Categoria", categories),
                FilterSpec("search", "Busca", [self.search_text.get("challenges", "") or "-"]),
            ]
        if self.current_section == "sherlocks":
            return [
                FilterSpec("state", "Estado", ["all", "active", "retired"]),
                FilterSpec("difficulty", "Dificuldade", ["all", "easy", "medium", "hard", "insane"]),
                FilterSpec("status", "Status", ["all", "done", "undone"]),
                FilterSpec("search", "Busca", [self.search_text.get("sherlocks", "") or "-"]),
            ]
        if self.current_section == "ranking":
            return [
                FilterSpec("scope", "Escopo", ["world", "country", "team", "uni"]),
                FilterSpec("country", "País", [self.cfg.country.upper()]),
            ]
        return []

    def _refresh_filters(self) -> None:
        entries: list[FilterEntry] = []
        section_filters = self.filters.setdefault(self.current_section, {})
        for spec in self._section_filter_specs():
            if spec.key == "search":
                value = spec.options[0]
            elif spec.key == "country":
                value = self.cfg.country.upper()
            else:
                value = section_filters.get(spec.key, spec.options[0])
                section_filters.setdefault(spec.key, value)
            entries.append(FilterEntry(spec.key, spec.label, value))
        self.query_one(FilterPanel).set_entries(entries)

    def _cycle_filter_value(self, key: str) -> None:
        if key == "search":
            self.action_search()
            return
        section_filters = self.filters.setdefault(self.current_section, {})
        specs = {spec.key: spec for spec in self._section_filter_specs()}
        spec = specs.get(key)
        if not spec or len(spec.options) <= 1:
            return
        current = section_filters.get(key, spec.options[0])
        try:
            idx = spec.options.index(current)
        except ValueError:
            idx = 0
        section_filters[key] = spec.options[(idx + 1) % len(spec.options)]
        self._refresh_filters()
        if self.current_section == "ranking" and key == "scope":
            self.load_section_data("ranking")
        else:
            self._render_table()

    def action_search(self) -> None:
        if self.current_section not in {"machines", "challenges", "sherlocks"}:
            return
        initial = self.search_text.get(self.current_section, "")

        def _apply_search(value: Optional[str]) -> None:
            if value is None:
                return
            self.search_text[self.current_section] = value
            self._refresh_filters()
            self._render_table()

        self.app.push_screen(SearchModal(initial), callback=_apply_search)

    # ------------------------------------------------------------------ #
    # Data loading (workers + retry for 429)
    # ------------------------------------------------------------------ #
    def _with_retry(self, fn: Callable[[], Any], *, label: str) -> Any:
        delay = 1.0
        for attempt in range(5):
            if self.is_closing:
                raise ShutdownInProgress()
            try:
                return fn()
            except HTBError as exc:
                msg = str(exc)
                if "429" in msg and attempt < 4:
                    self.app.call_from_thread(self._show_status, f"{label}: rate limit, retry em {delay:.0f}s...")
                    if not self._cooperative_sleep(delay):
                        raise ShutdownInProgress()
                    delay *= 2
                    continue
                raise

    @work(thread=True, exclusive=True, group="profile")
    def load_profile_header(self) -> None:
        try:
            profile = self._with_retry(self.client.self_profile, label="Perfil")
            active = self._with_retry(self.client.machine_active, label="Máquina ativa")
            self.app.call_from_thread(self._apply_profile_header, profile, active)
        except ShutdownInProgress:
            return
        except HTBError as exc:
            self.app.call_from_thread(self._show_status, f"Falha ao carregar perfil: {exc}")

    def _apply_profile_header(self, profile: dict[str, Any], active: Optional[dict[str, Any]]) -> None:
        parts = [
            str(profile.get("name", "-")),
            f"Rank #{profile.get('ranking', '-')}",
            f"{profile.get('points', '-')} pts",
        ]
        if active:
            ip = active.get("ip") or "aguardando IP"
            parts.append(f"Active: {active.get('name', '-')} ({ip})")
        self.query_one("#header-user", Static).update("  ·  ".join(parts))
        self.raw_data["profile"] = profile
        self.raw_data["active"] = active
        self._show_status("Perfil atualizado.")

    def _sidebar_counts(self) -> dict[str, int]:
        """Build the "N results" hints shown next to each sidebar section."""
        counts: dict[str, int] = {}
        m_active, m_retired = self.raw_data.get("machines_active"), self.raw_data.get("machines_retired")
        if m_active is not None or m_retired is not None:
            counts["machines"] = len(m_active or []) + len(m_retired or [])
        c_active, c_retired = self.raw_data.get("challenges_active"), self.raw_data.get("challenges_retired")
        if c_active is not None or c_retired is not None:
            counts["challenges"] = len(c_active or []) + len(c_retired or [])
        sherlocks = self.raw_data.get("sherlocks")
        if sherlocks is not None:
            counts["sherlocks"] = len(sherlocks)
        ranking_rows = self.raw_data.get("ranking_rows")
        if ranking_rows is not None:
            counts["ranking"] = len(ranking_rows)
        if "watch_machine" in self.raw_data:
            counts["watch"] = 1 if self.raw_data.get("watch_machine") else 0
        return counts

    def _ensure_section_data(self, section: str) -> None:
        cache_keys = {
            "machines": "machines_active",
            "challenges": "challenges_active",
            "sherlocks": "sherlocks",
            "ranking": "ranking_rows",
            "watch": "watch_machine",
            "profile": "profile",
        }
        key = cache_keys.get(section, section)
        if key not in self.raw_data:
            self.load_section_data(section)

    @work(thread=True, group="section")
    def load_section_data(self, section: str) -> None:
        try:
            self.app.call_from_thread(self._set_loading, True, section)
            self.app.call_from_thread(self._show_status, f"Carregando {section}...")
            if section == "machines":
                active = self._with_retry(self.client.machines_active, label="Machines active")
                retired = self._with_retry(self.client.machines_retired, label="Machines retired")
                payload = {"machines_active": active, "machines_retired": retired}
            elif section == "challenges":
                active = self._with_retry(lambda: self.client.challenges(retired=False), label="Challenges active")
                retired = self._with_retry(lambda: self.client.challenges(retired=True), label="Challenges retired")
                categories = self._with_retry(self.client.challenge_categories, label="Categorias")
                payload = {
                    "challenges_active": active,
                    "challenges_retired": retired,
                    "challenge_categories": categories,
                }
            elif section == "sherlocks":
                payload = {"sherlocks": self._with_retry(self.client.sherlocks, label="Sherlocks")}
            elif section == "ranking":
                scope = self.filters["ranking"]["scope"]
                if scope == "world":
                    rows = self._with_retry(self.client.ranking_world, label="Ranking world")
                elif scope == "country":
                    rows = self._with_retry(lambda: self.client.ranking_country(self.cfg.country), label="Ranking country")
                elif scope == "team":
                    rows = self._with_retry(self.client.ranking_teams, label="Ranking teams")
                else:
                    rows = self._with_retry(self.client.ranking_universities, label="Ranking uni")
                payload = {"ranking_rows": rows}
            elif section == "profile":
                payload = {"profile": self._with_retry(self.client.self_profile, label="Perfil")}
            elif section == "watch":
                active = self._with_retry(self.client.machine_active, label="Máquina ativa")
                if not active:
                    payload = {"watch_machine": None}
                else:
                    prof = self._with_retry(lambda: self.client.machine_profile(active.get("id")), label="Machine watch")
                    payload = {"watch_machine": prof}
            else:
                payload = {}
            self.app.call_from_thread(self._apply_payload, payload, section)
        except ShutdownInProgress:
            return
        except HTBError as exc:
            self.app.call_from_thread(self._set_loading, False, section)
            self.app.call_from_thread(self._show_status, f"Erro em {section}: {exc}")

    def _apply_payload(self, payload: dict[str, Any], section: str) -> None:
        self.raw_data.update(payload)
        self._refresh_filters()
        self._render_table()
        self.query_one(Sidebar).update_counts(self._sidebar_counts())
        self._set_loading(False, section)
        counts: list[str] = []
        for key, value in payload.items():
            if isinstance(value, list):
                counts.append(f"{key}={len(value)}")
            elif value is None:
                counts.append(f"{key}=none")
            else:
                counts.append(f"{key}=ok")
        suffix = f" ({', '.join(counts)})" if counts else ""
        self._show_status(f"{section} atualizado{suffix}.")

    # ------------------------------------------------------------------ #
    # Watch / blood live mode
    # ------------------------------------------------------------------ #
    @work(thread=True, group="watch")
    def start_watch_loop(self) -> None:
        if self.watch_loop_enabled:
            return
        self.watch_loop_enabled = True
        while self.watch_loop_enabled and not self.is_closing:
            try:
                active = self._with_retry(self.client.machine_active, label="Watch active")
                if not active:
                    self.app.call_from_thread(self._apply_watch_data, None)
                    if not self._cooperative_sleep(15):
                        break
                    continue
                profile = self._with_retry(lambda: self.client.machine_profile(active.get("id")), label="Watch profile")
                self.app.call_from_thread(self._apply_watch_data, profile)
            except ShutdownInProgress:
                break
            except HTBError as exc:
                self.app.call_from_thread(self._show_status, f"Watch pausado: {exc}")
            if not self._cooperative_sleep(15):
                break

    def _apply_watch_data(self, profile: Optional[dict[str, Any]]) -> None:
        self.raw_data["watch_machine"] = profile
        if not profile:
            if self.current_section == "watch":
                self.query_one(DetailPane).set_text("Nenhuma máquina ativa para monitorar.")
                self._render_table()
            return

        user_blood = ((profile.get("userBlood") or {}).get("user") or {}).get("name")
        root_blood = ((profile.get("rootBlood") or {}).get("user") or {}).get("name")

        if user_blood and user_blood != self.last_blood_user:
            self.last_blood_user = user_blood
            self._blood_alert(f"USER BLOOD: {user_blood}")
        if root_blood and root_blood != self.last_blood_root:
            self.last_blood_root = root_blood
            self._blood_alert(f"ROOT BLOOD: {root_blood}")

        if self.current_section == "watch":
            self._render_table()

    def _blood_alert(self, message: str) -> None:
        self.app.bell()
        pane = self.query_one(DetailPane)
        pane.add_class("blood-alert")
        self.set_timer(1.2, lambda: pane.remove_class("blood-alert"))
        self._show_status(message)

    # ------------------------------------------------------------------ #
    # Table rendering and selection
    # ------------------------------------------------------------------ #
    def _configure_table_columns(self) -> None:
        table = self.query_one("#data-table", DataTable)
        table.clear(columns=True)
        self.table_rows = []
        if self.current_section == "machines":
            table.add_columns("ID", "Name", "OS", "Diff", "Pts", "Rating", "Done")
        elif self.current_section == "watch":
            table.add_columns("ID", "Name", "IP", "User Blood", "Root Blood", "User owns", "Root owns")
        elif self.current_section == "challenges":
            table.add_columns("ID", "Name", "Category", "Diff", "Pts", "Solves", "Done")
        elif self.current_section == "sherlocks":
            table.add_columns("ID", "Name", "Category", "Diff", "State", "Solves", "Done")
        elif self.current_section == "ranking":
            table.add_columns("#", "Name", "Rank", "Points", "Country/Team")
        elif self.current_section == "profile":
            table.add_columns("Field", "Value")

    def _render_table(self) -> None:
        table = self.query_one("#data-table", DataTable)
        table.clear(columns=False)
        self.table_rows = []
        detail = self.query_one(DetailPane)
        section = self.current_section
        accent = self._accent()

        if section == "machines":
            rows = self._filtered_machines()
            for m in rows:
                table.add_row(
                    Text(str(m.get("id", "-")), style="dim"),
                    Text(str(m.get("name", "-")), style="bold"),
                    self._machine_os_text(m),
                    _diff_cell(self._machine_difficulty_text(m)),
                    str(m.get("points", m.get("static_points", "-"))),
                    _rating_cell(m.get("star")),
                    _done_cell(self._solved_machine(m), accent),
                )
            self.table_rows = rows
            detail.set_text("Selecione uma máquina e pressione Enter para detalhes.")
        elif section == "watch":
            machine = self.raw_data.get("watch_machine")
            if machine:
                ub = ((machine.get("userBlood") or {}).get("user") or {}).get("name") or "-"
                rb = ((machine.get("rootBlood") or {}).get("user") or {}).get("name") or "-"
                table.add_row(
                    str(machine.get("id", "-")),
                    str(machine.get("name", "-")),
                    str(machine.get("ip", "-")),
                    ub,
                    rb,
                    str(machine.get("user_owns_count", "-")),
                    str(machine.get("root_owns_count", "-")),
                )
                self.table_rows = [machine]
                detail.set_text(
                    f"{machine.get('name', '-')}\n"
                    f"IP: {machine.get('ip', '-')}\n"
                    f"Difficulty: {machine.get('difficultyText', '-')}\n"
                    f"User Blood: {ub}\n"
                    f"Root Blood: {rb}"
                )
            else:
                detail.set_text("Nenhuma máquina ativa para monitorar no Watch.")
        elif section == "challenges":
            rows = self._filtered_challenges()
            for c in rows:
                table.add_row(
                    Text(str(c.get("id", "-")), style="dim"),
                    Text(str(c.get("name", "-")), style="bold"),
                    str(c.get("category_name") or c.get("category") or "-"),
                    _diff_cell(c.get("difficulty", "-")),
                    str(c.get("points", "-")),
                    str(c.get("solves", "-")),
                    _done_cell(self._solved(c), accent),
                )
            self.table_rows = rows
            detail.set_text("Selecione um challenge e pressione Enter para detalhes.")
        elif section == "sherlocks":
            rows = self._filtered_sherlocks()
            for s in rows:
                table.add_row(
                    Text(str(s.get("id", "-")), style="dim"),
                    Text(str(s.get("name", "-")), style="bold"),
                    str(s.get("category_name", "DFIR")),
                    _diff_cell(s.get("difficulty", "-")),
                    str(s.get("state", "-")),
                    str(s.get("solves", "-")),
                    _done_cell(self._solved(s), accent),
                )
            self.table_rows = rows
            detail.set_text("Selecione um sherlock e pressione Enter para detalhes.")
        elif section == "ranking":
            scope = self.filters["ranking"]["scope"]
            rows = self.raw_data.get("ranking_rows", [])
            self_found = False
            for idx, r in enumerate(rows, start=1):
                name = r.get("name") or r.get("username") or r.get("user_name") or "-"
                rank_name = r.get("level") or r.get("rank_name") or r.get("rankText") or "-"
                points = r.get("points") or r.get("rankingPoints") or r.get("rank_points") or "-"
                country = (
                    (r.get("country") or {}).get("name")
                    if isinstance(r.get("country"), dict)
                    else r.get("country")
                ) or r.get("team") or "-"
                is_self = self._is_self_ranking_row(scope, r)
                self_found = self_found or is_self
                if is_self:
                    name = f"» {name} (você)"
                table.add_row(
                    _rank_cell(r.get("rank", idx), is_self, accent),
                    _rank_cell(name, is_self, accent),
                    _rank_cell(rank_name, is_self, accent),
                    _rank_cell(points, is_self, accent),
                    _rank_cell(country, is_self, accent),
                )
            self.table_rows = rows
            detail.set_text(
                "Você está destacado na lista." if self_found else "Ranking carregado."
            )
        elif section == "profile":
            p = self.raw_data.get("profile", {})
            rows = [
                ("Name", p.get("name", "-")),
                ("Global Rank", f"#{p.get('ranking', '-')}"),
                ("Rank/Level", p.get("rank", "-")),
                ("Points", p.get("points", "-")),
                ("User Owns", p.get("user_owns", "-")),
                ("System Owns", p.get("system_owns", "-")),
                ("Team", (p.get("team") or {}).get("name", "-")),
                ("Country", p.get("country_name") or p.get("country") or "-"),
            ]
            for left, right in rows:
                table.add_row(str(left), str(right))
            self.table_rows = [p]
            detail.set_text("Perfil completo no painel central.")
        table.refresh()

    def _is_self_ranking_row(self, scope: str, row: dict[str, Any]) -> bool:
        """Whether a ranking row is the logged-in user (or their team)."""
        if scope in ("world", "country"):
            target = self.cfg.user_id
        elif scope == "team":
            target = self.cfg.team_id
        else:
            return False
        if target is None:
            return False
        try:
            return int(row.get("id")) == int(target)
        except (TypeError, ValueError):
            return False

    def _filtered_machines(self) -> list[dict[str, Any]]:
        f = self.filters["machines"]
        if f["retired"] == "retired":
            rows = list(self.raw_data.get("machines_retired", []))
        elif f["retired"] == "active":
            rows = list(self.raw_data.get("machines_active", []))
        else:
            rows = list(self.raw_data.get("machines_active", [])) + list(self.raw_data.get("machines_retired", []))
        if f["os"] != "all":
            rows = [m for m in rows if f["os"] in self._machine_os_text(m).lower()]
        if f["difficulty"] != "all":
            rows = [m for m in rows if f["difficulty"] in self._machine_difficulty_text(m).lower()]
        if f["status"] == "done":
            rows = [m for m in rows if self._solved_machine(m)]
        elif f["status"] == "undone":
            rows = [m for m in rows if not self._solved_machine(m)]
        search = self.search_text.get("machines", "").strip().lower()
        if search:
            rows = [m for m in rows if search in str(m.get("name", "")).lower()]
        sort_key = f.get("sort", "default")
        if sort_key != "default":
            rows = sorted(rows, key=self._machine_sort_key(sort_key), reverse=sort_key != "name")
        return rows

    def _filtered_challenges(self) -> list[dict[str, Any]]:
        f = self.filters["challenges"]
        retired = f["retired"]
        if retired == "retired":
            rows = list(self.raw_data.get("challenges_retired", []))
        elif retired == "active":
            rows = list(self.raw_data.get("challenges_active", []))
        else:
            rows = list(self.raw_data.get("challenges_active", [])) + list(self.raw_data.get("challenges_retired", []))
        if f["difficulty"] != "all":
            rows = [c for c in rows if f["difficulty"] in str(c.get("difficulty", "")).lower()]
        if f["status"] == "done":
            rows = [c for c in rows if self._solved(c)]
        elif f["status"] == "undone":
            rows = [c for c in rows if not self._solved(c)]
        if f["category"] != "all":
            rows = [
                c
                for c in rows
                if f["category"].lower() in str(c.get("category_name") or c.get("category") or "").lower()
            ]
        search = self.search_text.get("challenges", "").strip().lower()
        if search:
            rows = [c for c in rows if search in str(c.get("name", "")).lower()]
        return rows

    def _filtered_sherlocks(self) -> list[dict[str, Any]]:
        f = self.filters["sherlocks"]
        rows = list(self.raw_data.get("sherlocks", []))
        if f["state"] == "active":
            rows = [s for s in rows if str(s.get("state", "")).lower() == "active"]
        elif f["state"] == "retired":
            rows = [s for s in rows if "retired" in str(s.get("state", "")).lower()]
        if f["difficulty"] != "all":
            rows = [s for s in rows if f["difficulty"] in str(s.get("difficulty", "")).lower()]
        if f["status"] == "done":
            rows = [s for s in rows if self._solved(s)]
        elif f["status"] == "undone":
            rows = [s for s in rows if not self._solved(s)]
        search = self.search_text.get("sherlocks", "").strip().lower()
        if search:
            rows = [s for s in rows if search in str(s.get("name", "")).lower()]
        return rows

    def _machine_sort_key(self, field: str):
        mapping: dict[str, Callable[[dict[str, Any]], Any]] = {
            "rating": lambda m: float(m.get("star") or 0),
            "points": lambda m: int(m.get("points") or m.get("static_points") or 0),
            "difficulty": lambda m: int(m.get("difficulty") or 0),
            "name": lambda m: str(m.get("name", "")).lower(),
            "user": lambda m: int(m.get("user_owns_count") or 0),
            "root": lambda m: int(m.get("root_owns_count") or 0),
        }
        return mapping.get(field, mapping["rating"])

    def _solved_machine(self, machine: dict[str, Any]) -> bool:
        return bool(
            machine.get("authUserInRootOwns")
            or machine.get("authUserInUserOwns")
            or machine.get("is_owned")
            or machine.get("owned")
            or machine.get("user_owned")
            or machine.get("root_owned")
        )

    def _solved(self, item: dict[str, Any]) -> bool:
        return bool(
            item.get("is_owned")
            or item.get("authUserSolve")
            or item.get("isCompleted")
            or item.get("solved")
            or item.get("owned")
            or item.get("completed")
        )

    def _machine_os_text(self, machine: dict[str, Any]) -> str:
        value = machine.get("os")
        if isinstance(value, dict):
            return str(value.get("name") or value.get("os") or "-")
        if value:
            return str(value)
        return str(machine.get("os_name") or "-")

    def _machine_difficulty_text(self, machine: dict[str, Any]) -> str:
        text = machine.get("difficultyText") or machine.get("difficulty_text")
        if text:
            return str(text)
        value = machine.get("difficulty")
        if isinstance(value, (int, float)):
            if value <= 30:
                return "easy"
            if value <= 60:
                return "medium"
            if value <= 85:
                return "hard"
            return "insane"
        return str(value or "-")

    # ------------------------------------------------------------------ #
    # Details
    # ------------------------------------------------------------------ #
    def action_open_detail(self) -> None:
        focused = self.app.focused
        if isinstance(focused, ListView):
            if focused.id == "sections-list":
                section = self.query_one(Sidebar).section_from_index(focused.index)
                if section != self.current_section:
                    self.current_section = section
                    self._refresh_filters()
                    self._configure_table_columns()
                    self._render_table()
                    self._ensure_section_data(section)
            elif focused.id == "filters-list" and focused.highlighted_child is not None:
                panel = self.query_one(FilterPanel)
                idx = focused.index
                if idx is not None and 0 <= idx < len(panel.entries):
                    self._cycle_filter_value(panel.entries[idx].key)
            return

        if not isinstance(focused, DataTable):
            return
        self._open_detail_from_table()

    def _open_detail_from_table(self) -> None:
        table = self.query_one("#data-table", DataTable)
        idx = self._current_table_index(table)
        if idx is None:
            return
        if idx < 0 or idx >= len(self.table_rows):
            return
        row = self.table_rows[idx]
        section = self.current_section
        if section == "machines":
            self._show_status(f"Abrindo detalhe da máquina {row.get('name', '-')}")
            self.load_machine_detail(row.get("id"))
        elif section == "challenges":
            self._show_status(f"Abrindo detalhe do challenge {row.get('name', '-')}")
            self.load_challenge_detail(row.get("id"))
        elif section == "sherlocks":
            self._show_status(f"Abrindo detalhe do sherlock {row.get('name', '-')}")
            self.load_sherlock_detail(row.get("id"))
        elif section == "watch":
            self._set_detail_from_machine(row)
        elif section == "ranking":
            self._set_ranking_detail(row)
        elif section == "profile":
            self.query_one(DetailPane).set_text("Perfil carregado. Use Esc para limpar este painel.")

    def action_close_detail(self) -> None:
        self.detail_locked = False
        self.query_one(DetailPane).set_text("Selecione um item e pressione Enter.")

    @work(thread=True, group="detail")
    def load_machine_detail(self, machine_id: Any) -> None:
        try:
            self.app.call_from_thread(self._set_detail_text, self._detail_loading_text("machine"))
            data = self._with_retry(lambda: self.client.machine_profile(machine_id), label="Machine detail")
            self.app.call_from_thread(self._set_detail_from_machine, data)
        except HTBError as exc:
            self.app.call_from_thread(self._set_detail_text, f"Erro ao carregar machine: {exc}")
            self.app.call_from_thread(self._show_status, f"Erro detalhe machine: {exc}")

    @work(thread=True, group="detail")
    def load_challenge_detail(self, challenge_id: Any) -> None:
        try:
            self.app.call_from_thread(self._set_detail_text, self._detail_loading_text("challenge"))
            data = self._with_retry(lambda: self.client.challenge_info(int(challenge_id)), label="Challenge detail")
            self.app.call_from_thread(self._set_detail_from_challenge, data)
        except (HTBError, ValueError) as exc:
            self.app.call_from_thread(self._set_detail_text, f"Erro ao carregar challenge: {exc}")
            self.app.call_from_thread(self._show_status, f"Erro detalhe challenge: {exc}")

    @work(thread=True, group="detail")
    def load_sherlock_detail(self, sherlock_id: Any) -> None:
        try:
            self.app.call_from_thread(self._set_detail_text, self._detail_loading_text("sherlock"))
            data = self._with_retry(lambda: self.client.sherlock_info(int(sherlock_id)), label="Sherlock detail")
            self.app.call_from_thread(self._set_detail_from_sherlock, data)
        except (HTBError, ValueError) as exc:
            self.app.call_from_thread(self._set_detail_text, f"Erro ao carregar sherlock: {exc}")
            self.app.call_from_thread(self._show_status, f"Erro detalhe sherlock: {exc}")

    @work(thread=True, group="actions")
    def _run_machine_action(self, action: str, machine_id: int, machine_name: str) -> None:
        try:
            self.app.call_from_thread(self._set_detail_text, f"{action.upper()} {machine_name}\n(*) enviando ação...")
            if action == "spawn":
                result = self._with_retry(lambda: self.client.spawn(machine_id), label="Spawn")
            elif action == "stop":
                result = self._with_retry(lambda: self.client.terminate(machine_id), label="Stop")
            elif action == "reset":
                result = self._with_retry(lambda: self.client.reset(machine_id), label="Reset")
            else:
                self.app.call_from_thread(self._show_status, f"Ação inválida: {action}")
                return
            msg = result.get("message", f"{action} executado em {machine_name}.")
            self.app.call_from_thread(self._set_detail_text, msg)
            self.app.call_from_thread(self._show_status, msg)
            self.app.call_from_thread(self._refresh_after_action, True)
        except ShutdownInProgress:
            return
        except HTBError as exc:
            self.app.call_from_thread(self._set_detail_text, f"Erro na ação {action}: {exc}")
            self.app.call_from_thread(self._show_status, f"Erro {action}: {exc}")

    @work(thread=True, group="actions")
    def _run_submit_machine_flag(self, machine_id: int, machine_name: str, flag: str, difficulty: int) -> None:
        try:
            self.app.call_from_thread(
                self._set_detail_text,
                f"SUBMIT MACHINE FLAG\n{machine_name}\n(*) enviando flag com dificuldade {difficulty}...",
            )
            result = self._with_retry(
                lambda: self.client.submit_machine_flag(machine_id, flag, difficulty),
                label="Submit machine flag",
            )
            msg = result.get("message", "Flag de máquina enviada.")
            self.app.call_from_thread(self._set_detail_text, msg)
            self.app.call_from_thread(self._show_status, msg)
            self.app.call_from_thread(self._refresh_after_action, True)
        except ShutdownInProgress:
            return
        except HTBError as exc:
            self.app.call_from_thread(self._set_detail_text, f"Erro no submit de máquina: {exc}")
            self.app.call_from_thread(self._show_status, f"Submit máquina falhou: {exc}")

    @work(thread=True, group="actions")
    def _run_submit_challenge_flag(self, challenge_id: int, challenge_name: str, flag: str, difficulty: int) -> None:
        try:
            self.app.call_from_thread(
                self._set_detail_text,
                f"SUBMIT CHALLENGE FLAG\n{challenge_name}\n(*) enviando flag com dificuldade {difficulty}...",
            )
            result = self._with_retry(
                lambda: self.client.submit_challenge_flag(challenge_id, flag, difficulty),
                label="Submit challenge flag",
            )
            msg = result.get("message", "Flag de challenge enviada.")
            self.app.call_from_thread(self._set_detail_text, msg)
            self.app.call_from_thread(self._show_status, msg)
            self.app.call_from_thread(self._refresh_after_action, False)
        except ShutdownInProgress:
            return
        except HTBError as exc:
            self.app.call_from_thread(self._set_detail_text, f"Erro no submit de challenge: {exc}")
            self.app.call_from_thread(self._show_status, f"Submit challenge falhou: {exc}")

    def _refresh_after_action(self, machine_related: bool) -> None:
        self.load_profile_header()
        self.load_section_data(self.current_section)
        if machine_related and self.current_section != "watch":
            self.load_section_data("watch")

    def _set_detail_from_machine(self, m: dict[str, Any]) -> None:
        self.detail_locked = True
        ub = ((m.get("userBlood") or {}).get("user") or {}).get("name") or "-"
        rb = ((m.get("rootBlood") or {}).get("user") or {}).get("name") or "-"
        text = (
            f"{m.get('name', '-')}\n"
            f"ID: {m.get('id', '-')}\n"
            f"OS: {m.get('os', '-')}\n"
            f"Difficulty: {m.get('difficultyText') or m.get('difficulty') or '-'}\n"
            f"Points: {m.get('points', '-')}\n"
            f"Rating: {m.get('star', '-')}\n"
            f"IP: {m.get('ip', '-')}\n"
            f"User owns: {m.get('user_owns_count', '-')}\n"
            f"Root owns: {m.get('root_owns_count', '-')}\n"
            f"User blood: {ub}\n"
            f"Root blood: {rb}"
        )
        self.query_one(DetailPane).set_text(text)

    def _set_detail_from_challenge(self, c: dict[str, Any]) -> None:
        self.detail_locked = True
        solved = "yes" if self._solved(c) else "no"
        text = (
            f"{c.get('name', '-')}\n"
            f"ID: {c.get('id', '-')}\n"
            f"Category: {c.get('category_name') or c.get('category') or '-'}\n"
            f"Difficulty: {c.get('difficulty', '-')}\n"
            f"Points: {c.get('points', '-')}\n"
            f"Solves: {c.get('solves', '-')}\n"
            f"Solved: {solved}\n\n"
            f"{(c.get('description') or '').strip()}"
        )
        self.query_one(DetailPane).set_text(text)

    def _set_detail_from_sherlock(self, s: dict[str, Any]) -> None:
        self.detail_locked = True
        solved = "yes" if self._solved(s) else "no"
        desc = (s.get("description") or s.get("scenario") or "").strip()
        text = (
            f"{s.get('name', '-')}\n"
            f"ID: {s.get('id', '-')}\n"
            f"Category: {s.get('category_name', 'DFIR')}\n"
            f"Difficulty: {s.get('difficulty', '-')}\n"
            f"Solves: {s.get('solves', '-')}\n"
            f"Rating: {s.get('rating', '-')}\n"
            f"Solved: {solved}\n\n"
            f"{desc}"
        )
        self.query_one(DetailPane).set_text(text)

    def _set_ranking_detail(self, row: dict[str, Any]) -> None:
        self.detail_locked = True
        name = row.get("name") or row.get("username") or row.get("user_name") or "-"
        country = row.get("country")
        if isinstance(country, dict):
            country = country.get("name")
        text = (
            f"{name}\n"
            f"Rank: {row.get('rank') or row.get('ranking') or '-'}\n"
            f"Level: {row.get('level') or row.get('rank_name') or row.get('rankText') or '-'}\n"
            f"Points: {row.get('points') or row.get('rankingPoints') or row.get('rank_points') or '-'}\n"
            f"Country/Team: {country or row.get('team') or '-'}"
        )
        self.query_one(DetailPane).set_text(text)

    # ------------------------------------------------------------------ #
    # Status / context
    # ------------------------------------------------------------------ #
    def _show_status(self, message: str) -> None:
        self.query_one("#status-line", Static).update(message)

    def _set_loading(self, active: bool, target: str) -> None:
        if not active and target != self.current_section:
            return
        self.loading_active = active
        self.loading_target = target
        loading_panel = self.query_one("#loading-panel", Static)
        table = self.query_one("#data-table", DataTable)
        if active:
            self.loading_frame = 0
            loading_panel.remove_class("hidden")
            table.add_class("hidden")
            self._tick_loading()
        else:
            loading_panel.add_class("hidden")
            table.remove_class("hidden")

    def _tick_loading(self) -> None:
        if not self.loading_active:
            return
        spinner = ["|", "/", "-", "\\"]
        pulses = ["sync", "probe", "decrypt", "parse", "hydrate", "render"]
        spin = spinner[self.loading_frame % len(spinner)]
        pulse = pulses[self.loading_frame % len(pulses)]
        progress = (self.loading_frame * 7) % 100
        bar_width = 24
        fill = int((progress / 100) * bar_width)
        bar = "#" * fill + "." * (bar_width - fill)
        scan = self.loading_frame % bar_width
        beam = "".join(">" if idx == scan else "=" for idx in range(bar_width))
        text = (
            f" caphtb://{self.loading_target}\n\n"
            f" ({spin}) initializing {self.loading_target} module\n"
            f" ({pulse}) packet stream accepted\n"
            f" ({bar}) {progress:02d}%\n"
            f" ({beam}) data bus\n\n"
            " waiting for Hack The Box API response..."
        )
        self.query_one("#loading-panel", Static).update(text)
        self.loading_frame += 1

    def _detail_loading_text(self, kind: str) -> str:
        return (
            f"{kind.upper()} DETAIL\n"
            "(*) opening endpoint\n"
            "(*) requesting payload\n"
            "(*) decoding response..."
        )

    def _set_detail_text(self, text: str) -> None:
        self.query_one(DetailPane).set_text(text)

    def _cooperative_sleep(self, seconds: float, step: float = 0.2) -> bool:
        """Sleep in short slices so app shutdown is fast."""
        elapsed = 0.0
        while elapsed < seconds:
            if self.is_closing or not self.watch_loop_enabled:
                return False
            chunk = min(step, seconds - elapsed)
            time.sleep(chunk)
            elapsed += chunk
        return True

    def _begin_shutdown(self) -> None:
        if self.is_closing:
            return
        self.is_closing = True
        self.watch_loop_enabled = False
        try:
            self.workers.cancel_node(self)
        except Exception:
            pass
        try:
            self.client.session.close()
        except Exception:
            pass

    def _selected_row_data(self) -> Optional[dict[str, Any]]:
        table = self.query_one("#data-table", DataTable)
        idx = self._current_table_index(table)
        if idx is None or idx < 0 or idx >= len(self.table_rows):
            return None
        return self.table_rows[idx]

    def _row_int(self, row: dict[str, Any], key: str) -> Optional[int]:
        try:
            return int(row.get(key))
        except (TypeError, ValueError):
            return None

    def _current_table_index(self, table: DataTable) -> int | None:
        row = getattr(table, "cursor_row", None)
        if row is not None:
            return int(row)
        coord = getattr(table, "cursor_coordinate", None)
        if coord is not None and hasattr(coord, "row"):
            return int(coord.row)
        return None

    def _preview_selected_row_detail(self) -> None:
        table = self.query_one("#data-table", DataTable)
        idx = self._current_table_index(table)
        if idx is None or idx < 0 or idx >= len(self.table_rows):
            return
        row = self.table_rows[idx]
        section = self.current_section
        if section == "machines":
            name = row.get("name", "-")
            mid = row.get("id", "-")
            os_name = self._machine_os_text(row)
            diff = self._machine_difficulty_text(row)
            pts = row.get("points", row.get("static_points", "-"))
            done = "yes" if self._solved_machine(row) else "no"
            self._set_detail_text(
                f"{name}\nID: {mid}\nOS: {os_name}\nDifficulty: {diff}\nPoints: {pts}\nSolved: {done}\n\nEnter detalhe | s spawn | x stop | r reset | f submit flag"
            )
        elif section == "challenges":
            self._set_detail_text(
                f"{row.get('name', '-')}\nID: {row.get('id', '-')}\nCategory: {row.get('category_name') or row.get('category') or '-'}\n"
                f"Difficulty: {row.get('difficulty', '-')}\n\nEnter detalhe | f submit flag"
            )
        elif section == "sherlocks":
            self._set_detail_text(
                f"{row.get('name', '-')}\nID: {row.get('id', '-')}\nState: {row.get('state', '-')}\n"
                f"Difficulty: {row.get('difficulty', '-')}\n\nPressione Enter para detalhe completo."
            )

    def _update_context_for_focus(self) -> None:
        focused = self.app.focused
        help_widget = self.query_one(ContextHelp)
        if isinstance(focused, DataTable):
            if self.current_section == "machines":
                help_widget.set_context("Machines: Enter detalhe | s spawn | x stop | r reset | f flag | / busca")
            elif self.current_section == "challenges":
                help_widget.set_context("Challenges: Enter detalhe | f flag | / busca | setas/hjkl navegam")
            else:
                help_widget.set_context("Tabela: setas/hjkl movem cursor | Enter detalhe | / busca | Esc limpa detalhe")
        elif isinstance(focused, ListView) and focused.id == "sections-list":
            help_widget.set_context("Seções: up/down ou j/k | Enter confirma | Tab troca painel")
        elif isinstance(focused, ListView) and focused.id == "filters-list":
            help_widget.set_context("Filtros: up/down ou j/k | Enter alterna valor | / busca")
        else:
            help_widget.set_context(None)

    def on_focus(self, _event: events.Focus) -> None:
        self._update_context_for_focus()
