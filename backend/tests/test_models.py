"""Tests for models.drift pydantic models."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from models.drift import DriftEvent, ScanResult, ScanTriggerRequest, get_datetime_utc


# ---------------------------------------------------------------------------
# get_datetime_utc
# ---------------------------------------------------------------------------


class TestGetDatetimeUtc:
    def test_returns_aware_datetime(self):
        dt = get_datetime_utc()
        assert dt.tzinfo is timezone.utc
        # Should be roughly now (within a few seconds)
        assert (datetime.now(timezone.utc) - dt).total_seconds() < 5


# ---------------------------------------------------------------------------
# DriftEvent
# ---------------------------------------------------------------------------


class TestDriftEvent:
    def test_valid_event(self):
        event = DriftEvent(
            scan_id="scan-1",
            resource_id="i-123",
            resource_type="ec2",
            attribute="instance_type",
            expected="t3.micro",
            actual="t3.large",
            severity="high",
        )
        assert event.resource_id == "i-123"
        assert event.resource_type == "ec2"
        assert event.severity == "high"
        assert event.region == "ap-southeast-2"  # default
        assert event.detected_at.tzinfo is timezone.utc

    def test_valid_event_all_severities(self):
        for sev in ("low", "medium", "high"):
            event = DriftEvent(
                scan_id="scan-1",
                resource_id="i-1",
                resource_type="s3",
                attribute="tags",
                expected="",
                actual="x",
                severity=sev,
            )
            assert event.severity == sev

    def test_valid_resource_types(self):
        for rt in ("ec2", "s3", "security_group", "iam_role", "rds"):
            event = DriftEvent(
                scan_id="scan-1",
                resource_id="x",
                resource_type=rt,
                attribute="attr",
                expected="a",
                actual="b",
            )
            assert event.resource_type == rt

    def test_invalid_severity(self):
        with pytest.raises(ValidationError) as exc_info:
            DriftEvent(
                scan_id="scan-1",
                resource_id="i-1",
                resource_type="ec2",
                attribute="x",
                expected="a",
                actual="b",
                severity="critical",
            )
        assert "critical" in str(exc_info.value)

    def test_invalid_resource_type(self):
        with pytest.raises(ValidationError) as exc_info:
            DriftEvent(
                scan_id="scan-1",
                resource_id="i-1",
                resource_type="lambda",
                attribute="x",
                expected="a",
                actual="b",
            )
        assert "lambda" in str(exc_info.value)

    def test_detected_at_default(self):
        """detected_at should default to current UTC time."""
        event = DriftEvent(
            scan_id="scan-1",
            resource_id="i-1",
            resource_type="ec2",
            attribute="x",
            expected="a",
            actual="b",
        )
        assert event.detected_at.tzinfo is timezone.utc

    def test_custom_datetime(self):
        custom_dt = datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc)
        event = DriftEvent(
            scan_id="scan-1",
            resource_id="i-1",
            resource_type="ec2",
            attribute="x",
            expected="a",
            actual="b",
            detected_at=custom_dt,
        )
        assert event.detected_at == custom_dt

    def test_model_dump(self):
        event = DriftEvent(
            scan_id="scan-1",
            resource_id="i-1",
            resource_type="ec2",
            attribute="ami",
            expected="ami-a",
            actual="ami-b",
            severity="high",
        )
        data = event.model_dump()
        assert data["scan_id"] == "scan-1"
        assert data["resource_id"] == "i-1"
        assert data["severity"] == "high"
        assert "detected_at" in data


# ---------------------------------------------------------------------------
# ScanResult
# ---------------------------------------------------------------------------


class TestScanResult:
    def test_defaults(self):
        result = ScanResult()
        assert result.scan_id  # UUID should be auto-generated
        assert result.started_at is not None
        assert result.finished_at is None
        assert result.resource_scanned == 0
        assert result.drifts_found == 0
        assert result.status == "running"
        assert result.drift_events == []

    def test_valid_uuid(self):
        result = ScanResult()
        # Should be a valid UUID
        UUID(result.scan_id)

    def test_status_values(self):
        for st in ("running", "completed", "failed"):
            result = ScanResult(status=st)
            assert result.status == st

    def test_invalid_status(self):
        with pytest.raises(ValidationError) as exc_info:
            ScanResult(status="pending")
        assert "pending" in str(exc_info.value)

    def test_with_events(self):
        event = DriftEvent(
            scan_id="scan-1",
            resource_id="i-1",
            resource_type="ec2",
            attribute="instance_type",
            expected="t3.micro",
            actual="t3.large",
            severity="high",
        )
        result = ScanResult(
            scan_id="scan-1",
            resource_scanned=5,
            drifts_found=1,
            status="completed",
            drift_events=[event],
        )
        assert len(result.drift_events) == 1
        assert result.drift_events[0].resource_id == "i-1"

    def test_model_dump_with_events(self):
        event = DriftEvent(
            scan_id="scan-1",
            resource_id="i-1",
            resource_type="ec2",
            attribute="ami",
            expected="ami-a",
            actual="ami-b",
            severity="high",
        )
        result = ScanResult(
            scan_id="scan-1",
            resource_scanned=5,
            drifts_found=1,
            status="completed",
            drift_events=[event],
        )
        data = result.model_dump()
        assert data["scan_id"] == "scan-1"
        assert data["resource_scanned"] == 5
        assert data["drifts_found"] == 1
        assert data["status"] == "completed"
        assert len(data["drift_events"]) == 1
        assert data["drift_events"][0]["resource_id"] == "i-1"


# ---------------------------------------------------------------------------
# ScanTriggerRequest
# ---------------------------------------------------------------------------


class TestScanTriggerRequest:
    def test_defaults(self):
        req = ScanTriggerRequest()
        assert req.dry_run is False
        assert req.resource_types is None

    def test_dry_run_true(self):
        req = ScanTriggerRequest(dry_run=True)
        assert req.dry_run is True

    def test_with_resource_types(self):
        req = ScanTriggerRequest(resource_types=["ec2", "s3"])
        assert req.resource_types == ["ec2", "s3"]

    def test_model_dump(self):
        req = ScanTriggerRequest(dry_run=True, resource_types=["ec2"])
        data = req.model_dump()
        assert data["dry_run"] is True
        assert data["resource_types"] == ["ec2"]
