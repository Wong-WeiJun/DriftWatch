"""
Seed LocalStack with a demo-sized Terraform state and matching live resources
so local scans look closer to a real account (~40 TF resources + a few drifts).

Strategy:
  1. Create (or reuse) live EC2 / SG / S3 / IAM resources in LocalStack
  2. Read back their real IDs
  3. Write terraform.tfstate keyed to those IDs, with intentional mismatches
     so the dashboard shows drifted / missing_in_live / missing_in_tf findings
"""

from __future__ import annotations

import json
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

REGION = "ap-southeast-2"
ENDPOINT = "http://localstack:4566"
BUCKET = "driftwatch-local-state"
PROVIDER = 'provider["registry.terraform.io/hashicorp/aws"]'

# Demo scale — target roughly production-ish resource counts.
NUM_EC2 = 8
NUM_SG = 8
NUM_S3 = 10
NUM_IAM = 10


def get_client(service: str):
    return boto3.client(service, endpoint_url=ENDPOINT, region_name=REGION)


def _tf_resource(
    res_type: str, name: str, attributes: dict[str, Any]
) -> dict[str, Any]:
    return {
        "mode": "managed",
        "type": res_type,
        "name": name,
        "provider": PROVIDER,
        "instances": [{"schema_version": 0, "attributes": attributes}],
    }


def create_vpc_for_ec2(ec2) -> tuple[str, str]:
    """Return (vpc_id, subnet_id), creating a tagged seed VPC if needed."""
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "tag:Name", "Values": ["seed-vpc"]}])
    if vpcs["Vpcs"]:
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        subnets = ec2.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "tag:Name", "Values": ["seed-subnet"]},
            ]
        )
        if subnets["Subnets"]:
            return vpc_id, subnets["Subnets"][0]["SubnetId"]
        subnet = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24")
        subnet_id = subnet["Subnet"]["SubnetId"]
        ec2.create_tags(
            Resources=[subnet_id], Tags=[{"Key": "Name", "Value": "seed-subnet"}]
        )
        return vpc_id, subnet_id

    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]
    ec2.create_tags(Resources=[vpc_id], Tags=[{"Key": "Name", "Value": "seed-vpc"}])
    subnet = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24")
    subnet_id = subnet["Subnet"]["SubnetId"]
    ec2.create_tags(
        Resources=[subnet_id], Tags=[{"Key": "Name", "Value": "seed-subnet"}]
    )
    return vpc_id, subnet_id


def ensure_ec2(ec2, subnet_id: str) -> list[dict[str, Any]]:
    """Ensure NUM_EC2 demo instances exist; return live instance dicts."""
    existing = []
    for page in ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "tag:driftwatch-demo", "Values": ["true"]}]
    ):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                if inst["State"]["Name"] == "terminated":
                    continue
                existing.append(inst)

    needed = max(0, NUM_EC2 - len(existing))
    for i in range(needed):
        idx = len(existing) + i + 1
        # Alternate instance types so we can introduce drift on one of them.
        itype = "t3.micro" if idx != 2 else "t3.small"
        try:
            resp = ec2.run_instances(
                ImageId="ami-0demo000000000001",
                MinCount=1,
                MaxCount=1,
                InstanceType=itype,
                SubnetId=subnet_id,
                TagSpecifications=[
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": "Name", "Value": f"demo-web-{idx:02d}"},
                            {"Key": "driftwatch-demo", "Value": "true"},
                        ],
                    }
                ],
            )
            existing.append(resp["Instances"][0])
            print(f"Created EC2 demo-web-{idx:02d}")
        except ClientError as e:
            print(f"EC2 create skipped: {e}")

    # Refresh list so attributes are current
    refreshed = []
    for page in ec2.get_paginator("describe_instances").paginate(
        Filters=[{"Name": "tag:driftwatch-demo", "Values": ["true"]}]
    ):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                if inst["State"]["Name"] != "terminated":
                    refreshed.append(inst)
    return refreshed[:NUM_EC2]


