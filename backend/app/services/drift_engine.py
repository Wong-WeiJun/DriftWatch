"""
Drift detection engine — bridges the live resource scanner with the S3-backed
Terraform state parser.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import boto3
import botocore

from app.core.config import settings
from app.services.scanner import (
    get_ec2,
    get_iam_roles,
    get_rds,
    get_s3,
    get_security_groups,
)
from app.services.state_parser import parse_tfstate_from_s3

logger = logging.getLogger(__name__)


def normalise(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return ""
    if isinstance(value, list):
        items = [normalise(v) for v in value]
        try:
            items.sort()
        except TypeError:
            pass
        return json.dumps(items, separators=(",", ":"))
    if isinstance(value, dict):
        return json.dumps(
            {k: normalise(v) for k, v in sorted(value.items())},
            separators=(",", ":"),
        )
    return value


def compute_drift(
    tf_attrs: dict[str, Any],
    live_attrs: dict[str, Any],
    *,
    ignore_fields: tuple[str, ...] = (),
) -> dict[str, dict[str, Any]]:
    diffs: dict[str, dict[str, Any]] = {}
    for key, tf_raw in tf_attrs.items():
        if key.startswith("_") or key in ignore_fields:
            continue
        live_raw = live_attrs.get(key)
        if normalise(tf_raw) != normalise(live_raw):
            diffs[key] = {"tf_value": tf_raw, "live_value": live_raw}
    return diffs


@dataclass(slots=True)
class DriftInfo:
    resource_type: str
    resource_id: str
    terraform_attrs: dict[str, Any]
    live_attrs: dict[str, Any]
    differences: dict[str, dict[str, Any]]
    only_in_live: set[str]
    only_in_tf: set[str] = field(default_factory=set)


def compare_single(
    resource_type: str,
    resource_id: str,
    tf_entry: dict[str, Any],
    live_entry: dict[str, Any],
) -> DriftInfo:
    tf_fields = {k for k in tf_entry if not k.startswith("_")}
    live_fields = {k for k in live_entry if not k.startswith("_")}

    only_in_live = live_fields - tf_fields
    only_in_tf = tf_fields - live_fields

    tf_attrs = {k: tf_entry[k] for k in tf_fields if k in live_entry}
    live_attrs = {k: live_entry[k] for k in tf_fields if k in live_entry}

    differences = compute_drift(tf_attrs, live_attrs)

    for k in only_in_tf:
        differences[k] = {"tf_value": tf_entry[k], "live_value": None}

    return DriftInfo(
        resource_type=resource_type,
        resource_id=resource_id,
        terraform_attrs=tf_entry,
        live_attrs=live_entry,
        differences=differences,
        only_in_live=only_in_live,
        only_in_tf=only_in_tf,
    )


def run_scan(
    resource_types: list[str] | None = None,
    scan_id: str | None = None,
) -> dict[str, Any]:
    """Fetch S3 TF state, scan live AWS, compare and return a report dict."""

    tfstate_bucket = settings.TERRAFORM_STATE_BUCKET
    tfstate_key = settings.TERRAFORM_STATE_KEY

    logger.info("Fetching Terraform state from S3…")
    tf_resources = parse_tfstate_from_s3(
        bucket=tfstate_bucket,
        key=tfstate_key,
        skip_data=True,
    )
    logger.info("Loaded %d resources from TF state", len(tf_resources))

    _TYPE_MAP: dict[str, str] = {
        "ec2": "aws_instance",
        "s3": "aws_s3_bucket",
        "security_group": "aws_security_group",
        "iam_role": "aws_iam_role",
        "rds": "aws_rds_instances",
    }

    tf_by_type: dict[str, dict[str, dict[str, Any]]] = {}
    for key, entry in tf_resources.items():
        t = entry["_type"]
        tf_by_type.setdefault(t, {})[key] = entry

    all_scanners: dict[str, Any] = {
        "aws_instance": get_ec2,
        "aws_s3_bucket": get_s3,
        "aws_security_group": get_security_groups,
        "aws_iam_role": get_iam_roles,
        "aws_rds_instances": get_rds,
    }

    if resource_types:
        allowed = {_TYPE_MAP.get(rt, rt) for rt in resource_types}
        scanners = {k: v for k, v in all_scanners.items() if k in allowed}
        logger.info("Scan limited to types: %s", sorted(scanners.keys()))
    else:
        scanners = all_scanners

    live_by_type: dict[str, dict[str, dict[str, Any]]] = {}
    for unified_type, scanner_fn in scanners.items():
        try:
            live_by_type[unified_type] = scanner_fn()
            logger.info(
                "Scanned %s: %d resources",
                unified_type,
                len(live_by_type[unified_type]),
            )
        except Exception:
            logger.exception("Scanner %s failed", unified_type)
            live_by_type[unified_type] = {}

    drifted: dict[str, Any] = {}
    missing_in_live: list[dict[str, Any]] = []
    missing_in_tf: list[dict[str, Any]] = []

    for unified_type, tf_map in tf_by_type.items():
        live_map = live_by_type.get(unified_type, {})
        for tf_key, tf_entry in tf_map.items():
            rid = tf_entry.get("id", tf_key)
            if rid not in live_map:
                missing_in_live.append(
                    {"resource_type": unified_type, "resource_id": rid}
                )
                continue
            info = compare_single(unified_type, rid, tf_entry, live_map[rid])
            if info.differences:
                drifted[rid] = {
                    "resource_type": unified_type,
                    "resource_id": rid,
                    "differences": info.differences,
                    "only_in_live": sorted(info.only_in_live),
                    "only_in_tf": sorted(info.only_in_tf),
                }

    for unified_type, live_map in live_by_type.items():
        tf_map = tf_by_type.get(unified_type, {})
        for live_key, live_entry in live_map.items():
            rid = live_entry.get("id", live_key)
            if rid not in tf_map:
                missing_in_tf.append(
                    {"resource_type": unified_type, "resource_id": rid}
                )

    live_total = sum(len(v) for v in live_by_type.values())
    tf_total = sum(len(v) for v in tf_by_type.values())

    report: dict[str, Any] = {
        "summary": {
            "tf_resources": tf_total,
            "live_resources": live_total,
            "drifted": len(drifted),
            "missing_in_live": len(missing_in_live),
            "missing_in_tf": len(missing_in_tf),
        },
        "drifted": drifted,
        "missing_in_live": missing_in_live,
        "missing_in_tf": missing_in_tf,
    }

    logger.info(
        "Scan complete — drifted=%d missing_in_live=%d missing_in_tf=%d",
        len(drifted),
        len(missing_in_live),
        len(missing_in_tf),
    )
    return report


def save_drift_result(report: dict[str, Any]) -> str:
    from datetime import datetime, timezone

    table_name = settings.DYNAMODB_TABLE_NAME
    ddb = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    table = ddb.Table(table_name)

    pk = str(uuid.uuid4())
    item = {
        "event_id": pk,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": report["summary"],
        "drifted": report["drifted"],
        "missing_in_live": report["missing_in_live"],
        "missing_in_tf": report["missing_in_tf"],
    }
    table.put_item(Item=item)
    logger.info("Drift report saved to DynamoDB (%s:%s)", table_name, pk)
    return pk


def publish_alert(report: dict[str, Any]) -> None:
    topic_arn = settings.SNS_TOPIC_ARN
    if not topic_arn:
        logger.warning("SNS_TOPIC_ARN not set — skipping alert")
        return

    sns = boto3.client("sns", region_name=settings.AWS_REGION)
    summary = report["summary"]
    msg = (
        f"DriftWatch alert — {summary['drifted']} resources drifted, "
        f"{summary['missing_in_live']} missing in live AWS, "
        f"{summary['missing_in_tf']} not managed by Terraform."
    )
    try:
        sns.publish(
            TopicArn=topic_arn,
            Subject="DriftWatch Drift Detected",
            Message=msg,
        )
        logger.info("Alert published to SNS (%s)", topic_arn)
    except botocore.exceptions.ClientError:
        logger.exception("Failed to publish SNS alert")


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)1.1s %(asctime)s %(name)s:%(lineno)d] %(message)s",
        datefmt="%y%m%d %H:%M:%S",
    )

    report = run_scan()

    print("\n" + "=" * 60)
    print("DRIFT REPORT")
    print("=" * 60)
    for key, val in report["summary"].items():
        print(f"  {key}: {val}")

    if report["drifted"]:
        print("\n--- Drifted resources ---")
        for rid, info in report["drifted"].items():
            print(f"\n{info['resource_type']}  {rid}")
            for f, delta in info["differences"].items():
                print(f"  {f}: TF={delta['tf_value']!r}  LIVE={delta['live_value']!r}")

    if report["missing_in_live"]:
        print("\n--- Missing in live AWS ---")
        for item in report["missing_in_live"]:
            print(f"  {item['resource_type']}  {item['resource_id']}")

    if report["missing_in_tf"]:
        print("\n--- Not managed by Terraform ---")
        for item in report["missing_in_tf"]:
            print(f"  {item['resource_type']}  {item['resource_id']}")
