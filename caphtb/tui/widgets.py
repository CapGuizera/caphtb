"""Reusable widgets for the caphtb Textual dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import ListItem, ListView, Static


# (key, label, nerd-font icon) - icons need a Nerd Font in the terminal,
# which the launcher's kitty profile guarantees.
SECTIONS: list[tuple[str, str, str]] = [
    ("machines", "Machines", "\uf233"),    # server
    ("watch", "Watch/Bloods", "\uf06e"),   # eye
    ("challenges", "Challenges", "\uf121"),  # code
    ("sherlocks", "Sherlocks", "\uf002"),  # magnifier
    ("ranking", "Ranking", "\uf091"),      # trophy
    ("profile", "Profile", "\uf007"),      # user
]


@dataclass
class FilterEntry:
    """One filter row rendered in the filter list."""

    key: str
    label: str
    value: str


class Sidebar(Static):
    """Left navigation with all available sections."""

    def compose(self):
        items = []
        for key, label, icon in SECTIONS:
            row = Static(f"{icon}  {label}", id=f"section-label-{key}", classes="sidebar-item")
            item = ListItem(row, id=f"section-{key}")
            items.append(item)
        yield ListView(*items, id="sections-list")

    def set_section(self, section_key: str) -> None:
        list_view = self.query_one("#sections-list", ListView)
        for index, (key, _label, _icon) in enumerate(SECTIONS):
            if key == section_key:
                list_view.index = index
                return

    def section_from_index(self, index: int | None) -> str:
        if index is None or index < 0 or index >= len(SECTIONS):
            return SECTIONS[0][0]
        return SECTIONS[index][0]

    def update_counts(self, counts: dict[str, int]) -> None:
        """Refresh the "N results" hint shown to the right of each section."""
        for key, label, icon in SECTIONS:
            row = self.query_one(f"#section-label-{key}", Static)
            count = counts.get(key)
            if count is None:
                row.update(f"{icon}  {label}")
            else:
                row.update(Text.assemble(f"{icon}  {label:<12}", (f"{count:>4}", "dim")))


class FilterPanel(Static):
    """Filter controls shown as keyboard-selectable rows."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.entries: list[FilterEntry] = []

    def compose(self):
        yield ListView(id="filters-list")

    def set_entries(self, entries: list[FilterEntry]) -> None:
        list_view = self.query_one("#filters-list", ListView)
        self.entries = list(entries)
        list_view.clear()
        for entry in entries:
            text = Text.assemble((f"{entry.label:<13}", "dim"), (entry.value, "bold"))
            # Avoid stable widget IDs here, since filters are rebuilt often.
            item = ListItem(Static(text, classes="filter-item"))
            list_view.append(item)
        if entries:
            list_view.index = min(list_view.index or 0, len(entries) - 1)


class DetailPane(Vertical):
    """Right-side pane used for metadata and item details."""

    def compose(self):
        yield Static("Detail", classes="panel-title")
        yield Static("Selecione um item e pressione Enter.", id="detail-body")

    def set_text(self, text: str) -> None:
        self.query_one("#detail-body", Static).update(text)


class ContextHelp(Static):
    """Contextual shortcuts line docked at the bottom."""

    DEFAULT_TEXT = (
        "Tab/Shift+Tab foco  ·  Enter detalhe  ·  / busca  ·  s spawn  ·  x stop  ·  "
        "r reset  ·  f flag  ·  t tema  ·  hjkl/setas navegar  ·  Esc fechar  ·  q sair"
    )

    def set_context(self, text: str | None = None) -> None:
        self.update(text or self.DEFAULT_TEXT)
