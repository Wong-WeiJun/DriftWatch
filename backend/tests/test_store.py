"""Tests for app.services.store."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.store import (
    _build_sk,
    _event_items_from_report,
    _parse_sk,
    _severity_for,
    get_scan_summary,
    list_drift_events,
    save_scan_result,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestSeverityFor:
    def test_high_severity_attributes(self):
        assert _severity_for("instance_type") == "high"
        assert _severity_for("instance_class") == "high"
        assert _severity_for("publicly_accessible") == "high"
        assert _severity_for("ami") == "high"

    def test_medium_severity_by_default(self):
        assert _severity_for("tags") == "medium"
        assert _severity_for("ingress_rule_count") == "medium"
        assert _severity_for("vpc_id") == "medium"


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
# report -> item conversion
# ---------------------------------------------------------------------------


class TestEventItemsFromReport:
    def test_empty_drifted(self):
        items = _event_items_from_report(
            {"drifted": {}, "summary": {}},
            scan_id="scan-1",
            region="ap-southeast-1",
        )
        assert items == []

    def test_single_drift(self):
        report = {
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
                }
            },
            "summary": {"drifted": 1},
        }
        items = _event_items_from_report(
            report, scan_id="scan-1", region="ap-southeast-1"
        )
        assert len(items) == 1
        item = items[0]
        assert item["scan_id"] == "scan-1"
        assert item["resource_id"] == "i-1#instance_type"
        assert item["_resource_id"] == "i-1"
        assert item["resource_type"] == "ec2"
        assert item["attribute"] == "instance_type"
        assert item["expected"] == "t3.micro"
        assert item["actual"] == "t3.large"
        assert item["severity"] == "high"
        assert item["region"] == "ap-southeast-1"
        assert "detected_at" in item

    def test_none_live_value(self):
        """Missing live values should be stored as empty string."""
        report = {
            "drifted": {
                "i-1": {
                    "resource_type": "aws_instance",
                    "differences": {
                        "key_name": {
                            "tf_value": "my-key",
                            "live_value": None,
                        }
                    },
                }
            },
            "summary": {},
        }
        items = _event_items_from_report(report, scan_id="s", region="r")
        assert items[0]["expected"] == "my-key"
        assert items[0]["actual"] == ""

    def test_unknown_resource_type_fallback(self):
        report = {
            "drifted": {
                "x": {
                    "resource_type": "aws_unknown",
                    "differences": {"foo": {"tf_value": "a", "live_value": "b"}},
                }
            },
            "summary": {},
        }
        items = _event_items_from_report(report, scan_id="s", region="r")
        assert items[0]["resource_type"] == "aws_unknown"  # falls through _TYPE_MAP


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

        report = {
            "summary": {
                "tf_resources": 5,
                "live_resources": 4,
                "drifted": 2,
                "missing_in_live": 1,
                "missing_in_tf": 1,
            },
            "drifted": {
                "i-1": {
                    "resource_type": "aws_instance",
                    "differences": {
                        "instance_type": {
                            "tf_value": "t3.micro",
                            "live_value": "t3.large",
                        }
                    },
                },
                "i-2": {
                    "resource_type": "aws_instance",
                    "differences": {
                        "ami": {
                            "tf_value": "ami-123",
                            "live_value": "ami-999",
                        }
                    },
                },
            },
            "missing_in_live": [],
            "missing_in_tf": [],
        }

        scan_id = save_scan_result(report)

        # batch_writer should be used
        assert mock_table.batch_writer.called

        # Collect every Item put through the batch writer
        call_args_list = (
            mock_table.batch_writer.return_value.__enter__.return_value.put_item.call_args_list
        )
        items = [c.kwargs["Item"] for c in call_args_list]

        # Should have 3 items: 2 drift events + 1 summary
        assert len(items) == 3

        summary_items = [i for i in items if i.get("resource_id") == "#SUMMARY"]
        assert len(summary_items) == 1
        assert summary_items[0]["drifted_count"] == 2

        drift_items = [i for i in items if i.get("resource_id") != "#SUMMARY"]
        assert len(drift_items) == 2
        attrs = {i["attribute"] for i in drift_items}
        assert attrs == {"instance_type", "ami"}

        # scan_id should be a UUID
        assert all(i["scan_id"] == scan_id for i in items)

    @patch("app.services.store.get_dynamodb")
    def test_no_drift_saves_summary_only(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        report = {
            "summary": {"drifted": 0, "missing_in_live": 0, "missing_in_tf": 0},
            "drifted": {},
            "missing_in_live": [],
            "missing_in_tf": [],
        }

        save_scan_result(report)

        call_args_list = (
            mock_table.batch_writer.return_value.__enter__.return_value.put_item.call_args_list
        )
        items = [c.kwargs["Item"] for c in call_args_list]
        assert len(items) == 1
        assert items[0]["resource_id"] == "#SUMMARY"


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
                "summary": {"drifted": 3},
                "region": "ap-southeast-1",
                "detected_at": "2026-06-08T10:00:00+00:00",
            }
        }

        result = get_scan_summary("scan-1")
        assert result is not None
        assert result["scan_id"] == "scan-1"
        assert result["summary"]["drifted"] == 3

    @patch("app.services.store.get_dynamodb")
    def test_not_found(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        mock_table.get_item.return_value = {}

        result = get_scan_summary("scan-missing")
        assert result is None
