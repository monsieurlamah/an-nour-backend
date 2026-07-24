"""Convenience access to the application configuration.

Import ``settings`` from here everywhere in the codebase so there is a single
shared, cached instance.
"""

from app.core.settings import Settings, get_settings

settings: Settings = get_settings()

__all__ = ["settings", "Settings", "get_settings"]
