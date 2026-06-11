import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings
from models.drift import ScanResult

logger = logging.getLogger(__name__)

_sns = None


def get_sns():
    global _sns
    if _sns is None:
        kwargs = {"region_name": settings.AWS_REGION}
        endpoint = settings.AWS_ENDPOINT_URL
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        _sns = boto3.client("sns", **kwargs)
    return _sns


def publish_drift_alert(result: ScanResult) -> None:
    if not settings.SNS_TOPIC_ARN:
        logger.info("SNS_TOPIC_ARN not set, skipping alert")
        return

    if result.drifts_found == 0:
        logger.info("No drift detected, skipping alert")
        return

    high = [e for e in result.drift_events if e.severity == "high"]
    medium = [e for e in result.drift_events if e.severity == "medium"]
    low = [e for e in result.drift_events if e.severity == "low"]

    lines = [
        f"Driftwatch detected {result.drifts_found} drift(s) in scan {result.scan_id[:8]}",
        "",
        f"Resources scanned: {result.resource_scanned}",
        f"High severity:     {len(high)}",
        f"Medium severity:   {len(medium)}",
        f"Low severity:      {len(low)}",
        "",
    ]

    shown = result.drift_events[:10]
    for event in shown:
        lines.append(
            f"[{event.severity.upper()}] {event.resource_type}/{event.resource_id}"
        )
        lines.append(
            f"  {event.attribute}: expected={event.expected!r}, actual={event.actual!r}"
        )
        lines.append("")

    if result.drifts_found > 10:
        lines.append(f"... and {result.drifts_found - 10} more drift(s) not shown.")

    message = "\n".join(lines)

    subject_severity = "HIGH" if high else "MEDIUM" if medium else "LOW"
    subject = (
        f"[Driftwatch] [{subject_severity}] {result.drifts_found} drift(s) detected"
    )

    try:
        get_sns().publish(
            TopicArn=settings.SNS_TOPIC_ARN,
            Subject=subject,
            Message=message,
        )
        logger.info(f"Drift alert published to SNS: {result.drifts_found} drift(s)")
    except ClientError as e:
        logger.error(f"Failed to publish SNS alert: {e}")
