from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FileSummary(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str | None
    status: str


class FeatureMeasurement(BaseModel):
    feature_id: str | int
    geometry_type: str | None
    geometry: dict[str, Any] | None
    crs: str | None
    source_crs: str | None
    properties: dict[str, Any] = Field(default_factory=dict)
    measurement: dict[str, float | str] | None = None
    measurement_crs: str | None = None
    measurement_status: str
    message: str | None = None


class MeasurementsResponse(BaseModel):
    file: FileSummary
    features: list[FeatureMeasurement]


class JobSummary(BaseModel):
    job_id: str
    filename: str
    status: str
    source_crs: str | None = None
    feature_count: int
    processed_count: int
    successful_count: int
    failed_count: int
    progress_percent: float
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
