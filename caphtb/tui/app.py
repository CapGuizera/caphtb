"""Textual application entrypoint for `caphtb tui`."""

from __future__ import annotations

from textual.app import App
from textual.theme import Theme

from ..api import HTBClient, HTBError
from ..config import Config
from .screens import DashboardScreen

# Custom palettes. "caphtb" mirrors the Rich CLI (caphtb/ui.py): HTB green on
# dark navy, so `caphtb` and `caphtb tui` read as one product. "ember" is a
# warm navy/amber alternative for whoever finds the green too loud.
CUSTOM_THEMES = [
    Theme(
        name="caphtb",
        primary="#9FEF00",      # HTB green - titles, borders, focus
        secondary="#7C8B9C",    # muted slate - filters, hints
        accent="#9FEF00",
        warning="#E3B341",
        error="#FF6B6B",
        success="#9FEF00",
        foreground="#D8E4EE",
        background="#111927",   # HTB_BG from ui.py
        surface="#16202E",
        panel="#1B2636",
        boost="#22314A",
        dark=True,
    ),
    Theme(
        name="ember",
        primary="#F2A65A",
        secondary="#8B93A7",
        accent="#F2A65A",
        warning="#E3B341",
        error="#FF6B6B",
        success="#9ECE6A",
        foreground="#E6E0D4",
        background="#0C1220",
        surface="#111A2C",
        panel="#16223A",
        boost="#1F2E4D",
        dark=True,
    ),
]

# Rotation order for the theme cycler: our palettes first, then a curated set
# of Textual built-ins (already registered by the framework).
THEME_CYCLE = [
    "caphtb",
    "ember",
    "nord",
    "gruvbox",
    "catppuccin-mocha",
    "dracula",
    "tokyo-night",
]


class CaphtbTUI(App[None]):
    """Main Textual app."""

    TITLE = "caphtb"
    CSS_PATH = "theme.tcss"

    def __init__(self, client: HTBClient, cfg: Config) -> None:
        super().__init__()
        self.client = client
        self.cfg = cfg
        for theme in CUSTOM_THEMES:
            self.register_theme(theme)
        saved = cfg.extra.get("theme") if isinstance(cfg.extra, dict) else None
        self.theme = saved if saved in THEME_CYCLE else "caphtb"

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen(self.client, self.cfg))
        self.sync_terminal_background()

    def sync_terminal_background(self) -> None:
        """Repaint the terminal background (kitty/OSC 11) to match the theme.

        Textual only paints the cell grid; the terminal padding around it keeps
        the emulator's own background color. Without this, switching themes
        leaves a ring in the old color around the app.
        """
        bg = self.theme_variables.get("background")
        if not bg:
            return
        try:
            import sys

            sys.__stdout__.write(f"\x1b]11;{bg}\x1b\\")
            sys.__stdout__.flush()
        except (OSError, AttributeError, ValueError):
            pass

    def cycle_theme(self) -> str:
        """Switch to the next palette and persist the choice in the config."""
        try:
            index = THEME_CYCLE.index(self.theme)
        except ValueError:
            index = -1
        self.theme = THEME_CYCLE[(index + 1) % len(THEME_CYCLE)]
        if not isinstance(self.cfg.extra, dict):
            self.cfg.extra = {}
        self.cfg.extra["theme"] = self.theme
        try:
            self.cfg.save()
        except OSError:
            pass
        self.call_after_refresh(self.sync_terminal_background)
        return self.theme


def run_tui() -> None:
    """Bootstrap and run the Textual TUI."""
    cfg = Config.load()
    client = HTBClient(cfg)
    try:
        CaphtbTUI(client, cfg).run()
    finally:
        # Reset the terminal background (OSC 111) for whoever ran this from a
        # regular shell, so their terminal does not keep the app's color.
        try:
            import sys

            sys.__stdout__.write("\x1b]111\x1b\\")
            sys.__stdout__.flush()
        except (OSError, AttributeError, ValueError):
            pass


__all__ = ["CaphtbTUI", "run_tui", "HTBError"]
