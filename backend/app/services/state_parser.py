import json
import boto3
from pathlib import Path
from typing import Any

from app.core.config import settings

_TYPE_ALIASES: dict[str, str] = {
    "aws_db_instance": "aws_rds_instance",
}


def _extract_common(attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("arn", "region", "vpc_id", "owner_id", "availability_zone"):
        if key in attrs and attrs[key] not in (None, ""):
            out[key] = attrs[key]
    if "tags" in attrs and isinstance(attrs["tags"], dict) and attrs["tags"]:
        out["tags"] = attrs["tags"]
    return out


def _extract_by_type(res_type: str, attrs: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    if res_type == "aws_instance":
        out["instance_type"] = attrs.get("instance_type", "")
        out["ami"] = attrs.get("ami", "")
        out["subnet_id"] = attrs.get("subnet_id", "")
        out["key_name"] = attrs.get("key_name", "")
        out["public_ip"] = attrs.get("public_ip", "")
        out["private_ip"] = attrs.get("private_ip", "")
        out["state"] = attrs.get("instance_state", "")

    elif res_type == "aws_s3_bucket":
        out["bucket"] = attrs.get("bucket", attrs.get("id", ""))

    elif res_type == "aws_s3_bucket_public_access_block":
        out["bucket"] = attrs.get("bucket", "")
        out["block_public_acls"] = str(attrs.get("block_public_acls", False))
        out["block_public_policy"] = str(attrs.get("block_public_policy", False))
        out["ignore_public_acls"] = str(attrs.get("ignore_public_acls", False))
        out["restrict_public_buckets"] = str(
            attrs.get("restrict_public_buckets", False)
        )

    elif res_type == "aws_security_group":
        out["name"] = attrs.get("name", attrs.get("group_name", ""))
        out["description"] = attrs.get("description", "")
        out["ingress_rule_count"] = str(len(attrs.get("ingress", [])))
        out["egress_rule_count"] = str(len(attrs.get("egress", [])))

    elif res_type == "aws_vpc":
        out["cidr_block"] = attrs.get("cidr_block", "")
        out["enable_dns_hostnames"] = str(attrs.get("enable_dns_hostnames", False))
        out["enable_dns_support"] = str(attrs.get("enable_dns_support", False))
        out["instance_tenancy"] = attrs.get("instance_tenancy", "default")
        out["default_network_acl_id"] = attrs.get("default_network_acl_id", "")
        out["default_route_table_id"] = attrs.get("default_route_table_id", "")
        out["default_security_group_id"] = attrs.get("default_security_group_id", "")

    elif res_type == "aws_subnet":
        out["cidr_block"] = attrs.get("cidr_block", "")
        out["availability_zone"] = attrs.get("availability_zone", "")
        out["map_public_ip_on_launch"] = str(
            attrs.get("map_public_ip_on_launch", False)
        )
        out["assign_ipv6_address_on_creation"] = str(
            attrs.get("assign_ipv6_address_on_creation", False)
        )

    elif res_type == "aws_internet_gateway":
        out["vpc_id"] = attrs.get("vpc_id", "")

    elif res_type == "aws_route_table":
        out["vpc_id"] = attrs.get("vpc_id", "")
        out["route_count"] = str(len(attrs.get("route", [])))

    elif res_type == "aws_route_table_association":
        out["subnet_id"] = attrs.get("subnet_id", "")
        out["gateway_id"] = attrs.get("gateway_id", "")
        out["route_table_id"] = attrs.get("route_table_id", "")

    elif res_type == "aws_eip":
        out["public_ip"] = attrs.get("public_ip", "")
        out["private_ip"] = attrs.get("private_ip", "")
        out["instance"] = attrs.get("instance", "")
        out["domain"] = attrs.get("domain", "")
        out["network_interface"] = attrs.get("network_interface", "")

    elif res_type == "aws_eip_association":
        out["allocation_id"] = attrs.get("allocation_id", "")
        out["instance_id"] = attrs.get("instance_id", "")
        out["network_interface_id"] = attrs.get("network_interface_id", "")

    elif res_type in ("aws_nat_gateway",):
        out["subnet_id"] = attrs.get("subnet_id", "")
        out["allocation_id"] = attrs.get("allocation_id", "")

    elif res_type == "aws_iam_role":
        out["name"] = attrs.get("name", attrs.get("id", ""))
        out["path"] = attrs.get("path", "/")
        out["max_session_duration"] = str(attrs.get("max_session_duration", 3600))
        out["assume_role_policy"] = attrs.get("assume_role_policy", "")

    elif res_type == "aws_iam_role_policy_attachment":
        out["role"] = attrs.get("role", "")
        out["policy_arn"] = attrs.get("policy_arn", "")

    elif res_type == "aws_ecs_cluster":
        out["name"] = attrs.get("name", "")
        out["setting_container_insights"] = str(
            any(
                s.get("name") == "containerInsights" and s.get("value") == "enabled"
                for s in attrs.get("setting", [])
            )
        )

    elif res_type == "aws_ecs_task_definition":
        out["family"] = attrs.get("family", "")
        out["network_mode"] = attrs.get("network_mode", "")
        out["cpu"] = attrs.get("cpu", "")
        out["memory"] = attrs.get("memory", "")
        out["requires_compatibilities"] = attrs.get("requires_compatibilities", [])
        out["execution_role_arn"] = attrs.get("execution_role_arn", "")
        out["task_role_arn"] = attrs.get("task_role_arn", "")
        container_defs = attrs.get("container_definitions", "[]")
        if isinstance(container_defs, str):
            try:
                container_defs = json.loads(container_defs)
            except json.JSONDecodeError:
                container_defs = []
        out["container_count"] = str(len(container_defs))
        out["container_images"] = [
            c.get("image", "") for c in container_defs if isinstance(c, dict)
        ]
        out["container_env_vars"] = {
            c.get("name", ""): [
                {e.get("name"): e.get("value") for e in c.get("environment", [])}
            ]
            for c in container_defs
            if isinstance(c, dict)
        }

    elif res_type == "aws_ecs_service":
        out["name"] = attrs.get("name", "")
        out["cluster"] = attrs.get("cluster", "")
        out["task_definition"] = attrs.get("task_definition", "")
        out["desired_count"] = str(attrs.get("desired_count", 1))
        out["launch_type"] = attrs.get("launch_type", "")
        out["scheduling_strategy"] = attrs.get("scheduling_strategy", "")
        net_cfg = attrs.get("network_configuration", {})
        if isinstance(net_cfg, dict):
            awsvpc = net_cfg.get("awsvpc_configuration", {})
            if isinstance(awsvpc, dict):
                out["subnets"] = awsvpc.get("subnets", [])
                out["security_groups"] = awsvpc.get("security_groups", [])
                out["assign_public_ip"] = str(
                    awsvpc.get("assign_public_ip", False)
                ).lower()

    elif res_type == "aws_db_instance":
        out["instance_class"] = attrs.get("instance_class", "")
        out["engine"] = attrs.get("engine", "")
        out["engine_version"] = attrs.get("engine_version", "")
        out["multi_az"] = str(attrs.get("multi_az", False))
        out["publicly_accessible"] = str(attrs.get("publicly_accessible", False))
        out["deletion_protection"] = str(attrs.get("deletion_protection", False))
        out["allocated_storage"] = str(attrs.get("allocated_storage", "0"))
        out["storage_encrypted"] = str(attrs.get("storage_encrypted", False))
        out["backup_retention_period"] = str(attrs.get("backup_retention_period", "0"))

    elif res_type == "aws_sns_topic":
        out["name"] = attrs.get("name", "")
        out["display_name"] = attrs.get("display_name", "")
        out["fifo_topic"] = str(attrs.get("fifo_topic", False))
        out[" kms_master_key_id "] = attrs.get("kms_master_key_id", "")

    elif res_type == "aws_sns_topic_subscription":
        out["topic_arn"] = attrs.get("topic_arn", "")
        out["protocol"] = attrs.get("protocol", "")
        out["endpoint"] = attrs.get("endpoint", "")
        out["raw_message_delivery"] = str(attrs.get("raw_message_delivery", False))

    elif res_type == "aws_ecr_repository":
        out["name"] = attrs.get("name", "")
        out["repository_url"] = attrs.get("repository_url", "")
        out["image_tag_mutability"] = attrs.get("image_tag_mutability", "MUTABLE")
        scan_cfg = attrs.get("image_scanning_configuration")
        scan_on_push = False
        if isinstance(scan_cfg, list) and scan_cfg:
            scan_on_push = scan_cfg[0].get("scan_on_push", False)
        elif isinstance(scan_cfg, dict):
            scan_on_push = scan_cfg.get("scan_on_push", False)
        out["scan_on_push"] = str(scan_on_push)

    elif res_type == "aws_network_interface":
        out["subnet_id"] = attrs.get("subnet_id", "")
        out["private_ips"] = attrs.get("private_ips", [])
        out["security_groups"] = attrs.get("security_groups", [])

    elif res_type == "aws_network_interface_attachment":
        out["instance_id"] = attrs.get("instance_id", "")
        out["network_interface_id"] = attrs.get("network_interface_id", "")
        out["device_index"] = str(attrs.get("device_index", "0"))

    return out


def _parse_state_dict(
    state: dict[str, Any], *, skip_data: bool = True
) -> dict[str, dict[str, Any]]:
    resources: dict[str, dict[str, Any]] = {}

    for res in state.get("resources", []):
        mode = res.get("mode", "managed")
        if skip_data and mode == "data":
            continue

        res_type = res.get("type", "unknown")
        res_name = res.get("name", "unknown")
        mapped_type = _TYPE_ALIASES.get(res_type, res_type)

        for inst in res.get("instances", []):
            attrs = inst.get("attributes", {})
            index_key = inst.get("index_key")

            resource_id = attrs.get("id", "")
            if not resource_id:
                resource_id = f"{res_type}.{res_name}"
                if index_key is not None:
                    resource_id = f"{resource_id}[{index_key}]"

            key = resource_id
            if index_key is not None:
                key = f"{resource_id}#{index_key}"

            entry: dict[str, Any] = {
                "_type": mapped_type,
                "_tf_type": res_type,
                "_name": res_name,
                "_mode": mode,
                "id": resource_id,
            }
            if index_key is not None:
                entry["_index"] = index_key

            entry.update(_extract_common(attrs))
            entry.update(_extract_by_type(res_type, attrs))

            resources[key] = entry

    return resources


def parse_tfstate(
    file_path: str | Path, *, skip_data: bool = True
) -> dict[str, dict[str, Any]]:
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as f:
        state = json.load(f)
    return _parse_state_dict(state, skip_data=skip_data)


def parse_tfstate_raw(file_path: str | Path) -> dict[str, Any]:
    """Return the raw Terraform state JSON dict without flattening resources."""
    with Path(file_path).open("r", encoding="utf-8") as f:
        return json.load(f)


def print_tfstate_summary(file_path: str | Path, *, skip_data: bool = True) -> None:
    """Print a human-readable summary of a local state file."""
    path = Path(file_path)
    raw = parse_tfstate_raw(path)
    resources = parse_tfstate(path, skip_data=skip_data)

    print(f"Terraform State: {path}")
    print(f"  Version: {raw.get('version', 'N/A')}")
    print(f"  Terraform Version: {raw.get('terraform_version', 'N/A')}")
    print(f"  Serial: {raw.get('serial', 'N/A')}")

    all_resources = raw.get("resources", [])
    data_count = sum(1 for r in all_resources if r.get("mode") == "data")
    managed_count = len(all_resources) - data_count
    print(f"  Resource blocks: {len(all_resources)}")
    print(f"    Managed: {managed_count}")
    print(f"    Data:    {data_count} {'(skipped)' if skip_data else '(included)'}")
    print()

    by_type: dict[str, list[dict[str, Any]]] = {}
    for res in resources.values():
        by_type.setdefault(res["_tf_type"], []).append(res)

    for tf_type, items in sorted(by_type.items()):
        print(f"[{tf_type}] — {len(items)} instance(s)")
        for item in items:
            name = item["_name"]
            idx = item.get("_index")
            rid = item["id"]
            label = f"{name}[{idx}]" if idx is not None else name
            print(f"  - {label} (id: {rid})")

            extras_parts = []
            for field_name, display in (
                ("arn", "arn"),
                ("cidr_block", "cidr"),
                ("public_ip", "public_ip"),
                ("private_ip", "private_ip"),
                ("region", "region"),
                ("vpc_id", "vpc"),
                ("subnet_id", "subnet"),
                ("bucket", "bucket"),
                ("availability_zone", "az"),
                ("instance_type", "type"),
                ("desired_count", "desired"),
                ("launch_type", "launch"),
                ("engine", "engine"),
                ("protocol", "protocol"),
            ):
                val = item.get(field_name)
                if val not in (None, "", [], {}):
                    if isinstance(val, str) and len(val) > 60:
                        val = val[:57] + "..."
                    extras_parts.append(f"{display}={val}")

            if extras_parts:
                print(f"    {', '.join(extras_parts)}")

            tags = item.get("tags")
            if tags:
                print(f"    tags={tags}")
        print()

    print(f"Total parsed resource instances: {len(resources)}")


def _get_s3_client() -> boto3.client:
    return boto3.client("s3", region_name=settings.AWS_REGION)


def fetch_tfstate_from_s3(
    bucket: str | None = None,
    key: str = "terraform.tfstate",
) -> dict[str, Any]:

    bucket = bucket or settings.TF_STATE_BUCKET
    if not bucket or bucket == "state_bucket":
        raise ValueError(
            "No S3 bucket configured. Set TF_STATE_BUCKET in .env or pass 'bucket'."
        )

    s3 = _get_s3_client()
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode("utf-8")
    return json.loads(body)


def list_tfstate_objects(
    bucket: str | None = None,
    prefix: str = "",
) -> list[dict[str, Any]]:

    bucket = bucket or settings.TF_STATE_BUCKET
    if not bucket or bucket == "state_bucket":
        raise ValueError(
            "No S3 bucket configured. Set TF_STATE_BUCKET in .env or pass 'bucket'."
        )

    s3 = _get_s3_client()
    paginator = s3.get_paginator("list_objects_v2")

    objects: list[dict[str, Any]] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".tfstate"):
                objects.append(
                    {
                        "key": key,
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                        "etag": obj["ETag"].strip('"'),
                    }
                )

    objects.sort(key=lambda o: o["last_modified"], reverse=True)
    return objects


def find_latest_tfstate_key(
    bucket: str | None = None,
    prefix: str = "",
) -> str | None:

    objs = list_tfstate_objects(bucket=bucket, prefix=prefix)
    return objs[0]["key"] if objs else None


def parse_tfstate_from_s3(
    bucket: str | None = None,
    key: str | None = None,
    *,
    skip_data: bool = True,
) -> dict[str, dict[str, Any]]:
    bucket = bucket or settings.TF_STATE_BUCKET
    if not key:
        key = find_latest_tfstate_key(bucket=bucket)
        if not key:
            raise FileNotFoundError(f"No .tfstate file found in s3://{bucket}")

    state = fetch_tfstate_from_s3(bucket=bucket, key=key)
    return _parse_state_dict(state, skip_data=skip_data)


def get_state_summary_from_s3(
    bucket: str | None = None,
    key: str | None = None,
    *,
    skip_data: bool = True,
) -> dict[str, Any]:
    """Return high-level metadata about the S3-hosted state file *and* parsed resources.

    This is useful for the drift scanner to quickly compare serial numbers,
    terraform versions, or resource counts without parsing twice.

    Example return value::

        {
            "bucket": "driftwatch",
            "key": "terraform.tfstate",
            "version": 4,
            "terraform_version": "1.8.0",
            "serial": 42,
            "lineage": "a1b2c3d4-",
            "resource_count": 17,
            "resources": { ... flattened resource map ... },
        }
    """
    bucket = bucket or settings.TF_STATE_BUCKET
    if not key:
        key = find_latest_tfstate_key(bucket=bucket)
        if not key:
            raise FileNotFoundError(f"No .tfstate file found in s3://{bucket}")

    state = fetch_tfstate_from_s3(bucket=bucket, key=key)
    resources = _parse_state_dict(state, skip_data=skip_data)

    all_raw_resources = state.get("resources", [])
    data_count = sum(1 for r in all_raw_resources if r.get("mode") == "data")

    return {
        "bucket": bucket,
        "key": key,
        "version": state.get("version"),
        "terraform_version": state.get("terraform_version"),
        "serial": state.get("serial"),
        "lineage": state.get("lineage"),
        "resource_blocks": len(all_raw_resources),
        "managed_blocks": len(all_raw_resources) - data_count,
        "data_blocks": data_count,
        "resource_count": len(resources),
        "resources": resources,
    }
