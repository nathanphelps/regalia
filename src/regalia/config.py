"""Read and write the small TOML configuration file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .environment import download_dir
from .paths import CONFIG_DIR, CONFIG_FILE


def default_scan_dirs() -> list[Path]:
    """Where a new user's downloads land.

    A localised desktop names this folder in the user's own language, so the
    answer comes from the desktop settings rather than a hardcoded "Downloads".
    """
    return [download_dir()]


def _toml_string(value: object) -> str:
    """Quote a value for the file. Paths can hold quotes and backslashes."""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


@dataclass(slots=True)
class Config:
    scan_dirs: list[Path] = field(default_factory=default_scan_dirs)
    game_root: Path | None = None
    steam_root: Path | None = None
    dark: bool = False
    library_density: str = "comfortable"
    image_cache_mb: int = 1024
    gui_theme: str = "dark"

    @staticmethod
    def exists() -> bool:
        """True once the user has saved settings at least once."""
        return CONFIG_FILE.is_file()

    @classmethod
    def load(cls) -> Config:
        if not CONFIG_FILE.is_file():
            return cls()
        try:
            data = tomllib.loads(CONFIG_FILE.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            # A broken file must not stop the tool from starting. The readiness
            # checks report it, and the settings screen can write a good one.
            return cls()
        scan = [Path(p).expanduser() for p in data.get("scan_dirs", [])]
        root = data.get("game_root")
        steam = data.get("steam_root")
        return cls(
            scan_dirs=scan or default_scan_dirs(),
            game_root=Path(root).expanduser() if root else None,
            steam_root=Path(steam).expanduser() if steam else None,
            dark=bool(data.get("dark", False)),
            library_density=str(data.get("library_density", "comfortable")),
            image_cache_mb=int(data.get("image_cache_mb", 1024)),
            gui_theme=str(data.get("gui_theme", "dark")),
        )

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        lines = ["scan_dirs = ["]
        lines += [f"  {_toml_string(path)}," for path in self.scan_dirs]
        lines.append("]")
        if self.game_root:
            lines.append(f"game_root = {_toml_string(self.game_root)}")
        if self.steam_root:
            lines.append(f"steam_root = {_toml_string(self.steam_root)}")
        lines.append(f"dark = {str(self.dark).lower()}")
        lines.append(f"library_density = {_toml_string(self.library_density)}")
        lines.append(f"image_cache_mb = {self.image_cache_mb}")
        lines.append(f"gui_theme = {_toml_string(self.gui_theme)}")
        CONFIG_FILE.write_text("\n".join(lines) + "\n")
