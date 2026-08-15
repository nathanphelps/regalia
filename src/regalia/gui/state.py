"""Small persistent state for discovery workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from ..paths import DATA_DIR

STATE_FILE = DATA_DIR / "gui-state.json"


@dataclass(slots=True)
class StateData:
    favorite_mod_ids: set[int] = field(default_factory=set)
    recent_mod_ids: list[int] = field(default_factory=list)
    saved_searches: list[str] = field(default_factory=list)


class GuiState(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.data = self._load()

    def _load(self) -> StateData:
        if not STATE_FILE.is_file():
            return StateData()
        try:
            raw = json.loads(STATE_FILE.read_text())
            return StateData(
                favorite_mod_ids={int(value) for value in raw.get("favorites", [])},
                recent_mod_ids=[int(value) for value in raw.get("recent", [])][:30],
                saved_searches=[str(value) for value in raw.get("searches", [])][:20],
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return StateData()

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "favorites": sorted(self.data.favorite_mod_ids),
            "recent": self.data.recent_mod_ids[:30],
            "searches": self.data.saved_searches[:20],
        }
        temporary = STATE_FILE.with_suffix(".json.new")
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        temporary.replace(STATE_FILE)
        self.changed.emit()

    def is_favorite(self, mod_id: int) -> bool:
        return mod_id in self.data.favorite_mod_ids

    def toggle_favorite(self, mod_id: int) -> bool:
        if mod_id in self.data.favorite_mod_ids:
            self.data.favorite_mod_ids.remove(mod_id)
            favorite = False
        else:
            self.data.favorite_mod_ids.add(mod_id)
            favorite = True
        self.save()
        return favorite

    def remember_mod(self, mod_id: int) -> None:
        self.data.recent_mod_ids = [
            value for value in self.data.recent_mod_ids if value != mod_id
        ]
        self.data.recent_mod_ids.insert(0, mod_id)
        self.data.recent_mod_ids = self.data.recent_mod_ids[:30]
        self.save()

    def save_search(self, query: str) -> bool:
        query = query.strip()
        if not query:
            return False
        self.data.saved_searches = [
            value for value in self.data.saved_searches if value != query
        ]
        self.data.saved_searches.insert(0, query)
        self.data.saved_searches = self.data.saved_searches[:20]
        self.save()
        return True

    def remove_search(self, query: str) -> None:
        self.data.saved_searches = [
            value for value in self.data.saved_searches if value != query
        ]
        self.save()
