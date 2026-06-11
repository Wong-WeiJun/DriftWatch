"""Tests for app.services.scanner."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.services.scanner import (
    _client,
    get_ec2,
    get_iam_roles,
    get_rds,
    get_s3,
    get_security_groups,
)


# ---------------------------------------------------------------------------
# _client
# ---------------------------------------------------------------------------


class TestClient:
    @patch("app.services.scanner.boto3.client")
    def test_basic_client(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        with patch("app.services.scanner.settings") as mock_settings:
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.AWS_ENDPOINT_URL = None

            result = _client("ec2")
            assert result is mock_client
            mock_boto_client.assert_called_once_with("ec2", region_name="us-east-1")

    @patch("app.services.scanner.boto3.client")
    def test_with_endpoint_url(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        with patch("app.services.scanner.settings") as mock_settings:
            mock_settings.AWS_REGION = "ap-southeast-2"
            mock_settings.AWS_ENDPOINT_URL = "http://localhost:4566"

            result = _client("s3")
            assert result is mock_client
            mock_boto_client.assert_called_once_with(
                "s3",
                region_name="ap-southeast-2",
                endpoint_url="http://localhost:4566",
            )


# ---------------------------------------------------------------------------
# get_ec2
# ---------------------------------------------------------------------------


class TestGetEc2:
    @patch("app.services.scanner._client")
    def test_single_instance(self, mock_client):
        mock_ec2 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-123",
                                "InstanceType": "t3.micro",
                                "ImageId": "ami-abc",
                                "State": {"Name": "running"},
                                "SubnetId": "subnet-1",
                                "VpcId": "vpc-1",
                                "KeyName": "my-key",
                            }
                        ]
                    }
                ]
            }
        ]
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_ec2

        result = get_ec2()

        assert "i-123" in result
        assert result["i-123"]["_type"] == "aws_instance"
        assert result["i-123"]["instance_type"] == "t3.micro"
        assert result["i-123"]["ami"] == "ami-abc"
        assert result["i-123"]["state"] == "running"
        assert result["i-123"]["subnet_id"] == "subnet-1"
        assert result["i-123"]["vpc_id"] == "vpc-1"
        assert result["i-123"]["key_name"] == "my-key"

    @patch("app.services.scanner._client")
    def test_multiple_instances_across_reservations(self, mock_client):
        mock_ec2 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-1",
                                "InstanceType": "t3.micro",
                                "ImageId": "ami-1",
                                "State": {"Name": "running"},
                            },
                        ]
                    }
                ]
            },
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-2",
                                "InstanceType": "t3.large",
                                "ImageId": "ami-2",
                                "State": {"Name": "stopped"},
                            },
                        ]
                    }
                ]
            },
        ]
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_ec2

        result = get_ec2()

        assert len(result) == 2
        assert result["i-1"]["instance_type"] == "t3.micro"
        assert result["i-2"]["state"] == "stopped"

    @patch("app.services.scanner._client")
    def test_missing_optional_fields(self, mock_client):
        """Instance without SubnetId/VpcId/KeyName should have empty strings."""
        mock_ec2 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-123",
                                "InstanceType": "t3.nano",
                                "ImageId": "ami-x",
                                "State": {"Name": "pending"},
                            }
                        ]
                    }
                ]
            }
        ]
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_ec2

        result = get_ec2()
        assert result["i-123"]["subnet_id"] == ""
        assert result["i-123"]["vpc_id"] == ""
        assert result["i-123"]["key_name"] == ""

    @patch("app.services.scanner._client")
    def test_no_reservations(self, mock_client):
        mock_ec2 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = []
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_ec2

        result = get_ec2()
        assert result == {}


# ---------------------------------------------------------------------------
# get_s3
# ---------------------------------------------------------------------------


class TestGetS3:
    @patch("app.services.scanner._client")
    def test_single_bucket(self, mock_client):
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {
            "Buckets": [
                {
                    "Name": "my-bucket",
                    "CreationDate": "2024-01-01T00:00:00Z",
                }
            ]
        }
        mock_s3.get_bucket_versioning.return_value = {
            "Status": "Enabled",
        }
        mock_s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": False,
            }
        }
        mock_client.return_value = mock_s3

        result = get_s3()

        assert "my-bucket" in result
        assert result["my-bucket"]["_type"] == "aws_s3_bucket"
        assert result["my-bucket"]["bucket"] == "my-bucket"
        assert result["my-bucket"]["versioning"] == "Enabled"
        assert result["my-bucket"]["block_public_acls"] == "True"
        assert result["my-bucket"]["block_public_policy"] == "False"

    @patch("app.services.scanner._client")
    def test_multiple_buckets(self, mock_client):
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {
            "Buckets": [
                {"Name": "bucket-a"},
                {"Name": "bucket-b"},
            ]
        }
        mock_s3.get_bucket_versioning.return_value = {"Status": "Suspended"}
        mock_s3.get_public_access_block.return_value = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": False,
                "BlockPublicPolicy": False,
            }
        }
        mock_client.return_value = mock_s3

        result = get_s3()

        assert len(result) == 2
        assert result["bucket-a"]["versioning"] == "Suspended"
        assert result["bucket-b"]["block_public_acls"] == "False"

    @patch("app.services.scanner._client")
    def test_versioning_exception_graceful(self, mock_client):
        """If get_bucket_versioning fails, versioning defaults to Disabled."""
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket"}]}
        mock_s3.get_bucket_versioning.side_effect = Exception("No access")
        mock_s3.get_public_access_block.side_effect = Exception("No access")
        mock_client.return_value = mock_s3

        result = get_s3()

        assert result["my-bucket"]["versioning"] == "Disabled"
        assert result["my-bucket"]["block_public_acls"] == "False"

    @patch("app.services.scanner._client")
    def test_empty_bucket_list(self, mock_client):
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {"Buckets": []}
        mock_client.return_value = mock_s3

        result = get_s3()
        assert result == {}

    @patch("app.services.scanner._client")
    def test_public_access_block_exception(self, mock_client):
        """If get_public_access_block fails, defaults should apply."""
        mock_s3 = MagicMock()
        mock_s3.list_buckets.return_value = {"Buckets": [{"Name": "my-bucket"}]}
        mock_s3.get_bucket_versioning.return_value = {}
        mock_s3.get_public_access_block.side_effect = ClientError(
            {
                "Error": {
                    "Code": "NoSuchPublicAccessBlockConfiguration",
                    "Message": "None",
                }
            },
            "GetPublicAccessBlock",
        )
        mock_client.return_value = mock_s3

        result = get_s3()
        assert result["my-bucket"]["block_public_acls"] == "False"
        assert result["my-bucket"]["block_public_policy"] == "False"


# ---------------------------------------------------------------------------
# get_security_groups
# ---------------------------------------------------------------------------


class TestGetSecurityGroups:
    @patch("app.services.scanner._client")
    def test_single_security_group(self, mock_client):
        mock_ec2 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "SecurityGroups": [
                    {
                        "GroupId": "sg-123",
                        "GroupName": "web_sg",
                        "Description": "Web security group",
                        "VpcId": "vpc-1",
                        "IpPermissions": [
                            {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80}
                        ],
                        "IpPermissionsEgress": [{"IpProtocol": "-1"}],
                    }
                ]
            }
        ]
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_ec2

        result = get_security_groups()

        assert "sg-123" in result
        assert result["sg-123"]["_type"] == "aws_security_group"
        assert result["sg-123"]["name"] == "web_sg"
        assert result["sg-123"]["desc"] == "Web security group"
        assert result["sg-123"]["vpc_id"] == "vpc-1"
        assert result["sg-123"]["ingress_rule_count"] == "1"
        assert result["sg-123"]["egress_rule_count"] == "1"

    @patch("app.services.scanner._client")
    def test_empty_permissions(self, mock_client):
        mock_ec2 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "SecurityGroups": [
                    {
                        "GroupId": "sg-456",
                        "GroupName": "empty_sg",
                        "Description": "Empty",
                        "VpcId": "vpc-2",
                        "IpPermissions": [],
                        "IpPermissionsEgress": [],
                    }
                ]
            }
        ]
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_ec2

        result = get_security_groups()

        assert result["sg-456"]["ingress_rule_count"] == "0"
        assert result["sg-456"]["egress_rule_count"] == "0"

    @patch("app.services.scanner._client")
    def test_no_security_groups(self, mock_client):
        mock_ec2 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = []
        mock_ec2.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_ec2

        result = get_security_groups()
        assert result == {}


# ---------------------------------------------------------------------------
# get_iam_roles
# ---------------------------------------------------------------------------


class TestGetIamRoles:
    @patch("app.services.scanner._client")
    def test_single_role(self, mock_client):
        mock_iam = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Roles": [
                    {
                        "RoleName": "my-role",
                        "Path": "/service/",
                        "MaxSessionDuration": 3600,
                    }
                ]
            }
        ]
        mock_iam.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_iam

        result = get_iam_roles()

        assert "my-role" in result
        assert result["my-role"]["_type"] == "aws_iam_role"
        assert result["my-role"]["name"] == "my-role"
        assert result["my-role"]["path"] == "/service/"
        assert result["my-role"]["max_session_duration"] == "3600"

    @patch("app.services.scanner._client")
    def test_role_with_defaults(self, mock_client):
        """Role with no explicit MaxSessionDuration should default to 3600."""
        mock_iam = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Roles": [
                    {
                        "RoleName": "basic-role",
                        "Path": "/",
                    }
                ]
            }
        ]
        mock_iam.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_iam

        result = get_iam_roles()

        assert result["basic-role"]["max_session_duration"] == "3600"

    @patch("app.services.scanner._client")
    def test_no_roles(self, mock_client):
        mock_iam = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = []
        mock_iam.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_iam

        result = get_iam_roles()
        assert result == {}


# ---------------------------------------------------------------------------
# get_rds
# ---------------------------------------------------------------------------


class TestGetRds:
    @patch("app.services.scanner._client")
    def test_single_instance(self, mock_client):
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DBInstances": [
                    {
                        "DBInstanceIdentifier": "my-db",
                        "DBInstanceClass": "db.t3.micro",
                        "Engine": "mysql",
                        "EngineVersion": "8.0",
                        "MultiAZ": False,
                        "PubliclyAccessible": False,
                        "DeletionProtection": True,
                    }
                ]
            }
        ]
        mock_rds.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_rds

        result = get_rds()

        assert "my-db" in result
        assert result["my-db"]["_type"] == "aws_rds_instances"
        assert result["my-db"]["instance_class"] == "db.t3.micro"
        assert result["my-db"]["engine"] == "mysql"
        assert result["my-db"]["engine_version"] == "8.0"
        assert result["my-db"]["multi_az"] == "False"
        assert result["my-db"]["publicly_accessible"] == "False"
        assert result["my-db"]["deletion_protection"] == "True"

    @patch("app.services.scanner._client")
    def test_multiple_instances(self, mock_client):
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "DBInstances": [
                    {
                        "DBInstanceIdentifier": "db-1",
                        "DBInstanceClass": "db.t3.small",
                        "Engine": "postgres",
                        "MultiAZ": True,
                        "PubliclyAccessible": True,
                        "DeletionProtection": False,
                    },
                    {
                        "DBInstanceIdentifier": "db-2",
                        "DBInstanceClass": "db.t3.micro",
                        "Engine": "mysql",
                        "MultiAZ": False,
                        "PubliclyAccessible": False,
                        "DeletionProtection": False,
                    },
                ]
            }
        ]
        mock_rds.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_rds

        result = get_rds()

        assert len(result) == 2
        assert result["db-1"]["multi_az"] == "True"
        assert result["db-1"]["publicly_accessible"] == "True"
        assert result["db-2"]["engine"] == "mysql"

    @patch("app.services.scanner._client")
    def test_internal_failure_graceful(self, mock_client):
        """InternalFailure should return empty dict (e.g. LocalStack)."""
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        error = ClientError(
            {"Error": {"Code": "InternalFailure", "Message": "RDS not available"}},
            "DescribeDBInstances",
        )
        mock_paginator.paginate.side_effect = error
        mock_rds.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_rds

        result = get_rds()
        assert result == {}

    @patch("app.services.scanner._client")
    def test_other_client_error_raises(self, mock_client):
        """Non-InternalFailure errors should propagate."""
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        error = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "No permission"}},
            "DescribeDBInstances",
        )
        mock_paginator.paginate.side_effect = error
        mock_rds.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_rds

        with pytest.raises(ClientError) as exc_info:
            get_rds()
        assert exc_info.value.response["Error"]["Code"] == "AccessDenied"

    @patch("app.services.scanner._client")
    def test_no_instances(self, mock_client):
        mock_rds = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"DBInstances": []}]
        mock_rds.get_paginator.return_value = mock_paginator
        mock_client.return_value = mock_rds

        result = get_rds()
        assert result == {}
