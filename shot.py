"""Development helper: boot the app headless and save screenshots.

Usage: python shot.py [--dark] [--tab=patch] [--demo]

"--demo" builds a throwaway game tree and installs a few mods into it, so that
conflict warnings and the installed list can be pictured without touching the
real installation.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from regalia import installer
from regalia.app import RegaliaApp
from regalia.catalog import Catalog
from regalia.config import Config
from regalia.paths import GamePaths

# Override with REGALIA_SHOT_DIR to write somewhere else.
OUT = Path(os.environ.get("REGALIA_SHOT_DIR", "shots"))


def build_demo_game() -> Path:
    root = Path(tempfile.mkdtemp(prefix="regalia-demo-"))
    game = GamePaths(root)
    game.paks.mkdir(parents=True)
    game.binaries.mkdir(parents=True)

    catalog = Catalog()
    catalog.rescan(Config().scan_dirs, game.mods)
    wanted = ("Moon Knight", "Cyclops", "Iron Fist")
    for mod in catalog.mods:
        if mod.hero in wanted:
            installer.install(mod, game.mods)
    return root


async def main() -> None:
    dark = "--dark" in sys.argv
    demo = "--demo" in sys.argv
    tab = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--tab=")), None)

    config = Config(dark=dark)
    if demo:
        config.game_root = build_demo_game()

    app = RegaliaApp(config)
    async with app.run_test(size=(112, 34)) as pilot:
        await pilot.pause()
        await asyncio.sleep(3.0)
        if tab:
            app.query_one("TabbedContent").active = tab
            await pilot.pause()
            await asyncio.sleep(4.0)
        await pilot.pause()

        name = "-".join(
            part
            for part in ("dark" if dark else "light", tab, "demo" if demo else "")
            if part
        )
        OUT.mkdir(parents=True, exist_ok=True)
        svg = OUT / f"{name}.svg"
        svg.write_text(app.export_screenshot())

    subprocess.run(
        ["inkscape", str(svg), "-o", str(svg.with_suffix(".png")), "-w", "1500"],
        capture_output=True,
    )
    print(svg.with_suffix(".png"))


asyncio.run(main())
