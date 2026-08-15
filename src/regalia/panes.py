"""The Nexus and Collections views.

These widgets only draw. Every network call lives on the application, which runs
it on a worker thread, then calls the `show_*` methods here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.widgets import Button, DataTable, Input, Static

from .credentials import API_KEY_URL
from .nexus.models import Collection, NexusFile, NexusMod


def _recent_cutoff(days: int = 7) -> str:
    """The date a week ago, as Nexus writes dates."""
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")


class KeyPrompt(Vertical):
    """Shown when no API key is set."""

    def compose(self) -> ComposeResult:
        yield Static("NEXUS API KEY", classes="section-label")
        yield Static(
            "Search and identification work without a key. Downloads need one.\n"
            f"Create a personal key at {API_KEY_URL}, then paste it below."
        )
        yield Input(placeholder="paste your key", password=True, id="key-input")
        with Horizontal(classes="row"):
            yield Button("Save key", id="save-key")
            yield Button("Continue without", id="skip-key")


class NexusPane(Vertical):
    """Search and browse Marvel Rivals mods."""

    COLUMNS = (
        ("MOD", 8),
        ("NAME", 38),
        ("AUTHOR", 16),
        ("DOWNLOADS", 11),
        ("STATUS", 16),
    )

    def compose(self) -> ComposeResult:
        yield Input(placeholder="search Nexus", id="nexus-search")
        with Horizontal(id="nexus-modes"):
            yield Button("Trending", id="nexus-trending")
            yield Button("Newest", id="nexus-newest")
            yield Button("Tracked", id="nexus-tracked")
        yield DataTable(id="nexus-table", cursor_type="row", zebra_stripes=False)
        yield Static("", id="nexus-detail")

    def on_mount(self) -> None:
        table = self.query_one("#nexus-table", DataTable)
        for label, width in self.COLUMNS:
            table.add_column(label, width=width)

    def show_mods(self, mods: list[NexusMod], owned: dict[int, str]) -> None:
        table = self.query_one("#nexus-table", DataTable)
        table.clear()
        for mod in mods:
            status = owned.get(mod.mod_id, "")
            style = "$success" if status.startswith("have") else "$warning"
            table.add_row(
                Content.styled(str(mod.mod_id), "$text-muted"),
                Content(mod.name),
                Content.styled(mod.author, "$text-muted"),
                Content(mod.downloads_label).right(11),
                Content.styled(status, style if status else ""),
                key=str(mod.mod_id),
            )

    def show_files(self, mod: NexusMod, files: list[NexusFile]) -> None:
        """Replace the list with the files of one mod."""
        table = self.query_one("#nexus-table", DataTable)
        table.clear()
        for file in files:
            live = file.is_current
            table.add_row(
                Content.styled(str(file.file_id), "$text-muted"),
                Content.styled(file.name, "" if live else "$text-muted"),
                Content.styled(file.version or "—", "$text-muted"),
                Content(file.size_label).right(11),
                Content.styled(
                    file.category, "$success" if file.is_main else "$text-muted"
                ),
                key=f"file:{file.file_id}",
            )

    def show_detail(self, text: Content | str) -> None:
        self.query_one("#nexus-detail", Static).update(text)


class CollectionsPane(Vertical):
    """Browse and install curated collections."""

    COLUMNS = (
        ("NAME", 34),
        ("CURATOR", 14),
        ("MODS", 5),
        ("SIZE", 9),
        ("UPDATED", 11),
        ("DOWNLOADS", 10),
        ("RATING", 13),
    )

    def compose(self) -> ComposeResult:
        yield DataTable(id="collections-table", cursor_type="row", zebra_stripes=False)
        yield Static("", id="collections-detail")
        with Horizontal(id="collections-actions"):
            yield Button("Load manifest", id="load-manifest")
            yield Button("Install", id="install-collection")
            yield Button("Include optional", id="toggle-optional")

    def on_mount(self) -> None:
        table = self.query_one("#collections-table", DataTable)
        for label, width in self.COLUMNS:
            table.add_column(label, width=width)

    def show_collections(self, collections: list[Collection]) -> None:
        table = self.query_one("#collections-table", DataTable)
        table.clear()
        for item in collections:
            # A collection touched in the last week is worth noticing, because
            # these packs are revised constantly as the game patches.
            fresh = item.updated_label >= _recent_cutoff()
            table.add_row(
                Content(item.name),
                Content.styled(item.author, "$text-muted"),
                Content(str(item.mod_count)).right(5),
                Content(item.size_label).right(9),
                Content.styled(
                    item.updated_label, "bold $success" if fresh else "$text-muted"
                ).right(11),
                Content(item.downloads_label).right(10),
                Content.styled(item.rating_label, "$text-muted").right(13),
                key=item.slug,
            )

    def show_detail(self, text: Content | str) -> None:
        self.query_one("#collections-detail", Static).update(text)
