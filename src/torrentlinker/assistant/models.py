"""Validated owner choices, never writable by the model."""

from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from torrentlinker.agent.access import Grant


class Conversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Discussion", min_length=1, max_length=100)
    provider_id: str = ""
    policy: Grant
    web: bool = False
    max_calls: int = Field(default=0, ge=0, le=200)
    max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    # Accepted when reading older settings; cumulative usage is no longer a cutoff.
    max_tokens: int | None = Field(default=None, exclude=True)
    max_seconds: int = Field(default=0, ge=0, le=1800)


class Schedule(Conversation):
    max_calls: int = Field(default=12, ge=1, le=40)
    max_seconds: int = Field(default=300, ge=10, le=1800)
    instruction: str = Field(min_length=1, max_length=16000)
    enabled: bool = False
    kind: Literal["model", "refresh", "catalogue"] = "model"
    frequency: Literal["interval", "daily", "weekly"] = "daily"
    interval_minutes: int = Field(default=60, ge=5, le=525600)
    at: str = "09:00"
    timezone: str = "Europe/Paris"
    weekdays: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=7)

    @model_validator(mode="after")
    def validate_schedule(self):
        if len(self.at) != 5 or self.at[2] != ":":
            raise ValueError("Use a local time in HH:MM format and select its timezone separately.")
        time.fromisoformat(self.at)
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown timezone. Use a name such as Europe/Paris.") from None
        if any(d < 0 or d > 6 for d in self.weekdays):
            raise ValueError("Weekdays must be between Monday (0) and Sunday (6).")
        return self

    def next_at(self, now: float) -> float:
        if self.frequency == "interval":
            return now + self.interval_minutes * 60
        zone = ZoneInfo(self.timezone)
        local = datetime.fromtimestamp(now, zone)
        for offset in range(9):
            day = local.date() + timedelta(days=offset)
            if self.frequency == "weekly" and day.weekday() not in self.weekdays:
                continue
            candidate = datetime.combine(day, time.fromisoformat(self.at), zone)
            stamp = candidate.timestamp()
            # Nonexistent spring-forward times run at the next valid wall-clock time;
            # fall-back runs once, using the first occurrence.
            if stamp > now:
                return stamp
        raise ValueError("Cannot calculate the next scheduled run.")


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str
    message: str = Field(min_length=1, max_length=16000)
