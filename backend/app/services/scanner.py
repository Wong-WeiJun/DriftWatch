from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


def _client(service: str) -> boto3.client:
    """Create a boto3 client, routing to LocalStack when AWS_ENDPOINT_URL is set."""
    kwargs: dict[str, Any] = {"region_name": settings.AWS_REGION}
    if settings.AWS_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL
    return boto3.client(service, **kwargs)


def _tags_dict(tag_list: list[dict[str, str]] | None) -> dict[str, str]:
    """Convert AWS Tag list [{"Key": k, "Value": v}] into a plain dict."""
    if not tag_list:
        return {}
    return {
        t["Key"]: t.get("Value", "")
        for t in tag_list
        if isinstance(t, dict) and "Key" in t
    }


def get_ec2() -> dict[str, dict[str, Any]]:
    ec2 = _client("ec2")
    instances = {}
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                iid = instance["InstanceId"]
                tags = _tags_dict(instance.get("Tags"))
                entry: dict[str, Any] = {
                    "_type": "aws_instance",
                    "id": iid,
                    "instance_type": instance.get("InstanceType", ""),
                    "ami": instance.get("ImageId", ""),
                    "state": instance["State"]["Name"],
                    "subnet_id": instance.get("SubnetId", ""),
                    "vpc_id": instance.get("VpcId", ""),
                    "key_name": instance.get("KeyName", ""),
                }
                if tags:
                    entry["tags"] = tags
                instances[iid] = entry
    return instances


def get_s3() -> dict[str, dict[str, Any]]:
    s3 = _client("s3")
    buckets = {}
    for bucket in s3.list_buckets().get("Buckets", []):
        name = bucket["Name"]
        versioning = "Disabled"
        try:
            v = s3.get_bucket_versioning(Bucket=name)
            versioning = v.get("Status", "Disabled")
        except Exception:
            pass

        public_block = {}
        try:
            pb = s3.get_public_access_block(Bucket=name)
            public_block = pb.get("PublicAccessBlockConfiguration", {})
        except Exception:
            pass

        tags: dict[str, str] = {}
        try:
            tag_resp = s3.get_bucket_tagging(Bucket=name)
            tags = _tags_dict(tag_resp.get("TagSet"))
        except Exception:
            pass

        entry: dict[str, Any] = {
            "_type": "aws_s3_bucket",
            "id": name,
            "bucket": name,
            "versioning": versioning,
            "block_public_acls": str(public_block.get("BlockPublicAcls", False)),
            "block_public_policy": str(public_block.get("BlockPublicPolicy", False)),
        }
        if tags:
            entry["tags"] = tags
        buckets[name] = entry
    return buckets


def get_security_groups() -> dict[str, dict[str, Any]]:
    ec2 = _client("ec2")
    sgs = {}
    paginator = ec2.get_paginator("describe_security_groups")
    for page in paginator.paginate():
        for sg in page["SecurityGroups"]:
            sid = sg["GroupId"]
            tags = _tags_dict(sg.get("Tags"))
            entry: dict[str, Any] = {
                "_type": "aws_security_group",
                "id": sid,
                "name": sg.get("GroupName", ""),
                "description": sg.get("Description", ""),
                "vpc_id": sg.get("VpcId", ""),
                "ingress_rule_count": str(len(sg.get("IpPermissions", []))),
                "egress_rule_count": str(len(sg.get("IpPermissionsEgress", []))),
            }
            if tags:
                entry["tags"] = tags
            sgs[sid] = entry
    return sgs


def get_iam_roles() -> dict[str, dict[str, Any]]:
    iam = _client("iam")
    roles = {}
    paginator = iam.get_paginator("list_roles")
    for page in paginator.paginate():
        for role in page["Roles"]:
            name = role["RoleName"]
            tags: dict[str, str] = {}
            try:
                tag_resp = iam.list_role_tags(RoleName=name)
                tags = _tags_dict(tag_resp.get("Tags"))
            except Exception:
                pass
            entry: dict[str, Any] = {
                "_type": "aws_iam_role",
                "id": name,
                "name": name,
                "path": role.get("Path", "/"),
                "max_session_duration": str(role.get("MaxSessionDuration", 3600)),
            }
            if tags:
                entry["tags"] = tags
            roles[name] = entry
    return roles


def get_rds() -> dict[str, dict[str, Any]]:
    rds = _client("rds")
    instances = {}
    try:
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page["DBInstances"]:
                dbid = db["DBInstanceIdentifier"]
                instances[dbid] = {
                    "_type": "aws_rds_instances",
                    "id": dbid,
                    "instance_class": db.get("DBInstanceClass", ""),
                    "engine": db.get("Engine", ""),
                    "engine_version": db.get("EngineVersion", ""),
                    "multi_az": str(db.get("MultiAZ", False)),
                    "publicly_accessible": str(db.get("PubliclyAccessible", False)),
                    "deletion_protection": str(db.get("DeletionProtection", False)),
                }
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "InternalFailure":
            logger.warning(
                "RDS not available in this environment (LocalStack?), skipping"
            )
        else:
            raise
    return instances
