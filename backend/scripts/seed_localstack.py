"""
Seed LocalStack with a minimal S3 bucket, dummy terraform.tfstate, and
some live AWS resources (EC2, IAM, SG) so the drift scanner has data
to compare against.
"""
import json
import time
import boto3
from botocore.exceptions import ClientError

REGION = "ap-southeast-2"
ENDPOINT = "http://localstack:4566"
BUCKET = "driftwatch-local-state"


def get_client(service: str):
    return boto3.client("s3" if service == "s3" else service,
                        endpoint_url=ENDPOINT, region_name=REGION)


TFSTATE = {
    "version": 4,
    "terraform_version": "1.8.0",
    "serial": 1,
    "lineage": "local-dev",
    "resources": [
        {
            "mode": "managed",
            "type": "aws_instance",
            "name": "example",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {
                    "schema_version": 1,
                    "attributes": {
                        "id": "i-local-001",
                        "ami": "ami-12345",
                        "instance_type": "t3.micro",
                        "subnet_id": "subnet-abc",
                        "vpc_id": "vpc-123",
                        "key_name": "my-key",
                        "tags": {"Name": "example"},
                    },
                }
            ],
        },
        {
            "mode": "managed",
            "type": "aws_s3_bucket",
            "name": "state",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {
                    "schema_version": 0,
                    "attributes": {
                        "id": "my-bucket",
                        "bucket": "my-bucket",
                        "arn": "arn:aws:s3:::my-bucket",
                        "tags": {"Name": "state"},
                    },
                }
            ],
        },
        {
            "mode": "managed",
            "type": "aws_s3_bucket_public_access_block",
            "name": "state_block",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {
                    "schema_version": 0,
                    "attributes": {
                        "id": "my-bucket",
                        "bucket": "my-bucket",
                        "block_public_acls": True,
                        "block_public_policy": True,
                        "ignore_public_acls": True,
                        "restrict_public_buckets": True,
                    },
                }
            ],
        },
        {
            "mode": "managed",
            "type": "aws_security_group",
            "name": "default",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {
                    "schema_version": 1,
                    "attributes": {
                        "id": "sg-local-001",
                        "group_name": "default",
                        "description": "default sg",
                        "vpc_id": "vpc-123",
                        "tags": {"Name": "default"},
                    },
                }
            ],
        },
        {
            "mode": "managed",
            "type": "aws_iam_role",
            "name": "exec",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {
                    "schema_version": 0,
                    "attributes": {
                        "id": "exec-role",
                        "name": "exec-role",
                        "path": "/",
                        "max_session_duration": 3600,
                        "assume_role_policy": "policy",
                    },
                }
            ],
        },
        {
            "mode": "managed",
            "type": "aws_db_instance",
            "name": "main",
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [
                {
                    "schema_version": 1,
                    "attributes": {
                        "id": "local-db",
                        "instance_class": "db.t3.micro",
                        "engine": "postgres",
                        "engine_version": "14.0",
                        "multi_az": False,
                        "publicly_accessible": False,
                        "deletion_protection": False,
                        "allocated_storage": 20,
                        "tags": {"Name": "main"},
                    },
                }
            ],
        },
    ],
}


def create_vpc_for_ec2(ec2):
    """Create a minimal VPC + subnet needed by LocalStack EC2 instances."""
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "tag:Name", "Values": ["seed-vpc"]}])
    if vpcs["Vpcs"]:
        return vpcs["Vpcs"][0]["VpcId"]

    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")
    vpc_id = vpc["Vpc"]["VpcId"]
    ec2.create_tags(Resources=[vpc_id], Tags=[{"Key": "Name", "Value": "seed-vpc"}])

    subnet = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24")
    subnet_id = subnet["Subnet"]["SubnetId"]
    ec2.create_tags(Resources=[subnet_id], Tags=[{"Key": "Name", "Value": "seed-subnet"}])
    return vpc_id


def seed_s3():
    s3 = get_client("s3")
    try:
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        print(f"Created S3 bucket: {BUCKET}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
            print(f"S3 bucket {BUCKET} already exists, skipping")
        else:
            raise

    s3.put_object(
        Bucket=BUCKET,
        Key="terraform.tfstate",
        Body=json.dumps(TFSTATE),
        ContentType="application/json",
    )
    print(f"Seeded terraform.tfstate in {BUCKET}")


def seed_ec2(vpc_id):
    ec2 = get_client("ec2")
    # Create the matching instance so the scanner finds something live
    try:
        ec2.run_instances(
            ImageId="ami-12345",
            MinCount=1,
            MaxCount=1,
            InstanceType="t3.micro",
            KeyName="my-key",
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": [
                        {"Key": "Name", "Value": "example"},
                    ],
                }
            ],
        )
        print("Created EC2 instance")
    except ClientError as e:
        print(f"EC2 instance creation skipped: {e}")

    # Create matching security group (with a non-conflicting name)
    try:
        ec2.create_security_group(
            GroupName="driftwatch-sg",
            Description="default sg",
            VpcId=vpc_id,
            TagSpecifications=[
                {
                    "ResourceType": "security-group",
                    "Tags": [
                        {"Key": "Name", "Value": "driftwatch-sg"},
                    ],
                }
            ],
        )
        print("Created Security Group: driftwatch-sg")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("InvalidGroup.Duplicate", "InvalidGroup.Duplicate"):
            print("Security group already exists, skipping")
        else:
            raise


def seed_iam():
    iam = get_client("iam")
    try:
        iam.create_role(
            RoleName="exec-role",
            AssumeRolePolicyDocument="{}",
            Path="/",
            Tags=[{"Key": "Name", "Value": "exec"}],
        )
        print("Created IAM role: exec-role")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "EntityAlreadyExists":
            print("IAM role exec-role already exists, skipping")
        else:
            raise


def seed_rds():
    # RDS is not available in free LocalStack;
    # skip silently so the container doesn't crash.
    print("RDS is a LocalStack Pro feature — skipping")


def main():
    time.sleep(3)  # give LocalStack time to finish starting
    seed_s3()
    ec2 = get_client("ec2")
    vpc_id = create_vpc_for_ec2(ec2)
    seed_ec2(vpc_id)
    seed_iam()
    seed_rds()


if __name__ == "__main__":
    main()
