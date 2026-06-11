"""Tests for app.services.store."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.store import (
    _build_sk,
    _parse_sk,
    get_scan_summary,
    list_drift_events,
    save_scan_result,
)
from models.drift import DriftEvent, ScanResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestBuildSK:
    def test_simple(self):
        assert _build_sk("i-123", "instance_type") == "i-123#instance_type"


class TestParseSK:
    def test_normal(self):
        assert _parse_sk("i-123#instance_type") == ("i-123", "instance_type")

    def test_no_hash(self):
        assert _parse_sk("i-123") == ("i-123", "")

    def test_multiple_hashes(self):
        assert _parse_sk("a#b#c") == ("a", "b#c")


# ---------------------------------------------------------------------------
# save_scan_result
# ---------------------------------------------------------------------------


class TestSaveScanResult:
    @patch("app.services.store.get_dynamodb")
    def test_saves_drift_events_and_summary(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        scan_id = "scan-1"
        event1 = DriftEvent(
            scan_id=scan_id,
            resource_id="i-1",
            resource_type="ec2",
            attribute="instance_type",
            expected="t3.micro",
            actual="t3.large",
            severity="high",
            detected_at=datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc),
            region="ap-southeast-1",
        )
        event2 = DriftEvent(
            scan_id=scan_id,
            resource_id="i-2",
            resource_type="ec2",
            attribute="ami",
            expected="ami-123",
            actual="ami-999",
            severity="high",
            detected_at=datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc),
            region="ap-southeast-1",
        )
        result = ScanResult(
            scan_id=scan_id,
            resource_scanned=5,
            drifts_found=2,
            status="completed",
            drift_events=[event1, event2],
        )

        save_scan_result(result)

        # batch_writer should be used
        assert mock_table.batch_writer.called

        # Collect every Item put through the batch writer
        call_args_list = mock_table.batch_writer.return_value.__enter__.return_value.put_item.call_args_list
        items = [c.kwargs["Item"] for c in call_args_list]

        # Should have 3 items: 2 drift events + 1 summary
        assert len(items) == 3

        summary_items = [i for i in items if i.get("resource_id") == "#SUMMARY"]
        assert len(summary_items) == 1
        assert summary_items[0]["drifts_found"] == 2

        drift_items = [i for i in items if i.get("resource_id") != "#SUMMARY"]
        assert len(drift_items) == 2
        attrs = {i["attribute"] for i in drift_items}
        assert attrs == {"instance_type", "ami"}

        # Each drift item should reference the scan_id
        assert all(i["scan_id"] == scan_id for i in drift_items)

    @patch("app.services.store.get_dynamodb")
    def test_no_drift_saves_summary_only(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        result = ScanResult(
            scan_id="scan-1",
            resource_scanned=0,
            drifts_found=0,
            status="completed",
            drift_events=[],
        )

        save_scan_result(result)

        call_args_list = mock_table.batch_writer.return_value.__enter__.return_value.put_item.call_args_list
        items = [c.kwargs["Item"] for c in call_args_list]
        assert len(items) == 1
        assert items[0]["resource_id"] == "#SUMMARY"

    @patch("app.services.store.get_dynamodb")
    def test_resource_id_in_drift_items(self, mock_get_dynamodb):
        """Each drift item should have both resource_id (SK) and _resource_id (clean)."""
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        event = DriftEvent(
            scan_id="scan-1",
            resource_id="i-1",
            resource_type="ec2",
            attribute="ami",
            expected="ami-100",
            actual="ami-200",
            severity="high",
        )
        result = ScanResult(
            scan_id="scan-1",
            resource_scanned=1,
            drifts_found=1,
            status="completed",
            drift_events=[event],
        )

        save_scan_result(result)

        call_args_list = mock_table.batch_writer.return_value.__enter__.return_value.put_item.call_args_list
        drift_items = [
            c.kwargs["Item"]
            for c in call_args_list
            if c.kwargs["Item"].get("resource_id") != "#SUMMARY"
        ]
        assert len(drift_items) == 1
        assert drift_items[0]["resource_id"] == "i-1#ami"
        assert drift_items[0]["_resource_id"] == "i-1"


# ---------------------------------------------------------------------------
# list_drift_events
# ---------------------------------------------------------------------------


class TestListDriftEvents:
    @patch("app.services.store.get_dynamodb")
    def test_query_by_scan_id(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        mock_table.query.return_value = {
            "Items": [
                {
                    "scan_id": "scan-1",
                    "resource_id": "i-1#instance_type",
                    "_resource_id": "i-1",
                    "resource_type": "ec2",
                    "attribute": "instance_type",
                    "expected": "t3.micro",
                    "actual": "t3.large",
                    "severity": "high",
                    "detected_at": "2026-06-08T10:00:00+00:00",
                    "region": "ap-southeast-1",
                }
            ]
        }

        events = list_drift_events(scan_id="scan-1")

        mock_table.query.assert_called_once()
        assert len(events) == 1
        assert events[0]["scan_id"] == "scan-1"
        assert events[0]["resource_id"] == "i-1"
        assert events[0]["attribute"] == "instance_type"
        assert events[0]["expected"] == "t3.micro"
        assert events[0]["actual"] == "t3.large"
        assert events[0]["severity"] == "high"

    @patch("app.services.store.get_dynamodb")
    def test_scan_across_all(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        mock_table.scan.return_value = {
            "Items": [
                {
                    "scan_id": "scan-2",
                    "resource_id": "i-1#ami",
                    "_resource_id": "i-1",
                    "resource_type": "ec2",
                    "attribute": "ami",
                    "expected": "ami-100",
                    "actual": "ami-200",
                    "severity": "high",
                    "detected_at": "2026-06-08T11:00:00+00:00",
                    "region": "ap-southeast-1",
                }
            ],
            "LastEvaluatedKey": None,
        }

        events = list_drift_events()

        mock_table.scan.assert_called_once()
        assert len(events) == 1
        assert events[0]["scan_id"] == "scan-2"

    @patch("app.services.store.get_dynamodb")
    def test_skips_summary_rows(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        mock_table.query.return_value = {
            "Items": [
                {
                    "scan_id": "scan-1",
                    "resource_id": "#SUMMARY",
                    "summary": {},
                },
                {
                    "scan_id": "scan-1",
                    "resource_id": "i-1#ami",
                    "_resource_id": "i-1",
                    "resource_type": "ec2",
                    "attribute": "ami",
                    "expected": "ami-100",
                    "actual": "ami-200",
                    "severity": "high",
                    "detected_at": "2026-06-08T10:00:00+00:00",
                    "region": "ap-southeast-1",
                },
            ]
        }

        events = list_drift_events(scan_id="scan-1")
        assert len(events) == 1
        assert events[0]["resource_id"] == "i-1"

    @patch("app.services.store.get_dynamodb")
    def test_fallback_parse_sk_when__resource_id_missing(self, mock_get_dynamodb):
        """Older rows without _resource_id should fall back to parsing the SK."""
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        mock_table.query.return_value = {
            "Items": [
                {
                    "scan_id": "scan-1",
                    "resource_id": "i-1#ami",  # no _resource_id key
                    "resource_type": "ec2",
                    "attribute": "ami",
                    "expected": "ami-100",
                    "actual": "ami-200",
                    "severity": "high",
                    "detected_at": "2026-06-08T10:00:00+00:00",
                    "region": "ap-southeast-1",
                }
            ]
        }

        events = list_drift_events(scan_id="scan-1")
        assert events[0]["resource_id"] == "i-1"


# ---------------------------------------------------------------------------
# get_scan_summary
# ---------------------------------------------------------------------------


class TestGetScanSummary:
    @patch("app.services.store.get_dynamodb")
    def test_found(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        mock_table.get_item.return_value = {
            "Item": {
                "scan_id": "scan-1",
                "resource_id": "#SUMMARY",
                "resource_scanned": 5,
                "drifts_found": 3,
                "status": "completed",
                "region": "ap-southeast-1",
                "detected_at": "2026-06-08T10:00:00+00:00",
            }
        }

        result = get_scan_summary("scan-1")
        assert result is not None
        assert result["scan_id"] == "scan-1"
        assert result["drifts_found"] == 3

    @patch("app.services.store.get_dynamodb")
    def test_not_found(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        mock_table.get_item.return_value = {}

        result = get_scan_summary("scan-missing")
        assert result is None
