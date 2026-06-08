import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Literal


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


class DriftEvent(BaseModel):
    scan_id: str
    resource_id: str
    resource_type: Literal["ec2", "s3", "security_group", "iam_role", "rds"]
    attribute: str
    expected: str
    actual: str
    severity: Literal["low", "medium", "high"] = "medium"
    detected_at: datetime = Field(default_factory=get_datetime_utc)
    region: str = "ap-southeast-2"


class ScanResult(BaseModel):
    scan_id: str = Field(default_factory=lambda: str(uuid.uuid4))
    started_at: datetime | None = Field(
        default_factory=get_datetime_utc,
    )
    finished_at: datetime | None = None
    resource_scanned: int = 0
    drifts_found: int = 0
    status: Literal["running", "completed", "failed"] = "running"
    drift_events: list[DriftEvent] = []
