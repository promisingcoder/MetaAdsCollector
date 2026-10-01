"""Validated contracts shared by tools, persisted jobs and the worker."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from meta_ads_collector.constants import (
    VALID_AD_TYPES,
    VALID_SEARCH_TYPES,
    VALID_SORT_MODES,
    VALID_STATUSES,
)
from meta_ads_collector.exceptions import MetaAdsError
from meta_ads_collector.filters import FilterConfig


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Filters(Contract):
    min_impressions: int | None = Field(None, ge=0)
    max_impressions: int | None = Field(None, ge=0)
    min_spend: int | None = Field(None, ge=0)
    max_spend: int | None = Field(None, ge=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    media_type: Literal["ALL", "IMAGE", "VIDEO", "MEME", "NONE"] | None = None
    publisher_platforms: list[str] | None = None
    languages: list[str] | None = None
    has_video: bool | None = None
    has_image: bool | None = None
    missing_data: Literal["include", "exclude"] = "include"

    @field_validator("start_date", "end_date")
    @classmethod
    def utc_dates(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ordered(self) -> Filters:
        for minimum, maximum in (
            (self.min_impressions, self.max_impressions),
            (self.min_spend, self.max_spend),
            (self.start_date, self.end_date),
        ):
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError("Filter minimum must not exceed its maximum")
        return self

    def core(self) -> FilterConfig:
        return FilterConfig(**self.model_dump(exclude={"missing_data"}))


class Search(Contract):
    query: str = Field("", max_length=1000)
    country: str = "US"
    ad_type: str = "ALL"
    status: str = "ACTIVE"
    search_type: str = "KEYWORD_UNORDERED"
    page_ids: list[str] | None = Field(None, max_length=50)
    sort_by: str | None = None
    filters: Filters = Field(default_factory=Filters)
    max_results: int = Field(100, ge=1, le=100000)
    page_size: int = Field(20, ge=1, le=30)
    max_requests: int = Field(100, ge=1, le=10000)
    max_seconds: int = Field(600, ge=1, le=86400)
    proxy_profile: str | None = None
    timeout: int = Field(30, ge=1, le=120)
    max_retries: int = Field(3, ge=1, le=5)
    rate_limit_delay: float = Field(1.0, ge=0, le=60)
    jitter: float = Field(0.5, ge=0, le=10)
    cookie_env: str | None = None

    @field_validator("country")
    @classmethod
    def country_code(cls, value: str) -> str:
        value = value.upper()
        if len(value) != 2 or not value.isascii() or not value.isalpha():
            raise ValueError("Country must be a two-letter code")
        return value

    @field_validator("page_ids")
    @classmethod
    def numeric_pages(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and (not values or any(not v.isascii() or not v.isdigit() for v in values)):
            raise ValueError("Page IDs must be nonempty numeric strings")
        return values

    @model_validator(mode="after")
    def supported(self) -> Search:
        for key, allowed in (
            ("ad_type", VALID_AD_TYPES),
            ("status", VALID_STATUSES),
            ("search_type", VALID_SEARCH_TYPES),
            ("sort_by", VALID_SORT_MODES),
        ):
            if getattr(self, key) not in allowed:
                raise ValueError(f"Unsupported {key}")
        if not self.query.strip() and not self.page_ids:
            raise ValueError("Provide a query or page IDs")
        if self.page_ids:
            self.search_type = "PAGE"
        if self.search_type == "PAGE" and not self.page_ids:
            raise ValueError("PAGE searches require page IDs")
        return self


class ProxyProfile(Contract):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    environment: str | None = Field(None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    secret_file: str | None = None
    max_failures: int = Field(3, ge=1, le=100)
    cooldown: float = Field(300, ge=0, le=86400)

    @model_validator(mode="after")
    def one_reference(self) -> ProxyProfile:
        if bool(self.environment) == bool(self.secret_file):
            raise ValueError("Provide exactly one environment or private secret-file reference")
        return self


class Schedule(Contract):
    name: str = Field(min_length=1, max_length=100)
    search: Search
    interval_seconds: int = Field(3600, ge=60, le=31536000)
    retention_days: int = Field(30, ge=1, le=3650)


class MCPError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BudgetReached(MetaAdsError):
    """A configured collection budget was exhausted."""


class Cancelled(MetaAdsError):
    """Cooperative cancellation at the next safe collection boundary."""
