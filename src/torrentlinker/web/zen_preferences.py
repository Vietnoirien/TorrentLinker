"""Owner-editable inputs to the shared Zen and Plan calculations."""

from dataclasses import asdict, replace
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from torrentlinker.config import Settings
from torrentlinker.zen import ZenClass


class ZenPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    zen_class: ZenClass | None = None
    tree_bonus: float | None = Field(default=None, ge=0, le=0.05)
    badge_bonus: float | None = Field(default=None, ge=0, le=1)
    seed_hours: float | None = Field(default=None, ge=0, le=24)
    torrent_cap: int | None = Field(default=None, ge=0, le=100_000)
    uploads: int | None = Field(default=None, ge=0, le=1_000_000)
    free_space_margin: float | None = Field(default=None, ge=0, le=0.9)
    plan_exclusions: list[str] | None = Field(default=None, max_length=1000)
    download_speed: float | None = Field(default=None, gt=0)

    def apply(self, settings: Settings) -> None:
        values = self.model_dump(exclude_unset=True)
        zen = {key: values[key] for key in asdict(settings.zen) if values.get(key) is not None}
        settings.zen = replace(settings.zen, **zen)
        for key in ("uploads", "free_space_margin", "plan_exclusions"):
            if values.get(key) is not None:
                setattr(settings, key, values[key])
        if "download_speed" in values:
            settings.download_speed = self.download_speed
            settings.download_speed_tested = None  # manually supplied rate


def snapshot(settings: Settings) -> dict:
    return {
        **asdict(settings.zen),
        "uploads": settings.uploads,
        "free_space_margin": settings.free_space_margin,
        "plan_exclusions": settings.plan_exclusions,
        "download_speed": settings.download_speed,
        "download_speed_tested": settings.download_speed_tested,
        "plan_options": asdict(settings.plan_options),
        "plan_categories": settings.plan_categories,
    }


def measure(setup) -> dict:
    from torrentlinker.speedtest import measure_download_speed

    speed = measure_download_speed()
    root = setup._root or setup
    root.settings.download_speed = speed
    root.settings.download_speed_tested = datetime.now().isoformat(timespec="minutes")
    root.save()
    setup.settings.download_speed = speed
    setup.settings.download_speed_tested = root.settings.download_speed_tested
    return snapshot(root.settings)
