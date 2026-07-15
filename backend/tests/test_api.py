"""Tests for API endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

API_PREFIX = "/api/v1"


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "DriftWatch"}


# ---------------------------------------------------------------------------
# /drifts
# ---------------------------------------------------------------------------


class TestDriftEndpoints:
    @patch("app.api.drift.store.list_drift_events")
    def test_list_events_no_scan_id(self, mock_list):
        mock_list.return_value = [
            {
                "scan_id": "scan-1",
                "resource_id": "i-1",
                "resource_type": "ec2",
                "attribute": "instance_type",
                "expected": "t3.micro",
                "actual": "t3.large",
                "severity": "high",
                "detected_at": "2026-06-08T10:00:00+00:00",
                "region": "ap-southeast-1",
            }
        ]
        response = client.get(f"{API_PREFIX}/drifts/events")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["resource_id"] == "i-1"
        mock_list.assert_called_once_with(scan_id=None, limit=100)

    @patch("app.api.drift.store.list_drift_events")
    def test_list_events_with_scan_id(self, mock_list):
        mock_list.return_value = []
        response = client.get(f"{API_PREFIX}/drifts/events?scan_id=scan-abc")
        assert response.status_code == 200
        mock_list.assert_called_once_with(scan_id="scan-abc", limit=100)

    @patch("app.api.drift.store.list_drift_events")
    def test_list_events_with_limit(self, mock_list):
        mock_list.return_value = []
        response = client.get(f"{API_PREFIX}/drifts/events?limit=50")
        assert response.status_code == 200
        mock_list.assert_called_once_with(scan_id=None, limit=50)

    @patch("app.api.drift.store.list_drift_events")
    def test_list_events_limit_too_high(self, mock_list):
        """Limit > 1000 should fail validation."""
        response = client.get(f"{API_PREFIX}/drifts/events?limit=5000")
        assert response.status_code == 422

    @patch("app.api.drift.store.get_scan_summary")
    def test_get_scan_summary_found(self, mock_get):
        mock_get.return_value = {
            "scan_id": "scan-1",
            "resource_scanned": 10,
            "drifts_found": 3,
            "status": "completed",
            "detected_at": "2026-06-08T10:00:00+00:00",
            "region": "ap-southeast-1",
        }
        response = client.get(f"{API_PREFIX}/drifts/scans/scan-1")
        assert response.status_code == 200
        data = response.json()
        assert data["scan_id"] == "scan-1"
        assert data["drifts_found"] == 3

    @patch("app.api.drift.store.get_scan_summary")
    def test_get_scan_summary_not_found(self, mock_get):
        mock_get.return_value = None
        response = client.get(f"{API_PREFIX}/drifts/scans/missing-scan")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# /scan
# ---------------------------------------------------------------------------


class TestScanEndpoints:
    @patch("app.api.scan.run_scan")
    def test_trigger_dry_run(self, mock_run_scan):
        mock_run_scan.return_value = {
            "summary": {
                "tf_resources": 2,
                "live_resources": 2,
                "drifted": 1,
                "missing_in_live": 0,
                "missing_in_tf": 0,
            },
            "drifted": {
                "i-1": {
                    "resource_type": "aws_instance",
                    "resource_id": "i-1",
                    "differences": {
                        "instance_type": {
                            "tf_value": "t3.micro",
                            "live_value": "t3.large",
                        }
                    },
                    "only_in_live": [],
                    "only_in_tf": [],
                }
            },
            "missing_in_live": [],
            "missing_in_tf": [],
        }

        response = client.post(f"{API_PREFIX}/scan/trigger", json={"dry_run": True})
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True
        assert data["status"] == "completed"
        assert data["drifts_found"] == 1
        assert data["resource_scanned"] == 2
        assert len(data["drift_events"]) == 1
        assert data["drift_events"][0]["resource_id"] == "i-1"
        assert data["drift_events"][0]["attribute"] == "instance_type"
        assert data["drift_events"][0]["severity"] == "high"
        mock_run_scan.assert_called_once_with(resource_types=None)

    @patch("app.api.scan.run_scan")
    def test_severity_tiers_high_medium_low(self, mock_run_scan):
        """Attribute name maps to high / medium / low for demo-friendly filtering."""
        mock_run_scan.return_value = {
            "summary": {
                "tf_resources": 3,
                "live_resources": 3,
                "drifted": 3,
                "missing_in_live": 0,
                "missing_in_tf": 0,
            },
            "drifted": {
                "i-1": {
                    "resource_type": "aws_instance",
                    "resource_id": "i-1",
                    "differences": {
                        "instance_type": {
                            "tf_value": "t3.micro",
                            "live_value": "t3.large",
                        },
                        "tags": {
                            "tf_value": {"Name": "old"},
                            "live_value": {"Name": "new"},
                        },
                    },
                    "only_in_live": [],
                    "only_in_tf": [],
                },
                "demo-role": {
                    "resource_type": "aws_iam_role",
                    "resource_id": "demo-role",
                    "differences": {
                        "max_session_duration": {
                            "tf_value": "3600",
                            "live_value": "7200",
                        }
                    },
                    "only_in_live": [],
                    "only_in_tf": [],
                },
            },
            "missing_in_live": [],
            "missing_in_tf": [],
        }

        response = client.post(f"{API_PREFIX}/scan/trigger", json={"dry_run": True})
        assert response.status_code == 200
        by_attr = {
            e["attribute"]: e["severity"] for e in response.json()["drift_events"]
        }
        assert by_attr["instance_type"] == "high"
        assert by_attr["max_session_duration"] == "medium"
        assert by_attr["tags"] == "low"

    @patch("app.api.scan.run_scan")
    def test_trigger_dry_run_with_resource_types(self, mock_run_scan):
        mock_run_scan.return_value = {
            "summary": {
                "tf_resources": 1,
                "live_resources": 1,
                "drifted": 0,
                "missing_in_live": 0,
                "missing_in_tf": 0,
            },
            "drifted": {},
            "missing_in_live": [],
            "missing_in_tf": [],
        }

        response = client.post(
            f"{API_PREFIX}/scan/trigger",
            json={"dry_run": True, "resource_types": ["ec2", "s3"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True
        assert data["drifts_found"] == 0
        mock_run_scan.assert_called_once_with(resource_types=["ec2", "s3"])

    @patch("app.api.scan.run_scan")
    def test_trigger_dry_run_empty_drift(self, mock_run_scan):
        """Dry run with no drift should return empty events."""
        mock_run_scan.return_value = {
            "summary": {
                "tf_resources": 3,
                "live_resources": 3,
                "drifted": 0,
                "missing_in_live": 0,
                "missing_in_tf": 0,
            },
            "drifted": {},
            "missing_in_live": [],
            "missing_in_tf": [],
        }

        response = client.post(f"{API_PREFIX}/scan/trigger", json={"dry_run": True})
        assert response.status_code == 200
        data = response.json()
        assert data["drifts_found"] == 0
        assert len(data["drift_events"]) == 0

    def test_trigger_background_queue(self):
        """Non-dry run should queue a background task and return scan_id."""
        response = client.post(f"{API_PREFIX}/scan/trigger", json={"dry_run": False})
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is False
        assert data["status"] == "queued"
        assert "scan_id" in data
        assert "message" in data

    def test_trigger_default_not_dry_run(self):
        """Default dry_run should be False (background task)."""
        response = client.post(f"{API_PREFIX}/scan/trigger", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is False
        assert data["status"] == "queued"


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------


class TestCors:
    def test_cors_preflight(self):
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        # FastAPI's CORSMiddleware should set the appropriate headers
        assert "access-control-allow-origin" in response.headers


# ---------------------------------------------------------------------------
# Router registration / app structure
# ---------------------------------------------------------------------------


class TestAppStructure:
    def test_openapi_schema_available(self):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "Driftwatch"
        paths = schema["paths"]
        assert "/health" in paths
        assert f"{API_PREFIX}/drifts/events" in paths
        assert f"{API_PREFIX}/drifts/scans/{{scan_id}}" in paths
        assert f"{API_PREFIX}/scan/trigger" in paths
