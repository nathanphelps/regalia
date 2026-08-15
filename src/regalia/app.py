"""The regalia terminal interface."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from . import conflicts, credentials, installer, library, patch, steam
from .catalog import Catalog
from .config import Config
from .environment import steam_installs
from .model import Mod, State
from .nexus import NexusClient, NexusError, UserInfo
from .nexus import collections as nexus_collections
from .nexus.download import download_file
from .nexus.identify import identify_paths
from .nexus.models import Collection, NexusMod
from .nexus.updates import check as check_updates
from .panes import CollectionsPane, KeyPrompt, NexusPane
from .paths import CONFIG_FILE, DATA_DIR, GameNotFound, GamePaths, discover_game
from .screens import (
    CollectionAction,
    CollectionDetail,
    ModAction,
    ModDetail,
    PartsScreen,
)

PARCHMENT = Theme(
    name="parchment",
    primary="#4b4bd6",
    secondary="#6c6ce0",
    accent="#6c6ce0",
    foreground="#1a1a1a",
    background="#ece8dc",
    surface="#e4dfd0",
    panel="#d9d3c0",
    success="#2f6f4f",
    warning="#9a6b1f",
    error="#a32b2b",
    dark=False,
    variables={"text-muted": "#7c7666", "block-cursor-foreground": "#ece8dc"},
)

INK = Theme(
    name="ink",
    primary="#8f92e8",
    secondary="#6c6ce0",
    accent="#8f92e8",
    foreground="#ece8dc",
    background="#1a1a1a",
    surface="#232320",
    panel="#2c2c28",
    success="#6fbf8f",
    warning="#d8a341",
    error="#e06666",
    dark=True,
    variables={"text-muted": "#8a8578", "block-cursor-foreground": "#1a1a1a"},
)

STATE_STYLE = {
    State.INSTALLED: ("INSTALLED", "bold $success"),
    State.DISABLED: ("DISABLED", "$text-muted"),
    State.BROKEN: ("BROKEN", "bold $error"),
    State.UNSUPPORTED: ("UNSUPPORTED", "$error"),
    State.AVAILABLE: ("", ""),
}


class ConfirmScreen(ModalScreen[bool]):
    """A yes or no question."""

    def __init__(self, title: str, body: str, confirm: str = "Overwrite") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._confirm = confirm

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title, id="dialog-title")
            yield Static(self._body)
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self._confirm, id="confirm", classes="-danger")

    @on(Button.Pressed)
    def _answer(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class RegaliaApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "regalia"

    BINDINGS = [
        ("space", "toggle_select", "pick"),
        ("i", "install", "install"),
        ("d", "disable", "disable"),
        ("e", "enable", "enable"),
        ("x", "remove", "remove"),
        ("p", "parts", "parts"),
        ("r", "rescan", "rescan"),
        ("n", "identify", "identify"),
        ("u", "check_updates", "updates"),
        ("c", "clean", "clean"),
        ("slash", "focus_search", "search"),
        ("q", "quit", "quit"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.catalog = Catalog.load()
        self.selected: set[str] = set()
        self.warnings: dict[str, list[conflicts.Warning_]] = {}
        self.game: GamePaths | None = None
        self.game_error: str = ""
        self._rows: dict[str, list[Mod]] = {"library": [], "installed": []}

        self.client = NexusClient(credentials.load_key())
        self.account: UserInfo | None = None
        self.nexus_error: str = ""
        self.nexus_rows: list[NexusMod] = []
        self.nexus_files_for: NexusMod | None = None
        self.collection_rows: list[Collection] = []
        self.manifest: Collection | None = None
        self.include_optional = False
        self._cancel_run = False
        self._scan_stamp = 0.0

    # -- layout ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="masthead"):
            yield Static("R E G A L I A", id="wordmark")
            yield Static("", id="status")
        yield Static("─" * 400, id="rule-top")

        with TabbedContent(initial="library"):
            with TabPane("LIBRARY", id="library"):
                yield Input(placeholder="search heroes and variants", id="search")
                yield DataTable(id="table", cursor_type="row", zebra_stripes=False)
                yield Static("", id="detail")
            with TabPane("INSTALLED", id="installed"):
                yield DataTable(
                    id="installed-table", cursor_type="row", zebra_stripes=False
                )
                yield Static("", id="installed-detail")
                with Horizontal(id="installed-actions"):
                    yield Button("Repair links", id="repair")
                    yield Button("Disable all", id="disable-all")
                    yield Button("Clean unfinished", id="clean-partials")
            with TabPane("NEXUS", id="nexus"):
                yield VerticalScroll(id="nexus-body")
            with TabPane("COLLECTIONS", id="collections"):
                yield CollectionsPane(id="collections-pane")
            with TabPane("PATCH", id="patch"):
                yield VerticalScroll(id="patch-body")
            with TabPane("SETUP", id="setup"):
                yield VerticalScroll(id="setup-body")
            with TabPane("LOG", id="log"):
                yield RichLog(id="logview", markup=True, wrap=True)

        with Horizontal(id="progress-row"):
            yield Static("", id="progress-label")
            yield ProgressBar(total=100, show_eta=False, id="progress")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(PARCHMENT)
        self.register_theme(INK)
        self.theme = "ink" if self.config.dark else "parchment"

        # Only the two mod tables get these columns. A bare query(DataTable)
        # would also reach the Nexus and Collections tables, which build their
        # own and would end up with both sets.
        for selector in ("#table", "#installed-table"):
            table = self.query_one(selector, DataTable)
            table.add_column("HERO", key="hero", width=20)
            table.add_column("VARIANT", key="variant", width=32)
            table.add_column("VERSION", key="version", width=8)
            table.add_column("SIZE", key="size", width=8)
            table.add_column("STATE", key="state", width=15)

        try:
            self.game = discover_game(
                self.config.game_root, steam_installs(self.config.steam_root)
            )
        except GameNotFound as error:
            self.game_error = str(error)

        if self.game is not None:
            from . import migrate

            for step in migrate.run(self.game.mods):
                self.log_line(f"[dim]moved:[/] {step}")

        self.refresh_setup()

        self.log_line(
            f"[dim]game:[/] {self.game.root if self.game else self.game_error}"
        )
        if warning := credentials.file_mode_warning():
            self.log_line(f"[yellow]security[/] {warning}")
        self.action_rescan()

        if self.client.api_key:
            self.validate_account()
        # New archives can arrive from the browser through the nxm:// handler,
        # which is a separate process. Watching the folder is simpler than any
        # channel between the two.
        self.set_interval(5.0, self.poll_scan_dirs)

    # -- setup ----------------------------------------------------------

    COLOURS = {"ok": "$success", "warn": "$warning", "blocked": "$error"}

    def refresh_setup(self) -> None:
        """Fill the SETUP tab, and open it when the tool cannot work yet.

        The checks come from `readiness`, the same source the doctor command
        prints, so the two can never disagree.
        """
        from .readiness import run_checks

        report = run_checks(self.config)
        body = self.query_one("#setup-body", VerticalScroll)
        body.remove_children()

        lines = [
            "[b]What this machine is ready to do.[/]",
            "Run [b]regalia doctor[/] for the same report with version details.",
            "",
        ]
        for check in report.checks:
            colour = self.COLOURS[check.level.value]
            lines.append(
                f"[{colour}]{check.level.mark}[/] [b]{check.name}[/] — {check.detail}"
            )
            if check.remedy:
                lines.append(f"    [dim]{check.remedy}[/]")
        lines.append("")
        lines.append(f"Settings live in [b]{CONFIG_FILE}[/].")
        body.mount(Static("\n".join(lines), id="setup-text"))

        if report.needs_setup:
            self.query_one(TabbedContent).active = "setup"

    # -- helpers --------------------------------------------------------

    def log_line(self, text: str) -> None:
        self.query_one("#logview", RichLog).write(text)

    def active_pane(self) -> str:
        pane = self.query_one(TabbedContent).active
        return pane if pane in ("library", "installed") else "library"

    def active_table(self) -> DataTable:
        suffix = "" if self.active_pane() == "library" else "installed-"
        return self.query_one(f"#{suffix}table", DataTable)

    def current_mod(self) -> Mod | None:
        rows = self._rows.get(self.active_pane(), [])
        cursor = self.active_table().cursor_row
        if cursor < 0 or cursor >= len(rows):
            return None
        return rows[cursor]

    def targets(self) -> list[Mod]:
        """The selected mods, or the mod under the cursor when none is picked."""
        if self.selected:
            return [m for m in self.catalog.mods if m.slug in self.selected]
        mod = self.current_mod()
        return [mod] if mod else []

    def refresh_table(self) -> None:
        query = self.query_one("#search", Input).value
        self._fill("library", self.catalog.search(query))
        self._fill("installed", [m for m in self.catalog.mods if m.is_present])
        self.refresh_detail()
        self.refresh_status()

    def _fill(self, pane: str, mods: list[Mod]) -> None:
        suffix = "" if pane == "library" else "installed-"
        table = self.query_one(f"#{suffix}table", DataTable)
        cursor = table.cursor_row
        table.clear()
        self._rows[pane] = mods

        for mod in mods:
            label, style = STATE_STYLE[mod.state]
            badge = conflicts.badge(self.warnings.get(mod.slug, []))
            marker = "▉ " if mod.slug in self.selected else "  "
            tick = " ✓" if mod.verified else ""
            table.add_row(
                Content.assemble(
                    (marker, "$accent"), (mod.hero, "bold"), (tick, "$success")
                ),
                Content(mod.variant),
                Content.styled(mod.version_label, "$text-muted"),
                Content(mod.size_label).right(8),
                Content.styled(f"{badge} {label}".strip(), style),
                key=mod.slug,
            )
        if mods:
            table.move_cursor(row=min(max(cursor, 0), len(mods) - 1))

    def refresh_detail(self) -> None:
        pane = self.active_pane()
        suffix = "" if pane == "library" else "installed-"
        detail = self.query_one(f"#{suffix}detail", Static)
        mod = self.current_mod()
        if mod is None:
            empty = "no mods found" if pane == "library" else "nothing installed yet"
            detail.update(Content.styled(empty, "$text-muted"))
            return

        parts: list[tuple[str, str]] = [(f"{mod.files_label}\n", "$text-muted")]
        if mod.nexus:
            tail = f" · {', '.join(mod.collections)}" if mod.collections else ""
            parts.append(
                (
                    f"{mod.nexus.mod_name} · {mod.nexus.author} · "
                    f"nexus {mod.nexus.mod_id}{tail}\n",
                    "$text-muted",
                )
            )
        else:
            parts.append((f"{mod.source.name}\n", "$text-muted"))
        for warning in self.warnings.get(mod.slug, []):
            symbol = conflicts.SYMBOLS[warning.kind]
            style = "bold $error" if warning.kind == "conflict" else "$warning"
            parts.append((f"{symbol} {warning.text}\n", style))
        detail.update(Content.assemble(*parts))

    def refresh_status(self) -> None:
        state = patch.status(self.game).summary if self.game else "no game"
        style = "$success" if state == "patch ok" else "$error"
        total = len(self.catalog.mods)

        parts: list[tuple[str, str] | str] = [(f"● {state}", f"bold {style}")]
        if self.account:
            parts.append(f"   {self.account.name} ")
            parts.append((self.account.badge, "bold $accent"))
            if quota := self.client.rate.label:
                parts.append(("  " + quota, "$text-muted"))
        elif self.client.api_key:
            parts.append(("   nexus ready", "$text-muted"))
        else:
            parts.append(("   no nexus key", "$text-muted"))
        parts.append(f"   {self.catalog.installed_count}/{total} installed")
        self.query_one("#status", Static).update(Content.assemble(*parts))

    def poll_scan_dirs(self) -> None:
        """Rescan when an archive appears from outside the interface."""
        stamp = 0.0
        for directory in self.config.scan_dirs:
            if directory.is_dir():
                stamp = max(stamp, directory.stat().st_mtime)
        if self._scan_stamp and stamp > self._scan_stamp:
            self.log_line("[dim]scan[/] the download folder changed")
            self.action_rescan()
        self._scan_stamp = stamp

    def set_busy(self, label: str | None, percent: int = 0) -> None:
        row = self.query_one("#progress-row")
        row.set_class(label is not None, "busy")
        if label is not None:
            self.query_one("#progress-label", Static).update(label)
            self.query_one("#progress", ProgressBar).update(progress=percent)

    # -- events ---------------------------------------------------------

    @on(Input.Changed, "#search")
    def _search_changed(self) -> None:
        self.refresh_table()

    @on(DataTable.RowHighlighted)
    def _row_moved(self) -> None:
        self.refresh_detail()

    @on(TabbedContent.TabActivated)
    async def _tab_changed(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "patch":
            await self.refresh_patch()
        elif event.pane.id == "nexus":
            await self.refresh_nexus()
        elif event.pane.id == "collections":
            if not self.collection_rows:
                self.load_collections()
        elif event.pane.id in ("library", "installed"):
            self.refresh_detail()

    @on(DataTable.RowSelected, "#nexus-table")
    def _nexus_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value or "")
        if key.isdigit():
            self.open_mod_detail(int(key))

    @on(DataTable.RowSelected, "#table")
    @on(DataTable.RowSelected, "#installed-table")
    def _library_row_selected(self) -> None:
        """Enter on a library row opens the mod behind it."""
        mod = self.current_mod()
        if mod is None:
            return
        if not mod.nexus:
            self.notify("Press n to identify this mod against Nexus first")
            return
        self.open_mod_detail(mod.nexus.mod_id)

    @work(thread=True, exclusive=True, group="nexus")
    def open_mod_detail(self, mod_id: int) -> None:
        """Gather everything the detail screen needs, then show it."""
        try:
            files = self.client.files(mod_id)
            known = next((m for m in self.nexus_rows if m.mod_id == mod_id), None)
            if known is None:
                found = self.client.mod(mod_id)
                known = found or NexusMod(
                    mod_id=mod_id, name=f"mod {mod_id}", author=""
                )
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))
            return

        live = [file for file in files if file.is_current] or files
        held = {
            mod.nexus.file_id: mod
            for mod in self.catalog.mods
            if mod.nexus
            and mod.nexus.mod_id == mod_id
            and mod.nexus.file_id
            and mod.is_present
        }
        self.call_from_thread(self._push_mod_detail, known, live, held)

    def _push_mod_detail(self, mod: NexusMod, files: list, held: dict) -> None:
        self.set_busy(None)
        self.push_screen(ModDetail(mod, files, held), self._mod_action)

    def _mod_action(self, action: ModAction | None) -> None:
        if action is None:
            return
        if action.kind == "browse":
            self.open_url(
                f"https://www.nexusmods.com/marvelrivals/mods/{action.mod_id}"
            )
            return
        if action.file_id is None:
            return
        replaced = self.catalog.by_slug(action.replaces) if action.replaces else None
        self.fetch_variant(
            action.mod_id, action.file_id, action.kind == "install", replaced
        )

    @work(thread=True, exclusive=True, group="nexus")
    def fetch_variant(
        self, mod_id: int, file_id: int, install_after: bool, replaced: Mod | None
    ) -> None:
        self.call_from_thread(self.set_busy, "downloading variant…", 0)

        def progress(done: int, total: int) -> None:
            self.call_from_thread(
                self.set_busy,
                "downloading variant…",
                int(done * 100 / total) if total else 0,
            )

        try:
            path = download_file(
                self.client,
                mod_id,
                file_id,
                library.ensure(),
                on_progress=progress,
            )
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))
            return
        self.call_from_thread(self._variant_ready, path, install_after, replaced)

    def _variant_ready(self, path, install_after: bool, replaced: Mod | None) -> None:
        assert self.game is not None
        self.set_busy(None)
        self.log_line(f"[green]nexus[/] fetched {path.name}")
        self.catalog.rescan(self.config.scan_dirs, self.game.mods)

        if install_after:
            # A variant replaces the one it supersedes. Both claim the same hero
            # slot, so leaving the old one installed would make the result
            # depend on load order rather than on the choice just made.
            if replaced and replaced.is_present:
                installer.remove(replaced, self.game.mods)
                self.log_line(f"[yellow]swap[/] removed {replaced.title}")
            fresh = next((mod for mod in self.catalog.mods if mod.source == path), None)
            if fresh:
                self._run_install([fresh], overwrite=True)
                return
        self._finish_batch(f"fetched {path.name}")

    def open_url(self, url: str) -> None:
        import webbrowser

        webbrowser.open(url)
        self.notify("opened in your browser")

    @work(thread=True, exclusive=True, group="nexus")
    def download_one(self, file_id: int) -> None:
        mod = self.nexus_files_for
        if mod is None:
            return
        self.call_from_thread(self.set_busy, f"downloading {mod.name[:36]}", 0)

        def progress(done: int, total: int) -> None:
            self.call_from_thread(
                self.set_busy,
                f"downloading {mod.name[:36]}",
                int(done * 100 / total) if total else 0,
            )

        try:
            path = download_file(
                self.client,
                mod.mod_id,
                file_id,
                library.ensure(),
                on_progress=progress,
            )
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))
            return
        self.call_from_thread(self._downloaded, path)

    def _downloaded(self, path) -> None:
        self.set_busy(None)
        self.log_line(f"[green]nexus[/] fetched {path.name}")
        self.action_rescan()
        self.notify(f"downloaded {path.name}")

    @on(Button.Pressed, "#repair")
    def _repair_pressed(self) -> None:
        self.action_repair()

    @on(Button.Pressed, "#disable-all")
    def _disable_all(self) -> None:
        self.selected = {
            m.slug for m in self.catalog.mods if m.state is State.INSTALLED
        }
        self.action_disable()

    @on(Button.Pressed, "#clean-partials")
    def _clean_partials(self) -> None:
        self.action_clean()

    def action_clean(self) -> None:
        """Delete downloads that never finished."""
        from . import archive

        partials = archive.find_partials(self.config.scan_dirs)
        if not partials:
            self.notify("no unfinished downloads")
            return
        total = sum(p.stat().st_size for p in partials)
        names = "\n".join(f"  {p.name[:64]}" for p in partials[:8])
        self.push_screen(
            ConfirmScreen(
                "Delete unfinished downloads",
                f"{len(partials)} file(s), {total / 2**20:,.0f} MB.\n"
                "These are the remains of runs that stopped early.\n\n"
                + names
                + ("\n  …" if len(partials) > 8 else ""),
                confirm="Delete",
            ),
            lambda ok: self._do_clean() if ok else None,
        )

    def _do_clean(self) -> None:
        from . import archive

        removed, freed = archive.clean_partials(self.config.scan_dirs)
        self.log_line(f"[yellow]clean[/] removed {removed} part file(s)")
        self.notify(f"removed {removed} file(s), freed {freed / 2**20:,.0f} MB")

    # -- actions --------------------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_toggle_select(self) -> None:
        mod = self.current_mod()
        if mod is None:
            return
        self.selected.symmetric_difference_update({mod.slug})
        table = self.active_table()
        row = table.cursor_row
        self.refresh_table()
        rows = self._rows[self.active_pane()]
        table.move_cursor(row=min(row + 1, len(rows) - 1))

    def action_rescan(self) -> None:
        if self.game is None:
            self.notify(self.game_error, severity="error", timeout=10)
            return
        for line in self.catalog.rescan(self.config.scan_dirs, self.game.mods):
            self.log_line(f"[dim]scan[/] {line}")
        self.warnings = conflicts.check(self.catalog.mods)
        self.catalog.save()
        self.refresh_table()
        self.log_line(f"[dim]scan[/] {len(self.catalog.mods)} mods known")

    def action_install(self) -> None:
        if self.game is None:
            return
        pending = [m for m in self.targets() if m.state is not State.UNSUPPORTED]
        if not pending:
            self.notify("nothing to install")
            return

        blocked = self._existing_real_files(pending)
        if blocked:
            self.push_screen(
                ConfirmScreen(
                    "Files already in ~mods",
                    "These are real files, not links made by this tool:\n\n"
                    + "\n".join(f"  {name}" for name in blocked[:8])
                    + ("\n  …" if len(blocked) > 8 else ""),
                ),
                lambda ok: self._run_install(pending, True) if ok else None,
            )
        else:
            self._run_install(pending, False)

    def _existing_real_files(self, mods: list[Mod]) -> list[str]:
        assert self.game is not None
        found: list[str] = []
        for mod in mods:
            for name in mod.files:
                target = self.game.mods / name
                if target.exists() and not target.is_symlink():
                    found.append(name)
        return found

    def _run_install(self, mods: list[Mod], overwrite: bool) -> None:
        self.set_busy("preparing…", 0)
        self._install_worker(mods, overwrite)

    @work(thread=True, exclusive=True)
    def _install_worker(self, mods: list[Mod], overwrite: bool) -> None:
        assert self.game is not None
        for index, mod in enumerate(mods, start=1):
            prefix = f"[{index}/{len(mods)}] {mod.title}"
            self.call_from_thread(self.set_busy, f"extracting {prefix}", 0)
            try:
                installer.install(
                    mod,
                    self.game.mods,
                    on_progress=lambda pct, p=prefix: self.call_from_thread(
                        self.set_busy, f"extracting {p}", pct
                    ),
                    overwrite=overwrite,
                )
                self.call_from_thread(self.log_line, f"[green]installed[/] {mod.title}")
            except Exception as error:
                mod.note = str(error)
                self.call_from_thread(
                    self.log_line, f"[red]failed[/] {mod.title}: {error}"
                )
        self.call_from_thread(self._finish_batch, f"installed {len(mods)} mod(s)")

    def _finish_batch(self, message: str) -> None:
        assert self.game is not None
        self.set_busy(None)
        self.selected.clear()
        self.catalog.verify(self.game.mods)
        self.warnings = conflicts.check(self.catalog.mods)
        self.catalog.save()
        self.refresh_table()
        self.notify(message)

    def action_disable(self) -> None:
        if self.game is None:
            return
        count = 0
        for mod in self.targets():
            if mod.state in (State.INSTALLED, State.BROKEN):
                installer.unlink(mod, self.game.mods)
                self.log_line(f"[yellow]disabled[/] {mod.title}")
                count += 1
        self._finish_batch(f"disabled {count} mod(s)")

    def action_enable(self) -> None:
        if self.game is None:
            return
        pending = [
            m for m in self.targets() if m.state in (State.DISABLED, State.BROKEN)
        ]
        if pending:
            self._run_install(pending, overwrite=True)
        else:
            self.action_install()

    def action_parts(self) -> None:
        """Choose which pak sets of the mod under the cursor run."""
        mod = self.current_mod()
        if mod is None:
            return
        if not mod.has_choices:
            self.notify("this mod has only one part")
            return

        def applied(changed: bool | None) -> None:
            if not changed:
                return
            if self.game and mod.is_present:
                try:
                    installer.apply_selection(mod, self.game.mods)
                except OSError as error:
                    self.notify(str(error), severity="error")
            self.catalog.save()
            self.log_line(f"[green]parts[/] {mod.title}: {len(mod.active)} running")
            self.refresh_table()

        self.push_screen(PartsScreen(mod), applied)

    def action_remove(self) -> None:
        if self.game is None:
            return
        pending = [m for m in self.targets() if m.is_present]
        if not pending:
            self.notify("nothing to remove")
            return
        names = "\n".join(f"  {m.title}" for m in pending[:8])
        self.push_screen(
            ConfirmScreen(
                "Remove extracted files",
                f"The archives stay in your downloads folder.\n\n{names}",
                confirm="Remove",
            ),
            lambda ok: self._do_remove(pending) if ok else None,
        )

    def _do_remove(self, mods: list[Mod]) -> None:
        assert self.game is not None
        for mod in mods:
            installer.remove(mod, self.game.mods)
            self.log_line(f"[red]removed[/] {mod.title}")
        self._finish_batch(f"removed {len(mods)} mod(s)")

    def action_repair(self) -> None:
        if self.game is None:
            return
        fixed = installer.repair(self.catalog.mods, self.game.mods)
        self._finish_batch(f"relinked {fixed} mod(s)")

    # -- patch tab ------------------------------------------------------

    async def refresh_patch(self) -> None:
        body = self.query_one("#patch-body", VerticalScroll)
        # The removal is queued on the message pump, so it must finish before the
        # rebuild. Without the await, the second visit to this tab mounts a
        # second widget with the same id and Textual rejects it.
        await body.remove_children()
        if self.game is None:
            body.mount(Static(self.game_error))
            return

        state = patch.status(self.game)
        found = self.catalog.patch_archive

        def check(ok: bool, text: str) -> Static:
            mark = "✓" if ok else "✗"
            style = "$success" if ok else "$error"
            return Static(
                Content.styled(f"{mark}  {text}", f"bold {style}"),
                classes="check-line",
            )

        body.mount(Static("WHY THIS IS NEEDED", classes="section-label"))
        body.mount(
            Static(
                "Marvel Rivals refuses unsigned pak files. The bypass is an ASI "
                "plugin that Ultimate ASI Loader injects through a stand-in "
                "dsound.dll. No mod loads until all three checks below pass."
            )
        )

        body.mount(Static("STATUS", classes="section-label"))
        body.mount(check(state.loader_installed, "dsound.dll in Binaries/Win64"))
        body.mount(check(state.plugin_installed, "signature bypass plugin present"))
        body.mount(check(state.override_set, "Proton DLL override in launch options"))

        body.mount(Static("STEAM LAUNCH OPTIONS", classes="section-label"))
        current = state.launch_options
        body.mount(
            Static(
                Content.assemble(
                    ("now: ", "$text-muted"),
                    (current if current else "(none set)", "bold"),
                )
            )
        )
        if not state.override_set:
            body.mount(
                Static(
                    "Wine ignores a native dsound.dll unless the launch options "
                    "say so. The wizard can set this for you:"
                )
            )
            body.mount(Static(steam.merge_override(current or ""), id="override-box"))
            body.mount(
                Static(
                    Content.styled(
                        "Steam holds this file open and rewrites it when it quits, "
                        "so the wizard closes Steam first and backs the file up. "
                        "Your other launch options are kept.",
                        "$text-muted",
                    )
                )
            )

        actions = Horizontal(id="patch-actions")
        body.mount(actions)
        if not (state.loader_installed and state.plugin_installed):
            label = "Install patch" if found else "No patch archive found"
            button = Button(label, id="install-patch")
            button.disabled = found is None
            actions.mount(button)
        else:
            actions.mount(Button("Remove patch", id="remove-patch", classes="-danger"))
        if not state.override_set:
            label = (
                "Close Steam and set options"
                if steam.is_running()
                else "Set launch options"
            )
            actions.mount(Button(label, id="set-launch-options"))
        actions.mount(Button("Re-check", id="recheck-patch"))

    @on(Button.Pressed, "#install-patch")
    async def _install_patch(self) -> None:
        assert self.game is not None and self.catalog.patch_archive is not None
        try:
            placed = patch.install(
                self.game, self.catalog.patch_archive, DATA_DIR / "staging"
            )
            self.log_line(f"[green]patch[/] installed {', '.join(placed)}")
            self.notify("patch installed")
        except Exception as error:
            self.log_line(f"[red]patch[/] {error}")
            self.notify(str(error), severity="error", timeout=10)
        await self.refresh_patch()
        self.refresh_status()

    @on(Button.Pressed, "#remove-patch")
    async def _remove_patch(self) -> None:
        assert self.game is not None
        removed = patch.uninstall(self.game)
        self.log_line(f"[yellow]patch[/] removed {', '.join(removed) or 'nothing'}")
        await self.refresh_patch()
        self.refresh_status()

    @on(Button.Pressed, "#recheck-patch")
    async def _recheck_patch(self) -> None:
        await self.refresh_patch()
        self.refresh_status()

    # -- steam ----------------------------------------------------------

    @on(Button.Pressed, "#set-launch-options")
    def _ask_launch_options(self) -> None:
        wanted = steam.merge_override(steam.read_current() or "")
        running = steam.is_running()
        body = (
            "Steam is running and must close first, or it will overwrite the "
            "change when it quits.\n\n"
            if running
            else ""
        ) + f"New value:\n  {wanted}\n\nThe settings file is backed up first."
        self.push_screen(
            ConfirmScreen(
                "Close Steam and set launch options"
                if running
                else "Set launch options",
                body,
                confirm="Do it",
            ),
            lambda ok: self.write_launch_options() if ok else None,
        )

    @work(thread=True, exclusive=True, group="steam")
    def write_launch_options(self) -> None:
        was_running = steam.is_running()
        if was_running:
            self.call_from_thread(self.set_busy, "closing Steam…", 0)
            if not steam.shutdown():
                self.call_from_thread(
                    self._steam_failed,
                    "Steam would not close, so nothing was changed.",
                )
                return

        self.call_from_thread(self.set_busy, "writing launch options…", 50)
        try:
            result = steam.apply_override()
        except steam.SteamError as error:
            self.call_from_thread(self._steam_failed, str(error))
            return
        self.call_from_thread(self._steam_written, result, was_running)

    def _steam_failed(self, message: str) -> None:
        self.set_busy(None)
        self.log_line(f"[red]steam[/] {message}")
        self.notify(message, severity="error", timeout=12)

    def _steam_written(self, result: steam.EditResult, was_running: bool) -> None:
        self.set_busy(None)
        if result.changed:
            self.log_line(f"[green]steam[/] launch options -> {result.after}")
            if result.backup:
                self.log_line(f"[dim]steam[/] backup at {result.backup}")
        else:
            self.log_line(f"[dim]steam[/] {result.message}")
        self.refresh_status()
        self.call_later(self._offer_restart, was_running)

    def _offer_restart(self, was_running: bool) -> None:
        if not was_running:
            self.notify("launch options set")
            return
        self.push_screen(
            ConfirmScreen(
                "Start Steam again?",
                "The launch options are set. Steam is closed.",
                confirm="Start Steam",
            ),
            lambda ok: self._restart_steam() if ok else None,
        )

    def _restart_steam(self) -> None:
        if steam.start():
            self.log_line("[dim]steam[/] starting")
            self.notify("starting Steam")
        else:
            self.notify("could not find the steam command", severity="error")

    # -- nexus ----------------------------------------------------------

    async def refresh_nexus(self) -> None:
        """Draw the Nexus pane, or the key prompt when no key is set."""
        body = self.query_one("#nexus-body", VerticalScroll)
        await body.remove_children()
        if self.client.api_key:
            await body.mount(NexusPane(id="nexus-pane"))
            if not self.nexus_rows:
                self.load_nexus("trending")
            else:
                self.render_nexus()
        else:
            await body.mount(KeyPrompt())

    def owned_labels(self) -> dict[int, str]:
        """What the library already holds, keyed by Nexus mod id."""
        labels: dict[int, str] = {}
        for mod in self.catalog.mods:
            if not mod.nexus:
                continue
            if mod.nexus.has_update:
                labels[mod.nexus.mod_id] = f"↑ {mod.nexus.latest_version or 'newer'}"
            else:
                labels[mod.nexus.mod_id] = f"have {mod.version_label}"
        return labels

    def render_nexus(self) -> None:
        try:
            pane = self.query_one("#nexus-pane", NexusPane)
        except Exception:
            return
        pane.show_mods(self.nexus_rows, self.owned_labels())
        pane.show_detail(
            Content.styled(
                f"{len(self.nexus_rows)} mods · enter for files · d download",
                "$text-muted",
            )
        )

    @work(thread=True, exclusive=True, group="nexus")
    def load_nexus(self, mode: str, text: str = "") -> None:
        self.call_from_thread(self.set_busy, f"nexus: {mode}…", 0)
        try:
            if mode == "search" and text.strip():
                mods = self.client.search(text.strip())
            elif mode == "tracked":
                ids = set(self.client.tracked())
                mods = [
                    m for m in self.client.browse("downloads", 200) if m.mod_id in ids
                ]
            elif mode == "newest":
                mods = self.client.browse("createdAt", 60)
            else:
                mods = self.client.browse("downloads", 60)
            self.nexus_rows = mods
            self.nexus_files_for = None
            self.call_from_thread(self._nexus_done, f"{len(mods)} mods")
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))

    def _nexus_done(self, message: str) -> None:
        self.set_busy(None)
        self.render_nexus()
        self.refresh_status()
        self.log_line(f"[dim]nexus[/] {message}")

    def _nexus_failed(self, message: str) -> None:
        self.set_busy(None)
        self.nexus_error = message
        self.log_line(f"[red]nexus[/] {message}")
        self.notify(message, severity="error", timeout=10)
        # Put the reason where the missing rows would have been. A toast fades
        # and leaves an empty table with no explanation.
        banner = Content.styled(f"⚠ {message}", "bold $error")
        for selector, pane_type in (
            ("#nexus-pane", NexusPane),
            ("#collections-pane", CollectionsPane),
        ):
            try:
                self.query_one(selector, pane_type).show_detail(banner)
            except Exception:
                pass
        self.refresh_status()

    @work(thread=True, exclusive=True, group="nexus")
    def identify_library(self) -> None:
        """Ask Nexus what every archive in the library actually is."""
        self.call_from_thread(self.set_busy, "hashing archives…", 0)
        try:
            paths = [mod.source for mod in self.catalog.mods]
            hints = {
                mod.source: int(mod.nexus_id)
                for mod in self.catalog.mods
                if mod.nexus_id and mod.nexus_id.isdigit()
            }

            def progress(index: int, total: int, name: str) -> None:
                self.call_from_thread(
                    self.set_busy,
                    f"hashing {name[:40]}",
                    int(index * 100 / max(total, 1)),
                )

            matches, digests = identify_paths(
                self.client, paths, self.catalog.md5_cache, hints, progress
            )
            count = self.catalog.apply_nexus(matches, digests)
            self.call_from_thread(self._finish_batch, f"identified {count} mods")
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))

    @work(thread=True, exclusive=True, group="nexus")
    def check_for_updates(self) -> None:
        self.call_from_thread(self.set_busy, "checking Nexus for updates…", 0)
        try:
            updates = check_updates(self.client, self.catalog.owned_mod_ids())
            marked = self.catalog.apply_updates(updates)
            self.call_from_thread(self._finish_batch, f"{marked} mods have updates")
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))

    def action_identify(self) -> None:
        if not self._require_nexus():
            return
        self.identify_library()

    def action_check_updates(self) -> None:
        if not self._require_nexus():
            return
        self.check_for_updates()

    def _require_nexus(self) -> bool:
        if self.client.api_key:
            return True
        self.notify("No Nexus key. Open the NEXUS tab to add one.", severity="warning")
        return False

    @on(Input.Submitted, "#nexus-search")
    def _nexus_search(self, event: Input.Submitted) -> None:
        self.load_nexus("search", event.value)

    @on(Button.Pressed, "#nexus-trending")
    def _nexus_trending(self) -> None:
        self.load_nexus("trending")

    @on(Button.Pressed, "#nexus-newest")
    def _nexus_newest(self) -> None:
        self.load_nexus("newest")

    @on(Button.Pressed, "#nexus-tracked")
    def _nexus_tracked(self) -> None:
        self.load_nexus("tracked")

    @on(Button.Pressed, "#save-key")
    async def _save_key(self) -> None:
        value = self.query_one("#key-input", Input).value.strip()
        if not value:
            return
        credentials.save_key(value)
        self.client = NexusClient(value)
        self.validate_account()
        await self.refresh_nexus()

    @on(Button.Pressed, "#skip-key")
    async def _skip_key(self) -> None:
        self.query_one(TabbedContent).active = "library"

    @work(thread=True, group="nexus")
    def validate_account(self) -> None:
        try:
            self.account = self.client.validate()
            self.call_from_thread(
                self.log_line,
                f"[dim]nexus[/] signed in as {self.account.name}"
                f" ({self.account.badge})",
            )
        except NexusError as error:
            self.account = None
            self.call_from_thread(self.log_line, f"[red]nexus[/] {error}")
        self.call_from_thread(self.refresh_status)

    # -- collections ----------------------------------------------------

    @work(thread=True, exclusive=True, group="nexus")
    def load_collections(self) -> None:
        self.call_from_thread(self.set_busy, "loading collections…", 0)
        try:
            self.collection_rows = self.client.collections("endorsements", 50)
            self.call_from_thread(self._collections_done)
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))

    def _collections_done(self) -> None:
        self.set_busy(None)
        pane = self.query_one("#collections-pane", CollectionsPane)
        pane.show_collections(self.collection_rows)
        pane.show_detail(
            Content.styled(
                f"{len(self.collection_rows)} collections · "
                "select one and press Load manifest",
                "$text-muted",
            )
        )
        self.refresh_status()

    def current_collection(self) -> Collection | None:
        table = self.query_one("#collections-table", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self.collection_rows):
            return self.collection_rows[row]
        return None

    @on(Button.Pressed, "#load-manifest")
    def _load_manifest(self) -> None:
        chosen = self.current_collection()
        if chosen:
            self.fetch_manifest(chosen.slug)

    @on(DataTable.RowSelected, "#collections-table")
    def _collection_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter opens the full member list."""
        slug = str(event.row_key.value or "")
        if slug:
            self.fetch_manifest(slug, show_screen=True)

    @work(thread=True, exclusive=True, group="nexus")
    def fetch_manifest(self, slug: str, show_screen: bool = False) -> None:
        self.call_from_thread(self.set_busy, f"reading {slug}…", 0)
        try:
            self.manifest = self.client.collection(slug)
        except NexusError as error:
            self.call_from_thread(self._nexus_failed, str(error))
            return
        if show_screen:
            self.call_from_thread(self._push_collection_detail)
        else:
            self.call_from_thread(self.show_manifest)

    def _push_collection_detail(self) -> None:
        self.set_busy(None)
        if self.manifest:
            self.push_screen(
                CollectionDetail(self.manifest, self.catalog.held_files()),
                self._collection_action,
            )

    def _collection_action(self, action: CollectionAction | None) -> None:
        if action is None or not self.manifest:
            return
        if action.kind == "browse":
            self.open_url(
                f"https://next.nexusmods.com/marvelrivals/collections/{action.slug}"
            )
            return
        plan = nexus_collections.plan(
            self.manifest, action.optional_ids, self.catalog.held_files()
        )
        if not plan.to_download:
            self.notify("everything in that selection is already here")
            return
        self.push_screen(
            ConfirmScreen(
                f"Install {self.manifest.name}",
                f"{len(plan.to_download)} archives, {plan.size_label}.\n"
                "They download into your scan folder, then install.",
                confirm="Install",
            ),
            lambda ok: self.run_collection(plan) if ok else None,
        )

    def show_manifest(self) -> None:
        self.set_busy(None)
        if not self.manifest:
            return
        plan = nexus_collections.plan(
            self.manifest,
            (
                {mod.file_id for mod in self.manifest.optional}
                if self.include_optional
                else set()
            ),
            self.catalog.held_files(),
        )
        pane = self.query_one("#collections-pane", CollectionsPane)
        pane.show_detail(
            Content.assemble(
                (f"{self.manifest.name}  ", "bold"),
                (
                    f"rev {self.manifest.revision} · {self.manifest.author} · "
                    f"updated {self.manifest.updated_label} · "
                    f"{self.manifest.downloads_label} downloads · "
                    f"{self.manifest.endorsements} endorsements · "
                    f"rated {self.manifest.rating_label}\n",
                    "$text-muted",
                ),
                (
                    f"{len(plan.wanted)} wanted · "
                    f"{len(plan.already_held)} already held · "
                    f"{len(plan.to_download)} to fetch · {plan.size_label}\n",
                    "",
                ),
                (
                    f"optional {'included' if self.include_optional else 'excluded'} "
                    f"({len(self.manifest.optional)} available)",
                    "$text-muted",
                ),
            )
        )

    @on(Button.Pressed, "#toggle-optional")
    def _toggle_optional(self) -> None:
        self.include_optional = not self.include_optional
        self.show_manifest()

    @on(Button.Pressed, "#install-collection")
    def _install_collection(self) -> None:
        if not self.manifest:
            self.notify("Load a manifest first")
            return
        if not self._require_nexus():
            return
        plan = nexus_collections.plan(
            self.manifest,
            (
                {mod.file_id for mod in self.manifest.optional}
                if self.include_optional
                else set()
            ),
            self.catalog.held_files(),
        )
        if not plan.to_download:
            self.notify("Everything in this collection is already here")
            return
        self.push_screen(
            ConfirmScreen(
                f"Install {self.manifest.name}",
                f"{len(plan.to_download)} archives, {plan.size_label}.\n"
                "They download into your scan folder, then install.",
                confirm="Install",
            ),
            lambda ok: self.run_collection(plan) if ok else None,
        )

    @work(thread=True, exclusive=True, group="nexus")
    def run_collection(self, plan: nexus_collections.Plan) -> None:
        self._cancel_run = False
        destination = library.ensure()

        def on_item(index: int, total: int, mod) -> None:
            self.call_from_thread(
                self.set_busy,
                f"{index}/{total} {mod.mod_name[:34]}",
                int(index * 100 / max(total, 1)),
            )

        outcome = nexus_collections.install(
            self.client,
            plan,
            destination,
            on_item=on_item,
            cancelled=lambda: self._cancel_run,
        )
        self.call_from_thread(self._collection_finished, plan, outcome)

    def _collection_finished(
        self, plan: nexus_collections.Plan, outcome: nexus_collections.Outcome
    ) -> None:
        self.set_busy(None)
        for path in outcome.downloaded:
            self.log_line(f"[green]nexus[/] fetched {path.name}")
        for mod, reason in outcome.failed:
            self.log_line(f"[red]nexus[/] {mod.mod_name}: {reason}")

        assert self.game is not None
        self.catalog.rescan(self.config.scan_dirs, self.game.mods)
        self.catalog.tag_collection(
            plan.collection.slug,
            set(outcome.downloaded),
            {(mod.mod_id, mod.file_id) for mod in plan.wanted},
        )
        self.warnings = conflicts.check(self.catalog.mods)
        self.catalog.save()
        self.refresh_table()

        self.notify(
            f"{len(outcome.downloaded)} downloaded, "
            f"{len(outcome.skipped)} already held, {len(outcome.failed)} failed"
        )

        # A collection is meant to be played, so its members are installed as
        # well as fetched. Members already held but switched off are included,
        # because the pack expects the whole set to be active.
        pending = [
            mod
            for mod in self.catalog.in_collection(plan.collection.slug)
            if mod.state is not State.UNSUPPORTED and mod.state is not State.INSTALLED
        ]
        if pending:
            self.log_line(f"[dim]collection[/] installing {len(pending)} mods")
            self._run_install(pending, overwrite=True)


def run(config: Config) -> None:
    RegaliaApp(config).run()
