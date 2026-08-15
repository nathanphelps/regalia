"""Full screen detail views for a mod and for a collection.

These screens gather a decision and hand it back. They do no network work and
they install nothing; the application performs the action they return.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from .model import Mod, State
from .nexus.models import Collection, NexusFile, NexusMod

MOD_URL = "https://www.nexusmods.com/marvelrivals/mods/{mod_id}"
COLLECTION_URL = "https://next.nexusmods.com/marvelrivals/collections/{slug}"

# The application binds these keys for the library. A screen's bindings are
# checked before the application's, so they are claimed here and made to do
# nothing. Without this, pressing "x" on a detail screen would remove whatever
# the library cursor happened to be sitting on.
SHADOWED = ("i", "e", "x", "X", "r", "n", "u", "c", "p", "f", "slash", "space")


def _shadow() -> list[Binding]:
    return [Binding(key, "nothing", "", show=False) for key in SHADOWED]


def size_label(size: int) -> str:
    """Bytes as a short string. Addon files are often well under a megabyte."""
    if size >= 1_048_576:
        return f"{size / 1_048_576:,.0f} MB"
    if size >= 1024:
        return f"{size / 1024:,.0f} KB"
    return f"{size} B"


@dataclass(frozen=True, slots=True)
class ModAction:
    kind: str  # "install", "download", or "browse"
    mod_id: int
    file_id: int | None = None
    file_name: str = ""
    replaces: str | None = None  # the slug of the variant being swapped out


class PartsScreen(Screen[bool]):
    """Choose which pak sets of one archive run.

    Most archives hold one and never reach this screen. The ones that hold
    twenty-four hold them because the author offered choices, and linking all of
    them hands the game two dozen claims on one mesh.
    """

    BINDINGS = [
        Binding("space", "toggle", "turn on/off"),
        Binding("enter", "toggle", "turn on/off", show=False),
        Binding("escape", "back", "back"),
        Binding("a", "all_off", "none"),
        *[Binding(key, "nothing", "", show=False) for key in ("i", "e", "x", "r", "n")],
    ]

    def action_nothing(self) -> None:
        return None

    def __init__(self, mod: Mod) -> None:
        super().__init__()
        self.mod = mod
        self.changed = False

    def compose(self) -> ComposeResult:
        yield Static(Content.styled(self.mod.title, "bold"), id="parts-title")
        yield Static(id="parts-hint")
        yield DataTable(id="parts-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#parts-table", DataTable)
        table.add_columns("on", "group", "part", "writes")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        from . import components

        table = self.query_one("#parts-table", DataTable)
        cursor = table.cursor_row
        table.clear()

        grouped = components.groups(self.mod.components)
        self._order = []
        for number, group in enumerate(grouped, start=1):
            exclusive = len(group) > 1
            for component in group:
                self._order.append(component)
                mark = str(number) if exclusive else "+"
                assets = (
                    f"{len(component.assets)} asset(s)"
                    if component.is_readable
                    else "unreadable"
                )
                table.add_row(
                    Content.styled("on" if component.enabled else "", "$success"),
                    Content.styled(mark, "$accent" if exclusive else "$text-muted"),
                    Content(component.label),
                    Content.styled(assets, "$text-muted"),
                )

        exclusive_groups = sum(1 for group in grouped if len(group) > 1)
        hint = (
            f"{len(self.mod.components)} parts. A number marks a group whose parts "
            "overwrite each other — only one of those can run. A + runs alongside."
            if exclusive_groups
            else f"{len(self.mod.components)} parts, none of which overlap."
        )
        self.query_one("#parts-hint", Static).update(
            Content.styled(hint, "$text-muted")
        )
        if self._order:
            table.move_cursor(row=min(max(cursor, 0), len(self._order) - 1))

    def action_toggle(self) -> None:
        from . import components

        table = self.query_one("#parts-table", DataTable)
        row = table.cursor_row
        if not 0 <= row < len(self._order):
            return
        component = self._order[row]
        if component.enabled:
            component.enabled = False
        else:
            displaced = components.enable(component, self.mod.components)
            if displaced:
                self.notify(f"turned off {len(displaced)} part(s) it would overwrite")
        self.changed = True
        self.refresh_rows()

    def action_all_off(self) -> None:
        for component in self.mod.components:
            component.enabled = False
        self.changed = True
        self.refresh_rows()

    def action_back(self) -> None:
        self.dismiss(self.changed)


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    kind: str  # "apply", "save", or "delete"
    name: str


class ProfilesScreen(Screen[ProfileChoice | None]):
    """Pick a saved set of mods, or record the current one.

    The screen only decides. The application carries the choice out, which keeps
    the linking off the screen and lets it report into the log like every other
    action.
    """

    BINDINGS = [
        Binding("enter", "switch", "switch to it"),
        Binding("s", "save", "save current"),
        Binding("d", "delete", "delete"),
        Binding("escape", "back", "back"),
        *[Binding(key, "nothing", "", show=False) for key in ("i", "e", "x", "r", "n")],
    ]

    def action_nothing(self) -> None:
        return None

    def __init__(self, store, mods: list[Mod]) -> None:
        super().__init__()
        self.store = store
        self.mods = mods

    def compose(self) -> ComposeResult:
        yield Static(Content.styled("PROFILES", "bold"), id="profiles-title")
        yield Static(id="profiles-hint")
        yield DataTable(id="profiles-table", cursor_type="row")
        yield Input(placeholder="name for a new profile", id="profile-name")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#profiles-table", DataTable)
        table.add_columns("profile", "mods", "saved")
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#profiles-table", DataTable)
        table.clear()
        for item in self.store.profiles:
            table.add_row(
                Content(item.name),
                Content.styled(str(item.size), "$text-muted").right(5),
                Content.styled(item.saved.split("T")[0] or "—", "$text-muted"),
            )
        running = sum(1 for mod in self.mods if mod.state is State.INSTALLED)
        self.query_one("#profiles-hint", Static).update(
            Content.styled(
                f"{running} mod(s) running now. "
                "Type a name and press S to save them as a profile.",
                "$text-muted",
            )
        )

    def _current(self) -> str:
        table = self.query_one("#profiles-table", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self.store.profiles):
            return self.store.profiles[row].name
        return ""

    def action_switch(self) -> None:
        if name := self._current():
            self.dismiss(ProfileChoice("apply", name))

    def action_save(self) -> None:
        typed = self.query_one("#profile-name", Input).value.strip()
        name = typed or self._current()
        if name:
            self.dismiss(ProfileChoice("save", name))

    def action_delete(self) -> None:
        if name := self._current():
            self.dismiss(ProfileChoice("delete", name))

    def action_back(self) -> None:
        self.dismiss(None)


@dataclass(frozen=True, slots=True)
class CollectionAction:
    kind: str  # "install" or "browse"
    slug: str
    optional_ids: set[int] = field(default_factory=set)


def _strip_html(text: str) -> str:
    """Nexus summaries carry a little markup. A terminal wants none of it."""
    import re

    cleaned = re.sub(r"<br\s*/?>", "\n", text or "")
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return cleaned.strip()


class ModDetail(Screen[ModAction | None]):
    """One mod, and every file it offers.

    Variants live at the file level for many mods, so this is where a variant is
    chosen. Nothing here changes the library until the choice is returned.
    """

    BINDINGS = [
        Binding("escape", "back", "back"),
        # The table consumes Enter, so the choice really arrives through
        # RowSelected. This entry exists so the footer advertises the key.
        Binding("enter", "choose", "install variant"),
        Binding("d", "download", "download only"),
        Binding("o", "browse", "open in browser"),
        *_shadow(),
    ]

    def action_nothing(self) -> None:
        """Claim a key the library uses so it does nothing here."""

    def __init__(
        self,
        mod: NexusMod,
        files: list[NexusFile],
        held: dict[int, Mod],
        summary: str = "",
    ) -> None:
        super().__init__()
        self.mod = mod
        self.files = files
        self.held = held  # file id -> the local mod holding it
        self.summary = summary or mod.summary

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-page"):
            yield Static("", id="detail-head")
            yield Static("", id="detail-summary")
            yield Static("FILES", classes="section-label")
            yield DataTable(id="detail-files", cursor_type="row", zebra_stripes=False)
            yield Static("", id="detail-foot")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#detail-head", Static).update(
            Content.assemble(
                (f"{self.mod.name}\n", "bold"),
                (
                    f"{self.mod.author} · nexus {self.mod.mod_id} · "
                    f"{self.mod.downloads_label} downloads · "
                    f"{self.mod.endorsements} endorsements"
                    + (" · adult" if self.mod.adult else ""),
                    "$text-muted",
                ),
            )
        )
        summary = _strip_html(self.summary)
        self.query_one("#detail-summary", Static).update(
            Content.styled(summary[:400] or "no description", "$text-muted")
        )

        table = self.query_one("#detail-files", DataTable)
        table.add_column(" ", width=3)
        table.add_column("VARIANT", width=40)
        table.add_column("VERSION", width=10)
        table.add_column("SIZE", width=10)
        table.add_column("CATEGORY", width=14)

        for file in self.files:
            mine = file.file_id in self.held
            table.add_row(
                Content.styled("✓" if mine else " ", "bold $success"),
                Content.styled(file.name, "bold" if mine else ""),
                Content.styled(file.version or "—", "$text-muted"),
                Content(size_label(file.size)).right(10),
                Content.styled(
                    file.category, "$success" if file.is_main else "$text-muted"
                ),
                key=str(file.file_id),
            )

        holding = ", ".join(m.variant or m.title for m in self.held.values())
        self.query_one("#detail-foot", Static).update(
            Content.styled(
                f"installed: {holding}" if holding else "none of these are installed",
                "$text-muted",
            )
        )

    def current_file(self) -> NexusFile | None:
        table = self.query_one("#detail-files", DataTable)
        row = table.cursor_row
        return self.files[row] if 0 <= row < len(self.files) else None

    def action_back(self) -> None:
        self.dismiss(None)

    @on(DataTable.RowSelected, "#detail-files")
    def _row_chosen(self) -> None:
        """The table consumes Enter itself, so the choice arrives as an event."""
        self.action_choose()

    def action_choose(self) -> None:
        file = self.current_file()
        if file is None:
            return
        if file.file_id in self.held:
            self.notify("that variant is already installed")
            return
        # Swapping is the point of a variant list: two variants of one mod claim
        # the same slot, so the one already installed is named for removal.
        replaced = next(iter(self.held.values()), None)
        self.dismiss(
            ModAction(
                "install",
                self.mod.mod_id,
                file.file_id,
                file.name,
                replaced.slug if replaced else None,
            )
        )

    def action_download(self) -> None:
        file = self.current_file()
        if file:
            self.dismiss(
                ModAction("download", self.mod.mod_id, file.file_id, file.name)
            )

    def action_browse(self) -> None:
        self.dismiss(ModAction("browse", self.mod.mod_id))


class CollectionDetail(Screen[CollectionAction | None]):
    """One collection, and every mod inside it.

    Optional members are chosen one at a time here, which the single switch on
    the list screen could not do.
    """

    BINDINGS = [
        Binding("escape", "back", "back"),
        Binding("space", "toggle", "pick optional"),
        Binding("i", "install", "install"),
        Binding("o", "browse", "open in browser"),
        *[
            Binding(k, "nothing", "", show=False)
            for k in ("e", "x", "r", "n", "u", "d", "c", "slash")
        ],
    ]

    def action_nothing(self) -> None:
        """Claim a key the library uses so it does nothing here."""

    def __init__(self, collection: Collection, held: set[tuple[int, int]]) -> None:
        super().__init__()
        self.collection = collection
        self.held = held
        self.chosen: set[int] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-page"):
            yield Static("", id="detail-head")
            yield Static("", id="detail-summary")
            with Horizontal(id="detail-stats"):
                yield Static("", id="detail-counts")
            yield DataTable(id="detail-mods", cursor_type="row", zebra_stripes=False)
        yield Footer()

    def on_mount(self) -> None:
        collection = self.collection
        self.query_one("#detail-head", Static).update(
            Content.assemble(
                (f"{collection.name}\n", "bold"),
                (
                    f"{collection.author} · revision {collection.revision} · "
                    f"updated {collection.updated_label} · "
                    f"{collection.downloads_label} downloads · "
                    f"{collection.endorsements} endorsements · "
                    f"rated {collection.rating_label}",
                    "$text-muted",
                ),
            )
        )
        self.query_one("#detail-summary", Static).update(
            Content.styled(
                _strip_html(collection.summary)[:300] or "no description", "$text-muted"
            )
        )

        table = self.query_one("#detail-mods", DataTable)
        table.add_column(" ", width=3)
        table.add_column("MOD", width=34)
        table.add_column("FILE", width=32)
        table.add_column("VERSION", width=9)
        table.add_column("SIZE", width=9)
        table.add_column("STATUS", width=12)
        self.refresh_rows()

    def refresh_rows(self) -> None:
        table = self.query_one("#detail-mods", DataTable)
        row = table.cursor_row
        table.clear()
        for index, mod in enumerate(self.collection.mods):
            have = (mod.mod_id, mod.file_id) in self.held
            if mod.optional:
                mark = "▉" if mod.file_id in self.chosen else "·"
                mark_style = "$accent" if mod.file_id in self.chosen else "$text-muted"
            else:
                mark = " "
                mark_style = ""
            status = "have" if have else ("optional" if mod.optional else "")
            table.add_row(
                Content.styled(mark, mark_style),
                Content(mod.mod_name),
                Content.styled(mod.file_name, "$text-muted"),
                Content.styled(mod.file_version or "—", "$text-muted"),
                Content(size_label(mod.size)).right(9),
                Content.styled(status, "$success" if have else "$text-muted"),
                key=str(index),
            )
        if self.collection.mods:
            table.move_cursor(row=min(max(row, 0), len(self.collection.mods) - 1))
        self.refresh_counts()

    def refresh_counts(self) -> None:
        wanted = [
            mod
            for mod in self.collection.mods
            if not mod.optional or mod.file_id in self.chosen
        ]
        new = [mod for mod in wanted if (mod.mod_id, mod.file_id) not in self.held]
        size = sum(mod.size for mod in new) / 2**30
        self.query_one("#detail-counts", Static).update(
            Content.assemble(
                (f"{len(wanted)} selected", "bold"),
                (
                    f" · {len(wanted) - len(new)} already held"
                    f" · {len(new)} to download"
                    f" · {size:,.2f} GB"
                    f" · {len(self.collection.optional)} optional available",
                    "$text-muted",
                ),
            )
        )

    def action_toggle(self) -> None:
        table = self.query_one("#detail-mods", DataTable)
        row = table.cursor_row
        if not (0 <= row < len(self.collection.mods)):
            return
        mod = self.collection.mods[row]
        if not mod.optional:
            self.notify("that mod is required, so it cannot be turned off")
            return
        self.chosen.symmetric_difference_update({mod.file_id})
        self.refresh_rows()

    def action_back(self) -> None:
        self.dismiss(None)

    def action_install(self) -> None:
        self.dismiss(
            CollectionAction("install", self.collection.slug, set(self.chosen))
        )

    def action_browse(self) -> None:
        self.dismiss(CollectionAction("browse", self.collection.slug))
