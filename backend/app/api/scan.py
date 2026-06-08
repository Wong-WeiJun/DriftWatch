from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks

from models.drift import ScanTriggerRequest, ScanResult
from app.services.drift_engine import run_scan
from app.services.store import save_scan_result
from app.services.notifier import publish_drift_alert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scan", tags=["scan"])


def _convert_report_to_scan_result(
    report: dict["str", "Any"], scan_id: str
) -> ScanResult:
    summary = report.get("summary", {})

    drift_events: list[dict[str, "Any"]] = []
    for rid, info in report.get("drifted", {}).items():
        resource_type = info.get("resource_type", "unknown")
        for attr, delta in info.get("differences", {}).items():
            drift_events.append(
                {
                    "scan_id": scan_id,
                    "resource_id": info.get("resource_id", rid),
                    "resource_type": _short_type(resource_type),
                    "attribute": attr,
                    "expected": ""
                    if delta.get("tf_value") is None
                    else str(delta["tf_value"]),
                    "actual": ""
                    if delta.get("live_value") is None
                    else str(delta["live_value"]),
                    "severity": "high"
                    if attr
                    in {"instance_type", "instance_class", "publicly_accessible", "ami"}
                    else "medium",
                    "region": "ap-southeast-2",
                }
            )

    return ScanResult(
        scan_id=scan_id,
        resource_scanned=summary.get("tf_resources", 0),
        drifts_found=summary.get("drifted", 0),
        status="completed",
        drift_events=drift_events,
    )


def _short_type(resource_type: str) -> str:
    return {
        "aws_instance": "ec2",
        "aws_s3_bucket": "s3",
        "aws_security_group": "security_group",
        "aws_iam_role": "iam_role",
        "aws_rds_instances": "rds",
    }.get(resource_type, resource_type)


def _run_and_persist(resource_types: list[str] | None) -> None:
    """Background task - runs scan, saves results, sends alert."""
    try:
        report = run_scan()
        scan_id = str(uuid.uuid4())
        result = _convert_report_to_scan_result(report, scan_id)
        save_scan_result(report)
        publish_drift_alert(result)
        logger.info(
            "Scan %s complete - %d drift(s) across %d resources",
            scan_id[:8],
            result.drifts_found,
            result.resource_scanned,
        )
    except Exception:
        logger.exception("Background scan failed")


@router.post("/trigger")
def trigger_scan(
    body: ScanTriggerRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, "Any"]:
    """
    Trigger a drift scan.

    *dry_run=True* → runs scan synchronously, returns full results,
    nothing saved, no alert sent.

    *dry_run=False* → queues scan as background task, returns scan_id
    immediately, saves results and alerts when done.
    """
    if body.dry_run:
        logger.info("Dry run triggered")
        report = run_scan()
        scan_id = str(uuid.uuid4())
        result = _convert_report_to_scan_result(report, scan_id)
        return {
            "scan_id": scan_id,
            "dry_run": True,
            "status": result.status,
            "resources_scanned": result.resource_scanned,
            "drifts_found": result.drifts_found,
            "drift_events": [e.model_dump() for e in result.drift_events],
        }

    scan_id = str(uuid.uuid4())
    logger.info("Scan queued: %s", scan_id[:8])
    background_tasks.add_task(_run_and_persist, body.resource_types)

    return {
        "scan_id": scan_id,
        "dry_run": False,
        "status": "queued",
        "message": "Scan started in background. Check /drifts/ for results shortly.",
    }