def ensure_security_groups(ec2, vpc_id: str) -> list[dict[str, Any]]:
    groups = []
    for i in range(1, NUM_SG + 1):
        name = f"demo-sg-{i:02d}"
        try:
            existing = ec2.describe_security_groups(
                Filters=[
                    {"Name": "group-name", "Values": [name]},
                    {"Name": "vpc-id", "Values": [vpc_id]},
                ]
            )["SecurityGroups"]
            if existing:
                sg_detail = existing[0]
            else:
                sg = ec2.create_security_group(
                    GroupName=name,
                    Description=f"Demo security group {i}",
                    VpcId=vpc_id,
                    TagSpecifications=[
                        {
                            "ResourceType": "security-group",
                            "Tags": [
                                {"Key": "Name", "Value": name},
                                {"Key": "driftwatch-demo", "Value": "true"},
                            ],
                        }
                    ],
                )
                print(f"Created SG {name}")
                sg_detail = ec2.describe_security_groups(GroupIds=[sg["GroupId"]])[
                    "SecurityGroups"
                ][0]

            # First SG always has an open 443 rule so TF can claim 0 ingress → high drift.
            # Other odd-numbered groups get the same for variety in live data.
            wants_ingress = i == 1 or i % 2 == 1
            if wants_ingress and not sg_detail.get("IpPermissions"):
                try:
                    ec2.authorize_security_group_ingress(
                        GroupId=sg_detail["GroupId"],
                        IpPermissions=[
                            {
                                "IpProtocol": "tcp",
                                "FromPort": 443,
                                "ToPort": 443,
                                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                            }
                        ],
                    )
                    sg_detail = ec2.describe_security_groups(
                        GroupIds=[sg_detail["GroupId"]]
                    )["SecurityGroups"][0]
                except ClientError:
                    pass

            groups.append(sg_detail)
        except ClientError as e:
            print(f"SG {name} skipped: {e}")
    return groups


