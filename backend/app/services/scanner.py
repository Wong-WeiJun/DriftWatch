import boto3
from typing import Any
from app.core.config import settings

_session = boto3.Session(region_name=settings.AWS_REGION)

def get_ec2() -> dict[str, dict[str, Any]]:
    ec2 = _session.client("ec2")
    instances = {}
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                iid = instance["InstanceId"]
                instances[iid] = {
                    "_type": "aws_instance",
                    "id": iid,
                    "instance_type": instance.get("InstanceType", ""),
                    "ami": instance.get("ImageId", ""),
                    "state": instance["State"]["Name"],
                    "subnet_id": instance.get("SubnetId", ""),
                    "vpc_id": instance.get("VpcId", ""),
                    "key_name": instance.get("KeyName", ""),
                }
    return instances

def get_s3() -> dict[str, dict[str, Any]]:
    s3 = _session.client("s3")
    buckets ={}
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

        buckets[name] = {
            "_type": "aws_s3_bucket",
            "id": name,
            "bucket": name,
            "versioning": versioning,
            "block_public_acls": str(public_block.get("BlockPublicAcls", False)),
            "block_public_policy": str(public_block.get("BlockPublicPolicy", False))
        }
    return buckets

# print(get_s3())
print(get_ec2())

