"""Shared panel chrome and session-only workspace controls."""

from textual import events
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Static

PANEL_IDS = (
    "overview",
    "watchlist-panel",
    "markets-panel",
    "account-panel",
    "contract-panel",
    "book-panel",
    "tape-panel",
)


class PanelChrome:
    async def on_mount(self) -> None:
        controls = Horizontal(classes="panel-actions")
        await self.mount(controls, before=0)
        for action, icon, hint in (
            ("expand", "⛶", "Expand panel"),
            ("reset", "↺", "Reset size and scroll"),
            ("hide", "×", "Hide panel; number key restores it"),
        ):
            await controls.mount(
                Button(icon, id=f"{self.id}-{action}", classes="panel-action", tooltip=hint)
            )

    def on_click(self, event: events.Click) -> None:
        self.app.activate_panel(self.id)
        if event.widget is self or isinstance(event.widget, Static):
            self.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.app.panel_action(self.id, event.button.id.rsplit("-", 1)[1])


class Panel(PanelChrome, Vertical, can_focus=True):
    pass


class ScrollPanel(PanelChrome, VerticalScroll, can_focus=True):
    pass


class PanelWorkspace:
    """Mixed into the dashboard to keep panel state separate from market reads."""

    def activate_panel(self, panel_id):
        for name in PANEL_IDS:
            self.dashboard_query(f"#{name}").set_class(name == panel_id, "active-panel")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        widget = event.widget
        while widget is not None and widget.id not in PANEL_IDS:
            widget = widget.parent
        self.activate_panel(widget.id if widget else None)

    def action_panel(self, number: int) -> None:
        name = PANEL_IDS[number - 1]
        hidden = name in self.hidden_panels
        if not hidden and len(self.hidden_panels) == len(PANEL_IDS) - 1:
            self.notify("Keep at least one panel visible.")
            return
        if hidden:
            self.hidden_panels.remove(name)
        else:
            self.hidden_panels.add(name)
        self.expanded_panel = None
        self.apply_layout()
        self.focus_visible_panel(name if hidden else None)

    def focus_visible_panel(self, preferred=None):
        name = preferred or next(name for name in PANEL_IDS if name not in self.hidden_panels)
        panel = self.dashboard_query(f"#{name}")
        panel.focus()
        self.activate_panel(name)
        panel.scroll_visible()

    def panel_action(self, name, action):
        if action == "hide":
            self.action_panel(PANEL_IDS.index(name) + 1)
            return
        if action == "expand":
            self.expanded_panel = None if self.expanded_panel == name else name
        elif action == "reset":
            self.expanded_panel = None
            panel = self.dashboard_query(f"#{name}")
            panel.scroll_home(animate=False)
            for table in panel.query(DataTable):
                table.scroll_home(animate=False)
                table.move_cursor(row=0, column=0)
        self.apply_layout()
        self.focus_visible_panel(name)

    def apply_panel_layout(self):
        self.set_class(self.expanded_panel is not None, "panel-expanded")
        for name in PANEL_IDS:
            panel = self.dashboard_query(f"#{name}")
            panel.styles.display = (
                ("block" if name == self.expanded_panel else "none")
                if self.expanded_panel
                else ("none" if name in self.hidden_panels else None)
            )
        for column in ("sidebar", "workspace", "inspector"):
            container = self.dashboard_query(f"#{column}")
            container.styles.display = (
                "none"
                if not any(panel.display for panel in container.query(".panel"))
                else "block"
                if self.expanded_panel
                else None
            )
