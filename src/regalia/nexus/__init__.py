"""Nexus Mods integration.

The two Nexus APIs divide the work. The v2 GraphQL endpoint answers searches,
hash lookups, and collection manifests without a key, and it batches. The v1
REST endpoint needs the key but is the only place that mints download links.
"""

from .client import (
    GAME_DOMAIN,
    GAME_ID,
    NexusAuthError,
    NexusClient,
    NexusError,
    NexusOffline,
    NexusPremiumRequired,
    NexusRateLimited,
    RateLimit,
)
from .models import (
    Collection,
    CollectionMod,
    HashMatch,
    NexusFile,
    NexusImage,
    NexusMod,
    Page,
    UserInfo,
)

__all__ = [
    "GAME_DOMAIN",
    "GAME_ID",
    "Collection",
    "CollectionMod",
    "HashMatch",
    "NexusAuthError",
    "NexusClient",
    "NexusError",
    "NexusFile",
    "NexusImage",
    "NexusMod",
    "NexusOffline",
    "NexusPremiumRequired",
    "NexusRateLimited",
    "Page",
    "RateLimit",
    "UserInfo",
]
