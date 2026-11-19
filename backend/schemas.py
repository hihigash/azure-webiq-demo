from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Mode = Literal["lite", "advanced"]
EventType = Literal["progress", "result", "error", "done"]


class Classification(BaseModel):
    name: str = Field(min_length=1)
    domains: list[str] = []


class Preset(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    label: str
    question: str = Field(min_length=1, max_length=1000)
    mode: Mode = "lite"
    useScope: bool = False
    responseFilter: list[str] = ["web", "news"]


class Pack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    description: str = ""
    scopeName: str | None = None
    allowedDomains: list[str] = Field(default_factory=list, max_length=100)
    classifications: list[Classification] = Field(default_factory=list)
    presets: list[Preset]

    @field_validator("allowedDomains")
    @classmethod
    def domains(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            domain = value.strip().lower().lstrip(".")
            if not domain or "://" in domain or ":" in domain or "?" in domain or "#" in domain or " " in domain:
                raise ValueError("allowedDomains must contain hosts or host/path prefixes")
            normalized.append(domain)
        return list(dict.fromkeys(normalized))


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    currency: str = "USD"
    model: dict[str, Any]
    search: dict[str, Any]


class PublicConfig(BaseModel):
    pack: Pack
    pricing: Pricing
    demoMode: bool
    limits: dict[str, int] = {"columns": 3, "allowedDomains": 100, "questionMaxLength": 1000}


class RunRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    presetId: str | None = None
    mode: Mode = "lite"
    scopeName: str | None = None
    allowedDomains: list[str] = Field(default_factory=list, max_length=100)
    responseFilter: list[str] = ["web", "news"]

    @field_validator("allowedDomains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value or "://" in value or ":" in value or "?" in value or "#" in value or " " in value:
                raise ValueError("allowedDomains must contain hosts or host/path prefixes")
        return list(dict.fromkeys(value.lower().lstrip(".") for value in values))


class Citation(BaseModel):
    id: str
    title: str = "取得不可"
    url: HttpUrl | str
    source: str = "取得不可"
    excerpt: str = "取得不可"
    publishedAt: str = "取得不可"
    dateKind: str = "取得不可"
    evidenceIds: list[str] = []
    classification: str = "その他"

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: HttpUrl | str) -> HttpUrl | str:
        url = str(value)
        if not url.lower().startswith(("http://", "https://")):
            return "取得不可"
        return url


class Evidence(BaseModel):
    id: str
    title: str = "取得不可"
    url: HttpUrl | str
    source: str = "取得不可"
    text: str = "取得不可"
    citationIds: list[str] = []
    kind: str = "evidence"
    structured: dict[str, Any] = {}

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: HttpUrl | str) -> HttpUrl | str:
        if not str(value).lower().startswith(("http://", "https://")):
            return "取得不可"
        return value


class Metrics(BaseModel):
    elapsedMs: int | None = None
    inputTokens: int | None = None
    outputTokens: int | None = None
    reasoningTokens: int | None = None
    searchRequests: int | None = None
    searchRequestUnit: str = "上流APIリクエスト"
    estimatedCost: float | None = None
    costCurrency: str | None = None
    unavailableFields: list[str] = []


class ColumnResult(BaseModel):
    columnId: Literal["A", "B", "C"]
    label: str
    status: Literal["success", "error"] = "success"
    answer: str = ""
    citations: list[Citation] = []
    evidence: list[Evidence] = []
    metrics: Metrics = Metrics()
    settings: dict[str, Any] = {}
    scopeApplied: bool | None = None
    error: dict[str, Any] | None = None


class RunSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")
    runId: str
    question: str = Field(max_length=1000)
    columns: list[ColumnResult] = Field(min_length=1, max_length=3)
    settings: dict[str, Any] = {}
    pricingVersion: str | None = None
    createdAt: str | None = None


class RunEvent(BaseModel):
    event: EventType
    columnId: Literal["A", "B", "C"]
    sequence: int
    elapsedMs: int
    message: str | None = None
    result: ColumnResult | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "RunEvent":
        if self.event == "result" and self.result is None:
            raise ValueError("result event requires result")
        return self

