from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks

from app.core.metrics import record_scan
from app.services.drift_engine import run_scan
from app.services.notifier import publish_drift_alert
from app.services.store import save_scan_result
from models.drift import DriftEvent, ScanResult, ScanTriggerRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scan", tags=["scan"])

_TYPE_SHORT: dict[str, str] = {
    "aws_instance": "ec2",
    "aws_s3_bucket": "s3",
    "aws_security_group": "security_group",
    "aws_iam_role": "iam_role",
    "aws_rds_instances": "rds",
}

_HIGH_SEVERITY_ATTRS = {
    "instance_type",
    "instance_class",
    "publicly_accessible",
    "ami",
    "ingress_rule_count",
    "egress_rule_count",
}


def _convert_report_to_scan_result(report: dict[str, Any], scan_id: str) -> ScanResult:
    summary = report.get("summary", {})
    drift_events: list[DriftEvent] = []

    for rid, info in report.get("drifted", {}).items():
        resource_type = info.get("resource_type", "unknown")
        short_type = _TYPE_SHORT.get(resource_type, resource_type)

        for attr, delta in info.get("differences", {}).items():
            tf_val = delta.get("tf_value")
            live_val = delta.get("live_value")
            drift_events.append(
                DriftEvent(
                    scan_id=scan_id,
                    resource_id=info.get("resource_id", rid),
                    resource_type=short_type,
                    attribute=attr,
                    expected="" if tf_val is None else str(tf_val),
                    actual="" if live_val is None else str(live_val),
                    severity="high" if attr in _HIGH_SEVERITY_ATTRS else "medium",
                )
            )

    return ScanResult(
        scan_id=scan_id,
        resource_scanned=summary.get("tf_resources", 0),
        drifts_found=summary.get("drifted", 0),
        status="completed",
        drift_events=drift_events,
    )


def _run_and_persist(scan_id: str, resource_types: list[str] | None) -> None:
    """Background task — runs scan, saves results, sends alert."""
    started = time.perf_counter()
    try:
        report = run_scan(resource_types=resource_types)
        result = _convert_report_to_scan_result(report, scan_id)
        save_scan_result(result)
        publish_drift_alert(result)
        record_scan(
            status="success",
            dry_run=False,
            duration_seconds=time.perf_counter() - started,
            report=report,
            drift_events=result.drift_events,
        )
        logger.info(
            "Scan %s complete - %d drift(s) across %d resources",
            scan_id[:8],
            result.drifts_found,
            result.resource_scanned,
        )
    except Exception:
        record_scan(
            status="error",
            dry_run=False,
            duration_seconds=time.perf_counter() - started,
        )
        logger.exception("Background scan failed")


@router.post("/trigger")
def trigger_scan(
    body: ScanTriggerRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    Trigger a drift scan.

    - dry_run=True  → runs synchronously, returns full results, nothing saved
    - dry_run=False → queues background task, returns scan_id immediately
    """
    scan_id = str(uuid.uuid4())

    if body.dry_run:
        logger.info("Dry run triggered")
        started = time.perf_counter()
        try:
            report = run_scan(resource_types=body.resource_types)
            result = _convert_report_to_scan_result(report, scan_id)
            record_scan(
                status="success",
                dry_run=True,
                duration_seconds=time.perf_counter() - started,
                report=report,
                drift_events=result.drift_events,
            )
        except Exception:
            record_scan(
                status="error",
                dry_run=True,
                duration_seconds=time.perf_counter() - started,
            )
            raise
        return {
            "scan_id": scan_id,
            "dry_run": True,
            "status": result.status,
            "resource_scanned": result.resource_scanned,
            "drifts_found": result.drifts_found,
            "drift_events": [e.model_dump() for e in result.drift_events],
        }

    logger.info("Scan queued: %s", scan_id[:8])
    background_tasks.add_task(_run_and_persist, scan_id, body.resource_types)
    return {
        "scan_id": scan_id,
        "dry_run": False,
        "status": "queued",
        "message": "Scan started in background. Check /drifts/ for results shortly.",
    }