def ensure_s3_buckets(s3) -> list[str]:
    names = [f"demo-app-bucket-{i:02d}" for i in range(1, NUM_S3 + 1)]
    for i, name in enumerate(names):
        try:
            s3.create_bucket(
                Bucket=name,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
            print(f"Created S3 bucket {name}")
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
                print(f"S3 {name} skipped: {e}")
                continue
        # Public access block — TF intentionally mismatches on bucket 03
        try:
            s3.put_public_access_block(
                Bucket=name,
                PublicAccessBlockConfiguration={
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                },
            )
        except ClientError:
            pass
        # Tag every bucket; bucket 06 gets an Extra live tag for a low-severity tag drift
        try:
            tag_set = [
                {"Key": "Name", "Value": name},
                {"Key": "driftwatch-demo", "Value": "true"},
            ]
            if i == 5:
                tag_set.append({"Key": "Owner", "Value": "platform-team"})
            s3.put_bucket_tagging(Bucket=name, Tagging={"TagSet": tag_set})
        except ClientError:
            pass
        # Enable versioning on bucket 05 so TF (Disabled) diverges → medium
        if i == 4:
            try:
                s3.put_bucket_versioning(
                    Bucket=name,
                    VersioningConfiguration={"Status": "Enabled"},
                )
            except ClientError:
                pass
    return names


def ensure_iam_roles(iam) -> list[dict[str, Any]]:
    roles = []
    for i in range(1, NUM_IAM + 1):
        name = f"demo-role-{i:02d}"
        try:
            iam.create_role(
                RoleName=name,
                AssumeRolePolicyDocument=json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": "ec2.amazonaws.com"},
                                "Action": "sts:AssumeRole",
                            }
                        ],
                    }
                ),
                Path="/demo/",
                MaxSessionDuration=3600,
                Tags=[
                    {"Key": "Name", "Value": name},
                    {"Key": "driftwatch-demo", "Value": "true"},
                ],
            )
            print(f"Created IAM role {name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "EntityAlreadyExists":
                print(f"IAM {name} skipped: {e}")
                continue
        try:
            roles.append(iam.get_role(RoleName=name)["Role"])
        except ClientError as e:
            print(f"IAM get {name} skipped: {e}")
    return roles


def build_tfstate(
    instances: list[dict[str, Any]],
    security_groups: list[dict[str, Any]],
    buckets: list[str],
    roles: list[dict[str, Any]],
    subnet_id: str,
) -> dict[str, Any]:
    """Build a TF state that mostly matches live, with intentional drifts.

    Demo drift matrix (so the dashboard shows high / medium / low):
      HIGH   — EC2 instance_type, EC2 ami, SG ingress_rule_count, S3 block_public_acls
      MEDIUM — IAM max_session_duration, S3 versioning
      LOW    — EC2 tags, S3 tags, IAM path
    """
    resources: list[dict[str, Any]] = []

    # --- EC2: match live IDs; intentional attribute drifts below
    for i, inst in enumerate(instances):
        iid = inst["InstanceId"]
        live_type = inst.get("InstanceType", "t3.micro")
        live_ami = inst.get("ImageId", "ami-0demo000000000001")
        live_tags = {
            t["Key"]: t["Value"] for t in inst.get("Tags", []) if "Key" in t
        } or {"Name": f"demo-web-{i + 1:02d}", "driftwatch-demo": "true"}

        # HIGH: instance #2 type (TF says t3.micro, live is t3.small)
        tf_type = "t3.micro" if i == 1 else live_type
        # HIGH: instance #3 AMI mismatch
        tf_ami = "ami-0stale00000000001" if i == 2 else live_ami
        # LOW: instance #4 Name tag drifted in the console
        if i == 3:
            tf_tags = {
                "Name": f"demo-web-{i + 1:02d}-old",
                "driftwatch-demo": "true",
            }
        else:
            tf_tags = live_tags

        resources.append(
            _tf_resource(
                "aws_instance",
                f"web_{i + 1:02d}",
                {
                    "id": iid,
                    "ami": tf_ami,
                    "instance_type": tf_type,
                    "instance_state": inst.get("State", {}).get("Name", "running"),
                    "subnet_id": inst.get("SubnetId", subnet_id),
                    "key_name": inst.get("KeyName", ""),
                    "tags": tf_tags,
                },
            )
        )

    # Phantom EC2 in TF only → missing_in_live
    resources.append(
        _tf_resource(
            "aws_instance",
            "retired_worker",
            {
                "id": "i-tfonly000000001",
                "ami": "ami-0demo000000000001",
                "instance_type": "t3.medium",
                "instance_state": "running",
                "subnet_id": subnet_id,
                "key_name": "",
                "tags": {"Name": "retired-worker"},
            },
        )
    )

    # --- Security groups: match live; drift ingress count on first SG
    for i, sg in enumerate(security_groups):
        sid = sg["GroupId"]
        live_ingress = len(sg.get("IpPermissions", []))
        live_tags = {t["Key"]: t["Value"] for t in sg.get("Tags", []) if "Key" in t}
        # HIGH: TF claims 0 ingress for first SG even if live has rules
        tf_ingress = [] if i == 0 else ([{"from_port": 443}] * live_ingress)
        resources.append(
            _tf_resource(
                "aws_security_group",
                f"sg_{i + 1:02d}",
                {
                    "id": sid,
                    "group_name": sg.get("GroupName", ""),
                    "name": sg.get("GroupName", ""),
                    "description": sg.get("Description", ""),
                    "vpc_id": sg.get("VpcId", ""),
                    "ingress": tf_ingress,
                    "egress": sg.get("IpPermissionsEgress", []),
                    "tags": live_tags or {"Name": sg.get("GroupName", "")},
                },
            )
        )

    # --- S3: include versioning / public-block fields the scanner compares
    # Leave the last live bucket out of TF → missing_in_tf (orphan)
    for i, name in enumerate(buckets[:-1]):
        # HIGH: public ACLs on bucket index 2 (TF False, live True)
        block_acls = "False" if i == 2 else "True"
        # MEDIUM: versioning — TF Disabled, live Enabled on bucket index 4
        versioning = "Disabled"
        # LOW: tags — TF missing Owner that live has on bucket index 5
        tags: dict[str, str] = {"Name": name, "driftwatch-demo": "true"}
        resources.append(
            _tf_resource(
                "aws_s3_bucket",
                f"bucket_{i + 1:02d}",
                {
                    "id": name,
                    "bucket": name,
                    "arn": f"arn:aws:s3:::{name}",
                    "versioning": versioning,
                    "block_public_acls": block_acls,
                    "block_public_policy": "True",
                    "tags": tags,
                },
            )
        )

    # Phantom bucket in TF only
    resources.append(
        _tf_resource(
            "aws_s3_bucket",
            "legacy_archive",
            {
                "id": "demo-legacy-archive",
                "bucket": "demo-legacy-archive",
                "arn": "arn:aws:s3:::demo-legacy-archive",
                "versioning": "Enabled",
                "block_public_acls": "True",
                "block_public_policy": "True",
                "tags": {"Name": "legacy"},
            },
        )
    )

    # --- IAM roles: match live; intentional drifts on roles 3 and 5
    for i, role in enumerate(roles):
        name = role["RoleName"]
        live_duration = int(role.get("MaxSessionDuration", 3600))
        live_path = role.get("Path", "/demo/")
        # MEDIUM: max_session_duration on role 3
        tf_duration = 7200 if i == 2 else live_duration
        # LOW: path on role 5
        tf_path = "/legacy/" if i == 4 else live_path
        tags = {"Name": name, "driftwatch-demo": "true"}
        resources.append(
            _tf_resource(
                "aws_iam_role",
                f"role_{i + 1:02d}",
                {
                    "id": name,
                    "name": name,
                    "path": tf_path,
                    "max_session_duration": tf_duration,
                    "tags": tags,
                },
            )
        )

    return {
        "version": 4,
        "terraform_version": "1.8.0",
        "serial": 1,
        "lineage": "local-demo",
        "resources": resources,
    }


def seed_state_bucket(s3, tfstate: dict[str, Any]) -> None:
    try:
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        print(f"Created S3 bucket: {BUCKET}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code not in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
            raise
        print(f"S3 bucket {BUCKET} already exists")

    s3.put_object(
        Bucket=BUCKET,
        Key="terraform.tfstate",
        Body=json.dumps(tfstate, indent=2),
        ContentType="application/json",
    )
    managed = sum(len(r.get("instances", [])) for r in tfstate["resources"])
    print(f"Seeded terraform.tfstate with {managed} managed resources in {BUCKET}")


def main() -> None:
    time.sleep(3)
    ec2 = get_client("ec2")
    s3 = get_client("s3")
    iam = get_client("iam")

    vpc_id, subnet_id = create_vpc_for_ec2(ec2)
    print(f"Using VPC={vpc_id} subnet={subnet_id}")

    instances = ensure_ec2(ec2, subnet_id)
    security_groups = ensure_security_groups(ec2, vpc_id)
    buckets = ensure_s3_buckets(s3)
    roles = ensure_iam_roles(iam)

    tfstate = build_tfstate(instances, security_groups, buckets, roles, subnet_id)
    seed_state_bucket(s3, tfstate)

    print(
        "Demo seed complete — "
        f"live EC2={len(instances)} SG={len(security_groups)} "
        f"S3={len(buckets)} IAM={len(roles)}"
    )


if __name__ == "__main__":
    main()
