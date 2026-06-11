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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_sk(resource_id: str, attribute: str) -> str:
    return f"{resource_id}#{attribute}"


def _parse_sk(sk: str) -> tuple[str, str]:
    parts = sk.split("#", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (sk, "")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_scan_result(result: ScanResult) -> None:
    """Persist a ScanResult to DynamoDB.

    Each DriftEvent becomes its own row. A summary sentinel row is also
    written so get_scan_summary() can retrieve high-level scan metadata.
    """
    table_name = settings.DYNAMODB_TABLE_NAME
    ddb = get_dynamodb()
    table = ddb.Table(table_name)

    items: list[dict[str, Any]] = []

    # One row per drift event
    for event in result.drift_events:
        sk = _build_sk(event.resource_id, event.attribute)
        items.append(
            {
                "scan_id": result.scan_id,
                "resource_id": sk,  # composite sort key — no collisions
                "_resource_id": event.resource_id,  # clean value for consumers
                "resource_type": event.resource_type,
                "attribute": event.attribute,
                "expected": event.expected,
                "actual": event.actual,
                "severity": event.severity,
                "detected_at": event.detected_at.isoformat()
                if hasattr(event.detected_at, "isoformat")
                else str(event.detected_at),
                "region": event.region
                if hasattr(event, "region")
                else settings.AWS_REGION,
            }
        )

    # Summary sentinel row
    items.append(
        {
            "scan_id": result.scan_id,
            "resource_id": "#SUMMARY",
            "resource_scanned": result.resource_scanned,
            "drifts_found": result.drifts_found,
            "status": result.status,
            "detected_at": _now_iso(),
            "region": settings.AWS_REGION,
        }
    )

    # Batch-write in chunks of 25 (DynamoDB hard limit)
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    logger.info(
        "Saved scan %s to %s (%d drift events)",
        result.scan_id,
        table_name,
        result.drifts_found,
    )


def list_drift_events(
    *,
    scan_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return drift events from DynamoDB, newest first.

    Pass scan_id to scope to a single scan, or omit for all recent events.
    """
    ddb = get_dynamodb()
    table = ddb.Table(settings.DYNAMODB_TABLE_NAME)

    if scan_id:
        resp = table.query(
            KeyConditionExpression="scan_id = :sid",
            ExpressionAttributeValues={":sid": scan_id},
            ScanIndexForward=False,
            Limit=limit,
        )
        raw = resp.get("Items", [])
    else:
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
        if item.get("attribute") is None:
            continue

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

    events.sort(key=lambda e: e.get("detected_at", ""), reverse=True)
    return events[:limit]


def get_scan_summary(scan_id: str) -> dict[str, Any] | None:
    """Fetch the summary row for a given scan. Returns None if not found."""
    ddb = get_dynamodb()
    table = ddb.Table(settings.DYNAMODB_TABLE_NAME)

    resp = table.get_item(Key={"scan_id": scan_id, "resource_id": "#SUMMARY"})
    item = resp.get("Item")
    if item is None:
        return None

    return {
        "scan_id": item["scan_id"],
        "resource_scanned": item.get("resource_scanned", 0),
        "drifts_found": item.get("drifts_found", 0),
        "status": item.get("status", "completed"),
        "detected_at": item.get("detected_at", ""),
        "region": item.get("region", settings.AWS_REGION),
    }
