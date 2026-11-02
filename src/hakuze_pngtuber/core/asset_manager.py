"""Avatar asset resolution: user images override bundled placeholder art."""
from __future__ import annotations

from pathlib import Path

from ..utils.image_utils import AssetError, load_rgba, make_placeholder
from ..utils.platform_utils import resource_path
from .settings_manager import SettingsManager


class AssetManager:
    """Resolves idle/talking images.

    Priority: user-configured path > bundled assets/character/*.png >
    in-memory placeholder (never crashes on missing files).
    """

    def __init__(self, settings: SettingsManager):
        self._settings = settings
        self._cache: dict[str, object] = {}
        self.using_placeholder = False

    def character_dir(self) -> Path:
        return resource_path("assets") / "character"

    def idle_path(self) -> Path | None:
        custom = self._settings.get("avatar.idle_image", "")
        if custom and Path(custom).is_file():
            return Path(custom)
        bundled = self.character_dir() / "idle.png"
        return bundled if bundled.is_file() else None

    def talking_path(self) -> Path | None:
        custom = self._settings.get("avatar.talking_image", "")
        if custom and Path(custom).is_file():
            return Path(custom)
        bundled = self.character_dir() / "talking.png"
        return bundled if bundled.is_file() else None

    def get_images(self) -> tuple[object, object]:
        """Return (idle, talking) PIL RGBA images; placeholders on failure.

        Raises nothing: a missing image degrades to placeholder art and sets
        using_placeholder so the UI can warn the user once.
        """
        idle, talk = None, None
        try:
            path = self.idle_path()
            if path:
                idle = load_rgba(path)
        except AssetError:
            idle = None
        try:
            path = self.talking_path()
            if path:
                talk = load_rgba(path)
        except AssetError:
            talk = None

        self.using_placeholder = idle is None or talk is None
        if idle is None:
            idle = make_placeholder(talking=False)
        if talk is None:
            talk = make_placeholder(talking=True)
        return idle, talk

    def reload(self) -> None:
        self._cache.clear()
