from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Profile(StrEnum):
    B0 = "B0"
    B1 = "B1"
    B2 = "B2"
    B3 = "B3"


class DocumentId(StrEnum):
    clean = "campus_wifi_clean"
    a07 = "campus_wifi_poisoned_a07"
    a08 = "campus_wifi_poisoned_a08"
    a09 = "campus_wifi_poisoned_a09"
    c05 = "campus_wifi_poisoned_c05"
    c06 = "campus_wifi_poisoned_c06"
    c07 = "campus_wifi_poisoned_c07"
    c08 = "campus_wifi_poisoned_c08"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)
    document_id: DocumentId = DocumentId.clean
    defense_profile: Profile = Profile.B0

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


class SecurityEvent(BaseModel):
    stage: str
    rule_id: str
    source: str


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    defense_profile: Profile
    document_id: DocumentId
    model: str
    latency_ms: int
    security_events: list[SecurityEvent]
    technical_status: str
