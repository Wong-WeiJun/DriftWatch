"""
DynamoDB persistence layer for DriftWatch scan results.

Typical usage::

    from app.services.drift_engine import run_scan
    from app.services.store import save_scan_result, list_drift_events

    report = run_scan()
    scan_id = save_scan_result(report)

    # List all stored drift events
    events = list_drift_events()

Stored as one DynamoDB item per drifted attribute.  The primary key is
``scan_id`` (hash) and ``resource_id#attribute`` (range) so a single
resource can have multiple drift rows without collision.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.database import get_dynamodb
from models.drift import DriftEvent, ScanResult

logger = logging.getLogger(__name__)

# Map scanner / TF resource types to the short labels used in DriftEvent.
_TYPE_MAP: dict[str, str] = {
    "aws_instance": "ec2",
    "aws_s3_bucket": "s3",
    "aws_security_group": "security_group",
    "aws_iam_role": "iam_role",
    "aws_rds_instances": "rds",
}

# Attributes considered high-severity when they drift.
_HIGH_SEVERITY_ATTRS: frozenset[str] = frozenset(
    {
        "instance_type",
        "instance_class",
        "publicly_accessible",
        "ami",  # changing AMI can mean unintentional replacement
    }
)


def _severity_for(attribute: str) -> str:
    """Return a severity level for a given attribute."""
    return "high" if attribute in _HIGH_SEVERITY_ATTRS else "medium"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_type(resource_type: str) -> str:
    return _TYPE_MAP.get(resource_type, resource_type)


def _build_sk(resource_id: str, attribute: str) -> str:
    """Build the DynamoDB sort-key value for a drift event."""
    return f"{resource_id}#{attribute}"


def _parse_sk(sk: str) -> tuple[str, str]:
    """Split a sort-key back into ``(resource_id, attribute)``."""
    parts = sk.split("#", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (sk, "")


def _event_items_from_report(
    report: dict[str, Any],
    *,
    scan_id: str,
    region: str,
) -> list[dict[str, Any]]:
    """Turn a drift-engine report into flat DynamoDB item dicts."""
    items: list[dict[str, Any]] = []
    drifted = report.get("drifted", {})

    for resource_id, info in drifted.items():
        resource_type = info.get("resource_type", "unknown")
        short_type = _short_type(resource_type)
        differences = info.get("differences", {})

        for attr, delta in differences.items():
            expected = delta.get("tf_value")
            actual = delta.get("live_value")

            # Normalise None / complex values to string for storage
            expected_str = "" if expected is None else str(expected)
            actual_str = "" if actual is None else str(actual)

            sk = _build_sk(resource_id, attr)
            item: dict[str, Any] = {
                "scan_id": scan_id,
                "resource_id": sk,  # composite sort key in DB
                "_resource_id": resource_id,  # clean value for consumers
                "resource_type": short_type,
                "attribute": attr,
                "expected": expected_str,
                "actual": actual_str,
                "severity": _severity_for(attr),
                "detected_at": _now_iso(),
                "region": region,
            }
            items.append(item)

    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_scan_result(report: dict[str, Any]) -> str:
    """Persist a drift report to DynamoDB.

    Each drifted attribute becomes its own row so the data is fully
    normalised and easy to query.

    Returns the generated ``scan_id``.
    """
    scan_id = str(uuid.uuid4())
    region = settings.AWS_REGION
    table_name = settings.DYNAMODB_TABLE_NAME

    ddb = get_dynamodb()
    table = ddb.Table(table_name)

    items = _event_items_from_report(report, scan_id=scan_id, region=region)

    # Also store a summary row so the high-level ScanResult can be rebuilt
    summary = report.get("summary", {})
    summary_item: dict[str, Any] = {
        "scan_id": scan_id,
        "resource_id": "#SUMMARY",  # sentinel sort key; never collides with real resources
        "summary": summary,
        "drifted_count": summary.get("drifted", 0),
        "missing_in_live_count": summary.get("missing_in_live", 0),
        "missing_in_tf_count": summary.get("missing_in_tf", 0),
        "region": region,
        "detected_at": _now_iso(),
    }
    items.append(summary_item)

    # Batch-write in chunks of 25 (DynamoDB limit)
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    logger.info(
        "Saved scan %s to %s (%d drift events)", scan_id, table_name, len(items) - 1
    )
    return scan_id


def list_drift_events(
    *,
    scan_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return drift events stored in DynamoDB.

    By default returns the most recent events across all scans (newest
    first).  Pass ``scan_id`` to scope to a single scan.

    Results are returned as plain dicts matching the shape::

        {
            "scan_id": "...",
            "resource_id": "i-0abc123def",
            "resource_type": "ec2",
            "attribute": "instance_type",
            "expected": "t3.micro",
            "actual": "t3.large",
            "severity": "high",
            "detected_at": "2026-06-08T10:00:00+00:00",
            "region": "ap-southeast-1",
        }
    """
    ddb = get_dynamodb()
    table = ddb.Table(settings.DYNAMODB_TABLE_NAME)

    if scan_id:
        resp = table.query(
            KeyConditionExpression="scan_id = :sid",
            ExpressionAttributeValues={":sid": scan_id},
            ScanIndexForward=False,  # newest first (by sort key)
            Limit=limit,
        )
        raw = resp.get("Items", [])
    else:
        # Scan with a filter to skip summary sentinel rows
        resp = table.scan(
            FilterExpression="attribute_exists(#attr)",
            ExpressionAttributeNames={"#attr": "attribute"},
            Limit=limit,
        )
        raw = resp.get("Items", [])
        while resp.get("LastEvaluatedKey") and len(raw) < limit:
            resp = table.scan(
                FilterExpression="attribute_exists(#attr)",
                ExpressionAttributeNames={"#attr": "attribute"},
                Limit=limit - len(raw),
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            raw.extend(resp.get("Items", []))

    events: list[dict[str, Any]] = []
    for item in raw:
        # Skip summary sentinel rows
        if item.get("attribute") is None:
            continue

        # Use the explicit clean resource_id if present, else split the SK
        resource_id = item.get("_resource_id")
        if resource_id is None:
            resource_id, _ = _parse_sk(item.get("resource_id", ""))

        events.append(
            {
                "scan_id": item["scan_id"],
                "resource_id": resource_id,
                "resource_type": item.get("resource_type", ""),
                "attribute": item.get("attribute", ""),
                "expected": item.get("expected", ""),
                "actual": item.get("actual", ""),
                "severity": item.get("severity", "medium"),
                "detected_at": item.get("detected_at", ""),
                "region": item.get("region", settings.AWS_REGION),
            }
        )

    # Sort newest first when scanning across many scans
    events.sort(key=lambda e: e.get("detected_at", ""), reverse=True)
    return events[:limit]


def get_scan_summary(scan_id: str) -> dict[str, Any] | None:
    """Fetch the summary row for a given scan.

    Returns ``None`` if the scan is not found.
    """
    ddb = get_dynamodb()
    table = ddb.Table(settings.DYNAMODB_TABLE_NAME)

    resp = table.get_item(Key={"scan_id": scan_id, "resource_id": "#SUMMARY"})
    item = resp.get("Item")
    if item is None:
        return None

    return {
        "scan_id": item["scan_id"],
        "summary": item.get("summary", {}),
        "region": item.get("region", settings.AWS_REGION),
        "detected_at": item.get("detected_at", ""),
    }
