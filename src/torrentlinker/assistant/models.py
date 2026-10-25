"""Validated owner choices and limited current-chat model classification."""

from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from torrentlinker.agent.access import Grant


class FolderChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folder: str = Field(default="", max_length=80)

    @field_validator("folder")
    @classmethod
    def folder_name(cls, value: str) -> str:
        value = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Use a folder name without control characters.")
        return value


class FolderMove(FolderChoice):
    automatic: bool = False


class FolderClassification(FolderChoice):
    folder: str = Field(max_length=80)


class Conversation(FolderChoice):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Discussion", min_length=1, max_length=100)
    folder_source: Literal["auto", "manual"] = "auto"
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


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    options: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_question(self):
        if not self.question.strip() or any(not x.strip() or len(x) > 500 for x in self.options):
            raise ValueError("Provide a question and non-empty suggested answers.")
        return self


class UserAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=16000)

    @model_validator(mode="after")
    def validate_answer(self):
        if not self.answer.strip():
            raise ValueError("Enter or select an answer before submitting.")
        return self


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
