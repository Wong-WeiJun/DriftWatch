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

def get_security_groups() -> dict[str, dict[str, Any]]:
    ec2 = _session.client("ec2")
    sgs = {}
    paginator = ec2.get_paginator("describe_security_groups")
    for page in paginator.paginate():
        for sg in page["SecurityGroups"]:
            sid = sg["GroupId"]
            sgs[sid] = {
                "_type": "aws_security_group",
                "id": sid,
                "name": sg.get("GroupName", ""),
                "desc": sg.get("Description", ""),
                "vpc_id": sg.get("VpcId", ""),
                "ingress_rule_count": str(len(sg.get("IpPermissions", []))),
                "egress_rule_count": str(len(sg.get("IpPermissionsEgress", []))),
            }
    return sgs

def get_iam_roles() -> dict[str, dict[str, Any]]:
    iam = _session.client("iam")
    roles = {}
    paginator = iam.get_paginator("list_roles")
    for page in paginator.paginate():
        for role in page["Roles"]:
            name = role["RoleName"]
            roles[name]= {
                "_type": "aws_iam_role",
                "id": name,
                "name": name,
                "path": role.get("Path", "/"),
                "max_session_duration": str(role.get("MaxSessionDuration", 3600)),
            }
    return roles

def get_rds() -> dict[str, dict[str, Any]]:
    rds = _session.client("rds")
    instances = {}
    paginator =rds.get_paginator("describe_db_instances")
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
    return instances


print(get_s3())
print(get_rds())

