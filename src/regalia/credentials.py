"""The Nexus API key.

The key lives in its own file at mode 0600. It never enters config.toml, the
catalog, the log, or git.
"""

from __future__ import annotations

import os
import tomllib

from .paths import CONFIG_DIR

CREDENTIALS_FILE = CONFIG_DIR / "credentials.toml"
ENV_VAR = "NEXUS_API_KEY"

API_KEY_URL = "https://next.nexusmods.com/settings/api-keys"


def load_key() -> str | None:
    """Read the key. The environment wins over the file."""
    if env := os.environ.get(ENV_VAR):
        return env.strip() or None
    if not CREDENTIALS_FILE.is_file():
        return None
    try:
        data = tomllib.loads(CREDENTIALS_FILE.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    key = data.get("nexus_api_key")
    return key.strip() if isinstance(key, str) and key.strip() else None


def save_key(key: str) -> None:
    """Write the key at mode 0600, creating the file with no wider window."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Open with the restrictive mode from the start. Writing first and calling
    # chmod afterwards would leave the key world readable in between.
    fd = os.open(CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(f'nexus_api_key = "{key.strip()}"\n')
    os.chmod(CREDENTIALS_FILE, 0o600)


def clear_key() -> None:
    CREDENTIALS_FILE.unlink(missing_ok=True)


def mask(key: str | None) -> str:
    """Render the key for the screen without showing it."""
    if not key:
        return "not set"
    return f"****{key[-4:]}" if len(key) > 4 else "****"


def file_mode_warning() -> str | None:
    """Report a credentials file that other users can read."""
    if not CREDENTIALS_FILE.is_file():
        return None
    mode = CREDENTIALS_FILE.stat().st_mode & 0o777
    if mode & 0o077:
        return f"{CREDENTIALS_FILE} is mode {mode:o}; it should be 600"
    return None
