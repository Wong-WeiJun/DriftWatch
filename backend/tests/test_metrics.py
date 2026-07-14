"""Tests for Prometheus metrics helpers — label bounds and recording."""

from prometheus_client import REGISTRY

from app.core import metrics
from models.drift import DriftEvent


def _counter_value(name: str, labels: dict[str, str]) -> float:
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else value


def test_record_scan_success_increments_bounded_labels():
    before = _counter_value(
        "driftwatch_scans_total", {"status": "success", "dry_run": "true"}
    )
    event = DriftEvent(
        scan_id="s1",
        resource_id="i-1",
        resource_type="ec2",
        attribute="instance_type",
        expected="t3.micro",
        actual="t3.large",
        severity="high",
    )
    report = {
        "summary": {
            "tf_resources": 3,
            "live_resources": 3,
            "drifted": 1,
            "missing_in_live": 1,
            "missing_in_tf": 2,
        }
    }
    metrics.record_scan(
        status="success",
        dry_run=True,
        duration_seconds=4.2,
        report=report,
        drift_events=[event],
    )

    assert (
        _counter_value(
            "driftwatch_scans_total", {"status": "success", "dry_run": "true"}
        )
        == before + 1
    )
    assert (
        _counter_value(
            "driftwatch_drift_events_total",
            {"kind": "drifted", "severity": "high"},
        )
        >= 1
    )
    assert (
        _counter_value(
            "driftwatch_drift_events_total",
            {"kind": "missing_in_live", "severity": "high"},
        )
        >= 1
    )
    assert (
        _counter_value(
            "driftwatch_drift_events_total",
            {"kind": "missing_in_tf", "severity": "medium"},
        )
        >= 2
    )
    assert metrics.RESOURCES_SCANNED._value.get() == 3.0


def test_record_scan_maps_unbounded_status_to_unknown():
    before = _counter_value(
        "driftwatch_scans_total", {"status": "unknown", "dry_run": "false"}
    )
    metrics.record_scan(
        status="exploded",
        dry_run=False,
        duration_seconds=1.0,
    )
    assert (
        _counter_value(
            "driftwatch_scans_total", {"status": "unknown", "dry_run": "false"}
        )
        == before + 1
    )


def test_metrics_endpoint_exposed():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "driftwatch_scans_total" in body
    assert "http_requests_total" in body or "http_request_duration" in body
