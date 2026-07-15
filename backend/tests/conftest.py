import pytest


@pytest.fixture
def mock_tf_state():
    """Return a parsed Terraform state dict as produced by parse_tfstate_from_s3."""
    return {
        "i-1234567890abcdef0": {
            "_type": "aws_instance",
            "_tf_type": "aws_instance",
            "_name": "web",
            "_mode": "managed",
            "id": "i-1234567890abcdef0",
            "instance_type": "t3.medium",
            "ami": "ami-12345",
            "state": "running",
            "subnet_id": "subnet-123",
            "vpc_id": "vpc-123",
            "key_name": "my-key",
        },
        "my-bucket": {
            "_type": "aws_s3_bucket",
            "_tf_type": "aws_s3_bucket",
            "_name": "assets",
            "_mode": "managed",
            "id": "my-bucket",
            "bucket": "my-bucket",
        },
        "sg-123": {
            "_type": "aws_security_group",
            "_tf_type": "aws_security_group",
            "_name": "web_sg",
            "_mode": "managed",
            "id": "sg-123",
            "name": "web_sg",
            "description": "Web security group",
            "vpc_id": "vpc-123",
            "ingress_rule_count": "2",
            "egress_rule_count": "1",
        },
        "my-role": {
            "_type": "aws_iam_role",
            "_tf_type": "aws_iam_role",
            "_name": "ecs_role",
            "_mode": "managed",
            "id": "my-role",
            "name": "my-role",
            "path": "/",
            "max_session_duration": "3600",
        },
    }


@pytest.fixture
def mock_live_resources():
    return {
        "aws_instance": {
            "i-1234567890abcdef0": {
                "_type": "aws_instance",
                "id": "i-1234567890abcdef0",
                "instance_type": "t3.medium",
                "ami": "ami-12345",
                "state": "running",
                "subnet_id": "subnet-123",
                "vpc_id": "vpc-123",
                "key_name": "my-key",
            }
        },
        "aws_s3_bucket": {
            "my-bucket": {
                "_type": "aws_s3_bucket",
                "id": "my-bucket",
                "bucket": "my-bucket",
                "versioning": "Enabled",
                "block_public_acls": "True",
                "block_public_policy": "True",
            }
        },
        "aws_security_group": {
            "sg-123": {
                "_type": "aws_security_group",
                "id": "sg-123",
                "name": "web_sg",
                "description": "Web security group",
                "vpc_id": "vpc-123",
                "ingress_rule_count": "2",
                "egress_rule_count": "1",
            }
        },
        "aws_iam_role": {
            "my-role": {
                "_type": "aws_iam_role",
                "id": "my-role",
                "name": "my-role",
                "path": "/",
                "max_session_duration": "3600",
            }
        },
        "aws_rds_instances": {
            "my-db": {
                "_type": "aws_rds_instances",
                "id": "my-db",
                "instance_class": "db.t3.micro",
                "engine": "mysql",
                "engine_version": "8.0",
                "multi_az": "False",
                "publicly_accessible": "False",
                "deletion_protection": "True",
            }
        },
    }
